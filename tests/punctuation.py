"""Check insertion-only punctuation; real model smoke check is opt-in."""
import sys
import os
import subprocess
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'python'))
from punctuation import merge_punctuation, restore

assert merge_punctuation('你好，世界', '你好，，世界。') == '你好，世界。'
assert merge_punctuation('使用 ChatGPT 处理文档', '使用ChatGPT处理文档。') == '使用 ChatGPT 处理文档。'
assert merge_punctuation('你好', '您好。') == '你好'  # Reject changed words.
assert merge_punctuation('版本 1.2 邮箱 a@b.com 路径 /a/b',
                         '版本1.，2邮箱a@b。com路径/a/，b。') == '版本 1.2 邮箱 a@b.com 路径 /a/b。'
assert merge_punctuation('你好\n世界', '你好世界。') == '你好\n世界。'
assert restore('') == ''
assert restore('hello world') == 'hello world'
print('PASS: existing punctuation, source words, spacing, identifiers and line breaks preserved')
if '--model' in sys.argv:
    import time
    source = '我今天想把这个功能改一下识别出来之后只加标点不要自动换段你觉得这样可以吗'
    start = time.monotonic()
    result = restore(source)
    assert '，' in result and result.endswith('？'), result
    assert ''.join(c for c in result if c not in '，。？！；：') == source
    assert '\n' not in result
    assert restore('你好，世界。今天天气不错你想出去吗') == '你好，世界。今天天气不错，你想出去吗？'
    rows = subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid,used_gpu_memory', '--format=csv,noheader'], text=True)
    assert not any(row.split(',')[0].strip() == str(os.getpid()) for row in rows.splitlines()), 'CPU 标点进程不应占用显存'
    print(f'PASS: offline CPU model ({time.monotonic()-start:.3f}s): {result}')
