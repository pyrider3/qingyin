"""Isolated CPU punctuation process; never import Whisper's ONNX runtime."""
import ctypes
import json
import os
import signal
import sys

# Canceling the ASR parent must also stop this process and release its memory.
parent_pid = int(os.environ.get('QINGYIN_ASR_PARENT', os.getppid()))
libc = ctypes.CDLL(None, use_errno=True)
if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
    raise OSError(ctypes.get_errno(), '无法设置标点进程的退出保护')
if os.getppid() != parent_pid or parent_pid == 1:
    sys.exit(1)

from punctuation import restore
try:
    text = json.load(sys.stdin)['text']
    print(json.dumps({'text': restore(text)}, ensure_ascii=False), flush=True)
except Exception as exc:
    print(json.dumps({'error': str(exc)}, ensure_ascii=False), flush=True)
    sys.exit(1)
