"""Offline GPU smoke test; public test audio only, no microphone or input injection."""
from pathlib import Path
import subprocess, os, json, tempfile, wave, sys
root=Path(__file__).resolve().parents[1]
site=next((root/'.venv/lib').glob('python*/site-packages'))
env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
     'LD_LIBRARY_PATH':':'.join(str(site/'nvidia'/lib/'lib') for lib in ('cublas','cudnn','cuda_nvrtc'))}
config=json.loads((Path.home()/'.config/qingyin/config.json').read_text())
p=subprocess.Popen([root/'.venv/bin/python',root/'python/asr.py',config['model'],'cuda','float16'],
                   env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
try:
 assert json.loads(p.stdout.readline())['ready']
 p.stdin.write(json.dumps({'path':str(root/'tests/jfk.wav'),'language':'auto'})+'\n');p.stdin.flush()
 out=json.loads(p.stdout.readline())
 assert 'ask not' in out.get('text','').lower(),out
 with tempfile.TemporaryDirectory() as tmp:
  f=Path(tmp)/'silence.wav'
  with wave.open(str(f),'wb') as w:
   w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0'*32000)
  p.stdin.write(json.dumps({'path':str(f),'language':'zh'})+'\n');p.stdin.flush()
  assert json.loads(p.stdout.readline())['text']==''
 print('PASS: offline full large-v3 CUDA transcription + local conversion, silence remains empty')
finally:
 p.kill();p.wait(timeout=5)
