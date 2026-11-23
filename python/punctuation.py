"""Local CPU punctuation restoration; preserve source characters and whitespace."""
from pathlib import Path
import re

MODEL_NAME = 'sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8'
MARKS = set('，。？！；：,.?!;:')
INSERTABLE = set('，。？！；：')
_model = None


def model_path():
    return Path.home() / '.local/share/qingyin/punctuation' / MODEL_NAME / 'model.int8.onnx'


def merge_punctuation(source, prediction):
    # The model can change spacing or duplicate existing punctuation. Only take
    # punctuation positions, never its rewritten text or whitespace.
    original = ''.join(c for c in source if c not in MARKS and not c.isspace())
    candidate = ''.join(c for c in prediction if c not in MARKS and not c.isspace())
    if original != candidate:
        return source
    additions = {}
    boundary = 0
    for char in prediction:
        if char in INSERTABLE:
            additions[boundary] = char
        elif char not in MARKS and not char.isspace():
            boundary += 1
    # Never insert punctuation inside an ASCII identifier, email, URL or path.
    protected = set()
    for match in re.finditer(r'[A-Za-z0-9_~/.@:+\\-]+', source):
        protected.update(range(match.start() + 1, match.end()))
    result = []
    boundary = 0
    for index, char in enumerate(source):
        result.append(char)
        if char in MARKS or char.isspace():
            continue
        boundary += 1
        mark = additions.get(boundary)
        following = source[index + 1:].lstrip()
        if mark and index + 1 not in protected and (not following or following[0] not in MARKS):
            result.append(mark)
    return ''.join(result)


def restore(text):
    global _model
    if not text or not re.search(r'[\u4e00-\u9fff]', text):
        return text
    if _model is None:
        import sherpa_onnx
        path = model_path()
        if not path.is_file():
            raise FileNotFoundError('本地标点模型不存在，请按安装说明下载标点模型')
        _model = sherpa_onnx.OfflinePunctuation(sherpa_onnx.OfflinePunctuationConfig(
            model=sherpa_onnx.OfflinePunctuationModelConfig(
                ct_transformer=str(path), num_threads=2, provider='cpu')))
    return merge_punctuation(text, _model.add_punctuation(text))


_worker = None


def close_isolated():
    global _worker
    if _worker is not None:
        try:
            _worker.kill()
            _worker.wait(timeout=2)
        except Exception:
            pass
        _worker = None


def restore_isolated(text):
    """Avoid native symbol collisions between Whisper VAD and sherpa ORT, reusing one warm worker."""
    global _worker
    if not text or not re.search(r'[\u4e00-\u9fff]', text):
        return text
    import atexit
    import json
    import os
    import select
    import subprocess
    import sys

    if _worker is None or _worker.poll() is not None:
        close_isolated()
        _worker = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name('punctuation_worker.py'))],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
            env={**os.environ, 'QINGYIN_ASR_PARENT': str(os.getpid())},
        )
        atexit.register(close_isolated)
    try:
        _worker.stdin.write(json.dumps({'text': text}, ensure_ascii=False) + '\n')
        _worker.stdin.flush()
        ready, _, _ = select.select([_worker.stdout], [], [], 60)
        if not ready:
            close_isolated()
            raise RuntimeError('标点进程超时，原转写已保留')
        line = _worker.stdout.readline()
    except Exception:
        close_isolated()
        raise
    if not line.strip():
        code = _worker.poll()
        close_isolated()
        raise RuntimeError(f'标点进程意外退出（退出码 {code}），原转写已保留')
    reply = json.loads(line)
    if 'error' in reply:
        close_isolated()
        raise RuntimeError(reply['error'])
    if not isinstance(reply.get('text'), str):
        close_isolated()
        raise RuntimeError('标点进程返回了无效结果，原转写已保留')
    return reply['text']
