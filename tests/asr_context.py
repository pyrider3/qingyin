"""Check context/learned vocabulary plumbing without real audio/models/network."""
import io,json,os,runpy,sys,tempfile,types
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'python'))
import learning
seen=[]
class FakeModel:
 def __init__(self,*_,**__):pass
 def transcribe(self,_,**kwargs):
  seen.append(kwargs)
  return [types.SimpleNamespace(text='打开青英')],None
whisper=types.ModuleType('faster_whisper');whisper.WhisperModel=FakeModel
numpy=types.ModuleType('numpy');numpy.float32='float32';numpy.frombuffer=lambda *_args,**_kwargs:[]
with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'HOME':tmp}):
 for event in ('one','two','three'):learning.record([('青英','青音')],event)
 requests=[{'path':'fake','language':'zh','learning':True,'context':'上下文 Noctalia','hotwords':'niri','punctuation':False},
           {'path':'fake','language':'zh','learning':False,'context':'上下文 Noctalia','hotwords':'niri','punctuation':False}]
 output=io.StringIO()
 with patch.dict(sys.modules,{'faster_whisper':whisper,'numpy':numpy}),patch('subprocess.run',return_value=types.SimpleNamespace(stdout=b'')),patch.object(sys,'stdin',io.StringIO('\n'.join(json.dumps(r) for r in requests))),patch.object(sys,'stdout',output),patch.object(sys,'argv',['asr.py','fake','cpu']):
  runpy.run_path(str(root/'python/asr.py'))
 results=[json.loads(line) for line in output.getvalue().splitlines()]
 assert results[1]['text']=='打开青音'
 assert results[2]['text']=='打开青英'
 assert seen[0]['initial_prompt']=='上下文 Noctalia' and '青音' in seen[0]['hotwords']
 assert seen[1]['initial_prompt'] is None and seen[1]['hotwords']=='niri'
print('PASS: context prompt/learned hotwords/corrections enabled; disabling learning excludes all three')
