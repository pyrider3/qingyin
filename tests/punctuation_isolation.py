"""Regression: cancel parent stops punctuation; optional real VAD/CUDA integration."""
from pathlib import Path
import os
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
worker = root / 'python/punctuation_worker.py'
code = '''import os,subprocess,sys,time
p=subprocess.Popen([sys.executable,sys.argv[1]],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
 env={**os.environ,'QINGYIN_ASR_PARENT':str(os.getpid())})
print(p.pid,flush=True)
time.sleep(120)
'''
parent = subprocess.Popen([sys.executable, '-c', code, str(worker)], stdout=subprocess.PIPE, text=True)
child = int(parent.stdout.readline())
def dead(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().split()[2] == 'Z'
    except (FileNotFoundError, ProcessLookupError):
        return True
try:
    time.sleep(.4)
    assert not dead(child), 'worker must be alive before cancellation'
    parent.kill(); parent.wait(timeout=3)
    end = time.monotonic() + 3
    while not dead(child) and time.monotonic() < end:
        time.sleep(.03)
    assert dead(child), 'punctuation child survived canceled parent'
finally:
    if parent.poll() is None:
        parent.kill();parent.wait()
    if not dead(child):
        os.kill(child, 9)
print('PASS: parent cancellation terminates isolated punctuation worker')

if '--model' in sys.argv:
    site = next((root / '.venv/lib').glob('python*/site-packages'))
    env = {**os.environ,
           'LD_LIBRARY_PATH': ':'.join(str(p) for p in site.glob('nvidia/*/lib')),
           'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
    code = '''from pathlib import Path
import sys,json
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'python'))
from gpu_policy import prepare_cuda
prepare_cuda()
from faster_whisper import WhisperModel
from punctuation import restore_isolated
cfg=json.loads((Path.home()/'.config/qingyin/config.json').read_text())
model=WhisperModel(cfg['model'],device='cuda',compute_type='float16',local_files_only=True)
segments,_=model.transcribe(str(root/'tests/jfk.wav'),language='en',vad_filter=True)
assert 'ask not' in ''.join(s.text for s in segments).lower()
assert 'onnxruntime' in sys.modules
source='我想问一下这个软件可以自动补标点吗'
for _ in range(3):
 out=restore_isolated(source)
 assert out.endswith('？') and ''.join(c for c in out if c not in '，。？！；：')==source
assert 'sherpa_onnx' not in sys.modules
print('PASS: real Whisper CUDA + VAD then isolated CPU punctuation (three sessions)')
'''
    subprocess.run([str(root / '.venv/bin/python'), '-c', code, str(root)], env=env, check=True)
