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


def restore_isolated(text):
    """Avoid native symbol collisions between Whisper VAD and sherpa ORT."""
    if not text or not re.search(r'[\u4e00-\u9fff]', text):
        return text
    import json
    import os
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name('punctuation_worker.py'))],
        input=json.dumps({'text': text}, ensure_ascii=False),
        text=True, capture_output=True, timeout=60,
        env={**os.environ, 'QINGYIN_ASR_PARENT': str(os.getpid())})
    if result.stderr:
        print(result.stderr, file=sys.stderr, end='')
    if not result.stdout.strip():
        raise RuntimeError(f'标点进程意外退出（退出码 {result.returncode}），原转写已保留')
    reply = json.loads(result.stdout)
    if 'error' in reply:
        raise RuntimeError(reply['error'])
    if result.returncode != 0 or not isinstance(reply.get('text'), str):
        raise RuntimeError('标点进程返回了无效结果，原转写已保留')
    return reply['text']
