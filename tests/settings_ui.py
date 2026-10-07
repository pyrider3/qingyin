"""Optional GTK preference integration with fake devices/config, no CUDA or microphone."""
import tempfile,json,sys,time
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'python'))
import settings
from gi.repository import GLib,Gio
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);a=p/'large-v3';b=p/'large-v3-turbo'
 for model in (a,b):model.mkdir();(model/'model.bin').touch()
 cfg=p/'config.json';cfg.write_text(json.dumps(dict(model=str(a),device='cuda',gpu_uuid='GPU-big',gpu_min_free_mib=7168,language='zh',microphone='internal',unknown='preserved',compute_type='float16',beam_size=5)))
 cards=[dict(uuid='GPU-small',name='RTX 4060',total=8192,free=7000),dict(uuid='GPU-big',name='RTX 5080',total=16384,free=14000)]
 settings.CONFIG=cfg
 with patch.object(settings.subprocess,'run',return_value=type('Result',(),{'returncode':0})()),patch.object(settings.data,'graphics',return_value=cards),patch.object(settings.data,'models',return_value=[a,b]),patch.object(settings.data,'microphones',return_value=[(None,'default'),('internal','内置麦克风')]),patch.object(settings.subprocess,'check_output',return_value=b'{"running":false}'):
  app=settings.Settings();app.set_flags(Gio.ApplicationFlags.NON_UNIQUE);assert app.register(None);app.activate()
  deadline=time.monotonic()+3
  while not app.cards and time.monotonic()<deadline:
   while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
   time.sleep(.01)
  assert app.cards
  assert app.devices[app.device.get_selected()][1]=='GPU-big'
  app.resident.set_active(True);app.device.set_selected(0);app.model.set_selected(1);app.punctuation.set_active(False);app.save()
  saved=json.loads(cfg.read_text());assert saved['device']=='cpu' and saved['gpu_uuid']=='' and saved['model']==str(b) and not saved['punctuation']
  assert saved['resident_model'] and saved['unknown']=='preserved' and saved['gpu_min_free_mib']==7168 and saved['compute_type']=='float16'
  app.device.set_selected(2);app.compute.set_selected(1);app.punctuation.set_active(True);app.save()
  saved=json.loads(cfg.read_text());assert saved['gpu_uuid']=='GPU-small' and saved['device']=='cuda' and saved['punctuation'] and saved['compute_type']=='int8_float16'
  before=cfg.read_text()
  with patch.object(settings.subprocess,'check_output',return_value=b'{"running":true,"phase":"recording"}'):
   app.device.set_selected(0);app.save();assert cfg.read_text()==before
  app.device.set_selected(2)
  app.apply_devices(('cuda','GPU-big'),[], '设备离线');app.device.set_selected(len(app.devices)-1);app.save();assert cfg.read_text()==before
  assert cfg.stat().st_mode & 0o777 == 0o600
  app.window.destroy();app.quit()
print('PASS: GPU/CPU/model/punctuation persistence, preserved fields, private config, active-session guard and missing GPU rejection')
