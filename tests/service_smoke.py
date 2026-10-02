"""Test installed unit with local public audio, without microphone or text injection.
Only a temporary per-unit PATH override is used; config is preserved.
"""
from pathlib import Path
import tempfile, os, subprocess, json, time
root=Path(__file__).resolve().parents[1]
cli=Path.home()/'.local/bin/qingyin'
unit_drop=Path(os.environ['XDG_RUNTIME_DIR'])/'systemd/user/qingyin.service.d/qingyin-smoke.conf'
assert subprocess.run(['systemctl','--user','is-active','--quiet','qingyin']).returncode != 0
assert not unit_drop.exists()
with tempfile.TemporaryDirectory() as tmp:
 fake=Path(tmp)
 record=fake/'pw-record'
 record.write_text(f'''#!/usr/bin/python3
import shutil,sys,signal,time
shutil.copyfile({str(root/'tests/jfk.wav')!r},sys.argv[-1])
signal.signal(signal.SIGINT,lambda *_:sys.exit(0))
time.sleep(300)
''');record.chmod(0o755)
 (fake/'niri').write_text('#!/bin/sh\nprintf "[]\\n"\n');(fake/'niri').chmod(0o755)
 (fake/'notify-send').symlink_to('/usr/bin/true')
 unit_drop.parent.mkdir(parents=True,exist_ok=True)
 unit_drop.write_text(f'[Service]\nEnvironment="PATH={fake}:/usr/local/bin:/usr/bin"\n')
 try:
  subprocess.run(['systemctl','--user','daemon-reload'],check=True)
  subprocess.run([cli,'toggle'],check=True,stdout=subprocess.DEVNULL)
  state=json.loads(subprocess.check_output([cli,'status']))
  assert state['phase']=='recording'
  subprocess.run([cli,'toggle'],check=True,stdout=subprocess.DEVNULL)
  end=time.monotonic()+35
  while time.monotonic()<end:
   active=subprocess.run(['systemctl','--user','is-active','--quiet','qingyin']).returncode==0
   if not active:break
   time.sleep(.15)
  assert not active,'unit did not exit'
  state=json.loads(subprocess.check_output([cli,'status']))
  assert state['phase']=='result' and state['text'] and not state['running'],state
  assert not (Path(os.environ['XDG_RUNTIME_DIR'])/'qingyin/recording.wav').exists()
  gpu=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid,process_name,used_memory','--format=csv,noheader'],text=True)
  assert 'qingyin/.venv/bin/python' not in gpu,gpu
  print('PASS: installed on-demand unit, stop while cold loading, full CUDA recognition, retained result after ExecStopPost, audio and GPU process released')
 finally:
  subprocess.run([cli,'cancel'],stdout=subprocess.DEVNULL)
  subprocess.run(['systemctl','--user','stop','qingyin'],check=True)
  unit_drop.unlink(missing_ok=True)
  subprocess.run(['systemctl','--user','daemon-reload'],check=True)
