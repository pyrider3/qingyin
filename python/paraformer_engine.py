"""Offline Paraformer (sherpa-onnx) worker: CPU only, same JSON-line protocol as asr.py."""
import json
import subprocess
import sys
from pathlib import Path

WEIGHTS = 'model.int8.onnx'
TOKENS = 'tokens.txt'


def is_model(path):
    path = Path(path)
    return (path/WEIGHTS).is_file() and (path/TOKENS).is_file()


def serve(model_dir):
    import numpy as np
    from normalize import simplified, without_final_period
    from punctuation import restore
    import learning
    try:
        import sherpa_onnx
        recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
            paraformer=str(Path(model_dir)/WEIGHTS), tokens=str(Path(model_dir)/TOKENS),
            num_threads=4, provider='cpu', decoding_method='greedy_search')
    except Exception as exc:
        print(f'模型加载失败：{exc}', file=sys.stderr, flush=True)
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), flush=True)
        sys.exit(1)
    print(json.dumps({'ready': True, 'device': 'cpu'}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            audio = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', request['path'], '-f', 'f32le',
                                    '-ac', '1', '-ar', '16000', 'pipe:1'], check=True, capture_output=True).stdout
            samples = np.frombuffer(audio, dtype=np.float32).copy()
            vocabulary = {'rules': []}
            if request.get('learning', True):
                try:
                    vocabulary = learning.load()
                except Exception as exc:
                    print(f'个人词库读取失败，保留原识别：{exc}', file=sys.stderr, flush=True)
            stream = recognizer.create_stream()
            stream.accept_waveform(16000, samples)
            recognizer.decode_stream(stream)
            text = simplified(stream.result.text.strip())
            # Paraformer has no prompt/hotword input: only post-hoc personal corrections apply.
            text = learning.apply(text, vocabulary)
            if request.get('punctuation', True):
                try:
                    text = restore(text)
                except Exception as exc:
                    print(f'补标点失败，保留原转写：{exc}', file=sys.stderr, flush=True)
            print(json.dumps({'text': without_final_period(text)}, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(f'转写失败：{exc}', file=sys.stderr, flush=True)
            print(json.dumps({'error': str(exc)}, ensure_ascii=False), flush=True)
        finally:
            for key in ('request', 'audio', 'samples', 'vocabulary', 'stream', 'text', 'line'):
                globals().pop(key, None)
