"""Live preview: tail the growing recording and print partial text as JSON lines.

CPU-only streaming recognizer (prefers lightweight X-ASR Zipformer streaming with
built-in bilingual zh-en & punctuation; falls back to streaming Paraformer).
Preview text is advisory; the final result still comes from the main recognizer.
Never loads CUDA and never writes audio.
"""
import array
import json
import os
import select
import struct
import sys
import time
from pathlib import Path

FILES = ('encoder.int8.onnx', 'decoder.int8.onnx', 'tokens.txt')
XASR_FILES = ('encoder.int8.onnx', 'decoder.onnx', 'joiner.int8.onnx', 'tokens.txt')
RATE = 16000


def _preview_root():
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'qingyin/preview'


def model_dir():
    return _preview_root() / 'streaming-paraformer-zh-en'


def xasr_model_dir():
    return _preview_root() / 'x-asr-streaming-zh-en'


def is_xasr(path) -> bool:
    path = Path(path)
    return all((path / name).is_file() for name in XASR_FILES)


def is_paraformer(path) -> bool:
    path = Path(path)
    return all((path / name).is_file() for name in FILES)


def active_model_dir(path=None):
    if path is not None:
        return Path(path)
    if is_xasr(xasr_model_dir()):
        return xasr_model_dir()
    return model_dir()


def installed(path=None):
    if path is not None:
        return is_xasr(path) or is_paraformer(path)
    return is_xasr(xasr_model_dir()) or is_paraformer(model_dir())


def data_offset(header):
    """Offset of PCM data in a (possibly still-growing) WAV header, or None if incomplete."""
    if header[:4] != b'RIFF' or header[8:12] != b'WAVE':
        raise ValueError('不是 WAV 录音')
    pos = 12
    while pos + 8 <= len(header):
        name, size = header[pos:pos + 4], struct.unpack('<I', header[pos + 4:pos + 8])[0]
        if name == b'data':
            return pos + 8
        pos += 8 + size + (size & 1)
    return None


class Tail:
    """Yield new float32 samples from a 16 kHz mono s16 WAV that is still being written."""
    def __init__(self, path):
        self.path = Path(path)
        self.offset = None
        self.position = 0
        self.spare = b''

    def read(self):
        with self.path.open('rb') as f:  # FileNotFoundError means the recording ended
            if self.offset is None:
                self.offset = data_offset(f.read(4096))
                if self.offset is None:
                    return []
                self.position = self.offset
            f.seek(self.position)
            new = f.read(RATE * 2 * 5)
        self.position += len(new)
        raw = self.spare + new
        usable = len(raw) // 2 * 2
        self.spare = raw[usable:]
        return [v / 32768 for v in array.array('h', raw[:usable])]


def load_recognizer(directory=None):
    import sherpa_onnx

    directory = active_model_dir(directory)
    if is_xasr(directory):
        return sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(directory / 'tokens.txt'),
            encoder=str(directory / 'encoder.int8.onnx'),
            decoder=str(directory / 'decoder.onnx'),
            joiner=str(directory / 'joiner.int8.onnx'),
            num_threads=2,
            provider='cpu',
            decoding_method='greedy_search',
        )
    return sherpa_onnx.OnlineRecognizer.from_paraformer(
        tokens=str(directory / 'tokens.txt'),
        encoder=str(directory / 'encoder.int8.onnx'),
        decoder=str(directory / 'decoder.int8.onnx'),
        num_threads=2,
        provider='cpu',
        decoding_method='greedy_search',
    )


def serve(wav, directory=None, recognizer=None, clock=time.sleep, out=sys.stdout, stop_check=None):
    import numpy as np
    from normalize import clean_spacing, simplified

    if recognizer is None:
        recognizer = load_recognizer(directory)
    stream = recognizer.create_stream()
    tail = Tail(wav)
    last = None
    print(json.dumps({'ready': True}), file=out, flush=True)
    while True:
        if stop_check and stop_check():
            return
        try:
            samples = tail.read()
        except FileNotFoundError:
            return  # recording finished or canceled
        if samples:
            stream.accept_waveform(RATE, np.asarray(samples, dtype=np.float32))
            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)
            text = clean_spacing(simplified(recognizer.get_result(stream).strip()))
            if text != last:
                last = text
                print(json.dumps({'text': text}, ensure_ascii=False), file=out, flush=True)
        else:
            clock(0.06)


def serve_resident(directory=None):
    """Persistent preview worker: keep weights warm across utterances."""
    recognizer = load_recognizer(directory)
    print(json.dumps({'ready': True}), flush=True)
    for raw in sys.stdin:
        if not raw.strip():
            continue
        req = json.loads(raw)
        wav = req.get('wav')
        if not wav:
            print(json.dumps({'done': True}), flush=True)
            continue

        def stopped():
            ready, _, _ = select.select([sys.stdin], [], [], 0)
            if not ready:
                return False
            line = sys.stdin.readline()
            return not line or json.loads(line).get('stop', False)

        serve(wav, recognizer=recognizer, stop_check=stopped)
        print(json.dumps({'done': True}), flush=True)


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['--resident']:
            serve_resident()
        else:
            serve(sys.argv[1])
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), flush=True)
        sys.exit(1)
