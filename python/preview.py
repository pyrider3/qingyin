"""Live preview: tail the growing recording and print partial text as JSON lines.

CPU-only streaming Paraformer. Preview text is advisory; the final result still comes
from the normal recognizer after recording stops. Never loads CUDA and never writes audio.
"""
import array
import json
import os
import struct
import sys
import time
from pathlib import Path

FILES = ('encoder.int8.onnx', 'decoder.int8.onnx', 'tokens.txt')
RATE = 16000


def model_dir():
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'qingyin/preview/streaming-paraformer-zh-en'


def installed(path=None):
    path = Path(path or model_dir())
    return all((path/name).is_file() for name in FILES)


def data_offset(header):
    """Offset of PCM data in a (possibly still-growing) WAV header, or None if incomplete."""
    if header[:4] != b'RIFF' or header[8:12] != b'WAVE': raise ValueError('不是 WAV 录音')
    pos = 12
    while pos + 8 <= len(header):
        name, size = header[pos:pos+4], struct.unpack('<I', header[pos+4:pos+8])[0]
        if name == b'data': return pos + 8
        pos += 8 + size + (size & 1)
    return None


class Tail:
    """Yield new float32 samples from a 16 kHz mono s16 WAV that is still being written."""
    def __init__(self, path):
        self.path = Path(path); self.offset = None; self.position = 0; self.spare = b''

    def read(self):
        with self.path.open('rb') as f:  # FileNotFoundError means the recording ended
            if self.offset is None:
                self.offset = data_offset(f.read(4096))
                if self.offset is None: return []
                self.position = self.offset
            f.seek(self.position); new = f.read(RATE * 2 * 5)
        self.position += len(new)
        raw = self.spare + new; usable = len(raw) // 2 * 2; self.spare = raw[usable:]
        return [v / 32768 for v in array.array('h', raw[:usable])]


def serve(wav, directory=None, recognizer=None, clock=time.sleep, out=sys.stdout):
    import numpy as np
    from normalize import simplified
    if recognizer is None:
        import sherpa_onnx
        directory = Path(directory or model_dir())
        recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
            tokens=str(directory/'tokens.txt'), encoder=str(directory/'encoder.int8.onnx'),
            decoder=str(directory/'decoder.int8.onnx'), num_threads=2, provider='cpu',
            decoding_method='greedy_search')
    stream = recognizer.create_stream(); tail = Tail(wav); last = None
    print(json.dumps({'ready': True}), file=out, flush=True)
    while True:
        try: samples = tail.read()
        except FileNotFoundError: return  # recording finished or canceled
        if samples:
            stream.accept_waveform(RATE, np.asarray(samples, dtype=np.float32))
            while recognizer.is_ready(stream): recognizer.decode_stream(stream)
            text = simplified(recognizer.get_result(stream).strip())
            if text != last:
                last = text; print(json.dumps({'text': text}, ensure_ascii=False), file=out, flush=True)
        else: clock(0.1)


if __name__ == '__main__':
    try: serve(sys.argv[1])
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), flush=True); sys.exit(1)
