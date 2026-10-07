"""Model download staging/validation without internet, CUDA or real weights."""
import os,sys,tempfile,types,importlib.util
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('download_model',root/'download_model.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class API:
 def model_info(self,_):return types.SimpleNamespace(sha='fixed-revision')
def snapshot(**kw):
 assert kw['revision']=='fixed-revision'
 folder=Path(kw['local_dir']);folder.mkdir(parents=True)
 for name in ('model.bin','config.json','tokenizer.json'):(folder/name).write_text('test')
hub=types.ModuleType('huggingface_hub');hub.HfApi=API;hub.snapshot_download=snapshot
with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'HOME':tmp,'HF_HUB_OFFLINE':'1'}),patch.dict(sys.modules,{'huggingface_hub':hub}):
 module.download('small');target=Path(tmp)/'.local/share/qingyin/models/small'
 assert (target/'model.bin').is_file() and os.environ.get('HF_HUB_OFFLINE') is None
 with patch.object(hub,'snapshot_download',side_effect=AssertionError('duplicate download')):module.download('small')
 def incomplete(**kw):
  folder=Path(kw['local_dir']);folder.mkdir(parents=True);(folder/'model.bin').touch()
 with patch.object(hub,'snapshot_download',side_effect=incomplete):
  try:module.download('base');raise AssertionError('incomplete model accepted')
  except RuntimeError:pass
 assert not (target.parent/'base').exists()
 assert not list((target.parent/'.downloads').iterdir())
print('PASS: pinned revision, atomic install, existing model preserved and incomplete downloads excluded')
