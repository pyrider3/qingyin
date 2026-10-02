"""Test on-demand lifecycle with mock audio/ASR. No real mic or application input."""
import tempfile, subprocess, os, pathlib, json, time, signal
binary=pathlib.Path(__file__).resolve().parents[1]/'target/release/qingyin'
with tempfile.TemporaryDirectory() as tmp:
 root=pathlib.Path(tmp); app=root/'app'; config=root/'.config/qingyin'; rt=root/'runtime'
 for p in [app/'.venv/bin',app/'python',config,rt,root/'bin']:p.mkdir(parents=True,exist_ok=True)
 (app/'.venv/bin/python').symlink_to('/usr/bin/python3')
 (root/'bin/notify-send').symlink_to('/usr/bin/true')
 (app/'python/asr.py').write_text('''import json,sys,time,os,pathlib
root=pathlib.Path(os.environ['HOME'])
(root/'asr.pid').write_text(str(os.getpid()))
time.sleep(1)
if (root/'fail-asr').exists():sys.exit(1)
print(json.dumps({'ready':True}),flush=True)
for line in sys.stdin:
 (root/'inference').write_text('started')
 time.sleep(8 if (root/'slow').exists() else .4)
 print(json.dumps({'text':'你好，青音。'}),flush=True)
''')
 recorder=root/'bin/pw-record'
 recorder.write_text('''#!/usr/bin/python3
import sys,wave,time,signal,os,pathlib
root=pathlib.Path(os.environ['HOME'])
if (root/'fail-record').exists():sys.exit(1)
(root/'recorder.pid').write_text(str(os.getpid()))
w=wave.open(sys.argv[-1],'wb');w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\\0'*32000);w.close()
signal.signal(signal.SIGINT,lambda *_:sys.exit(0))
time.sleep(120)
''');recorder.chmod(0o755)
 (root/'bin/niri').write_text('#!/bin/sh\nprintf \'[{"id":1,"is_focused":true}]\\n\'\n');(root/'bin/niri').chmod(0o755)
 (root/'bin/wl-copy').write_text('#!/bin/sh\ncat > "$HOME/copied"\n');(root/'bin/wl-copy').chmod(0o755)
 # Emulate unit activation to test the real first/second CLI toggle path, including races.
 (root/'bin/systemctl').write_text('''#!/usr/bin/python3
import os,sys,subprocess,pathlib
r=pathlib.Path(os.environ['HOME'])
if 'start' in sys.argv:
 p=subprocess.Popen([os.environ['TEST_BINARY'],'session'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
 (r/'service.pid').write_text(str(p.pid))
 with (r/'activations').open('a') as f:f.write('start\\n')
 sys.exit(0)
sys.exit(1)
''');(root/'bin/systemctl').chmod(0o755)
 (config/'config.json').write_text(json.dumps({'model':'fake','device':'cpu','language':'zh','auto_input':False,'microphone':None,'max_seconds':3}))
 env={**os.environ,'HOME':str(root),'QINGYIN_HOME':str(app),'XDG_RUNTIME_DIR':str(rt),'PATH':str(root/'bin')+':'+os.environ['PATH'],'TEST_BINARY':str(binary)}
 def command(c):return subprocess.check_output([binary,c],env=env,stderr=subprocess.PIPE,timeout=8).decode().strip()
 def state():return json.loads(command('status'))
 def until(check, seconds=5):
  end=time.monotonic()+seconds
  while time.monotonic()<end:
   if check():return
   time.sleep(.03)
  raise AssertionError(('timeout',state()))
 def dead(pid):
  try:return pathlib.Path(f'/proc/{pid}/stat').read_text().split()[2]=='Z'
  except FileNotFoundError:return True
 def clean():
  assert not list((rt/'qingyin').glob('*.wav')),'audio remains'
  assert not (rt/'qingyin/control.sock').exists(),'controller socket remains'
  for name in ('asr.pid','recorder.pid'):
   if (root/name).exists():assert dead(int((root/name).read_text())),name+' remains alive'
 def session():
  command('dismiss')
  (root/'inference').unlink(missing_ok=True)
  p=subprocess.Popen([binary,'session'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  until(lambda:state()['phase']=='recording' and (root/'asr.pid').exists())
  return p
 # Cold startup records before ready; stopping during loading queues transcription.
 p=session();assert not (root/'inference').exists()
 command('toggle');assert state()['phase']=='transcribing';assert '稍候' in command('toggle')
 p.wait(timeout=5);assert state()['text']=='你好，青音。';assert not state()['running'];clean()
 command('copy');assert (root/'copied').read_text()=='你好，青音。'
 # Cancel during model loading releases child immediately and clears audio.
 p=session();command('cancel');p.wait(timeout=2);clean();assert state()['phase']=='idle'
 # Cancel during active inference kills the worker without waiting 8 seconds.
 (root/'slow').touch();p=session();command('toggle');until(lambda:(root/'inference').exists())
 start=time.monotonic();command('cancel');p.wait(timeout=2);assert time.monotonic()-start<2;clean()
 time.sleep(.5);assert state()['phase']=='idle';(root/'slow').unlink()
 # Maximum duration stops and releases everything automatically.
 p=session();p.wait(timeout=6);assert state()['phase']=='result';clean()
 # Model and recorder failures also release resources and preserve a useful error.
 (root/'fail-asr').touch();p=session();p.wait(timeout=4);assert state()['phase']=='error';clean();(root/'fail-asr').unlink()
 (root/'fail-record').touch();p=subprocess.Popen([binary,'session'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 p.wait(timeout=3);assert state()['phase']=='error';clean();(root/'fail-record').unlink()
 # Launch while an old error exists; rapid repeated presses must start exactly one unit.
 first=subprocess.Popen([binary,'toggle'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 second=subprocess.Popen([binary,'toggle'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 assert first.communicate(timeout=8)[0];assert first.returncode==0
 assert second.communicate(timeout=8)[0];assert second.returncode==0
 until(lambda:state()['phase']=='result' and not state()['running'])
 until(lambda:dead(int((root/'service.pid').read_text())))
 assert (root/'activations').read_text().splitlines()==['start'];clean()
 # Cancel/copy/status while inactive must not activate the model.
 command('cancel');assert state()['phase']=='idle';assert not state()['running']
 assert (root/'activations').read_text().splitlines()==['start']
 print('PASS: cold loading stop, cancellation during loading/inference, duration limit, errors, rapid presses, child/audio cleanup, retained copy, inactive commands')
