"""Resident reuse/reload/cancellation test with fake ASR, no models or CUDA."""
import os,sys,socket,tempfile,subprocess,time,json,signal
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'python'))
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);app=p/'app/python';app.mkdir(parents=True);rt=p/'run';rt.mkdir()
 (app/'asr.py').write_text('''import json,os,sys,time
print('{"ready":true}',flush=True)
for line in sys.stdin:
 job=json.loads(line)
 if job.get('slow'):time.sleep(30)
 print(json.dumps({'text':'ok','pid':os.getpid()}),flush=True)
''')
 env={**os.environ,'XDG_RUNTIME_DIR':str(rt)}
 with patch.dict(os.environ,env):
  from resident import line
 code='import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import resident;resident.ROOT=Path(sys.argv[2]);resident.serve()'
 server=subprocess.Popen([sys.executable,'-c',code,str(root/'python'),str(p/'app')],env=env,start_new_session=True)
 path=rt/'qingyin/model.sock'
 for _ in range(100):
  if path.exists():break
  time.sleep(.02)
 def connect(model='one'):
  c=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);c.settimeout(5);c.connect(str(path));c.sendall(json.dumps(dict(model=model,device='cpu',compute='int8')).encode()+b'\n');assert json.loads(line(c))['ready'];return c
 def job(model='one'):
  with connect(model) as c:
   c.sendall(b'{}\n');return json.loads(line(c))['pid']
 try:
  first=job();assert job()==first
  second=job('two');assert second!=first
  c=connect('two');c.sendall(b'{"slow":true}\n');time.sleep(.1);c.close()
  time.sleep(.3);assert job('two')!=second
  print('PASS: two sessions reuse one model; model change reloads; canceled inference releases worker')
 finally:os.killpg(server.pid,signal.SIGTERM);server.wait(timeout=3)
