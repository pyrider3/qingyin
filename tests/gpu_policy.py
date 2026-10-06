"""GPU safety policy tests; no real CUDA calls or models."""
import os,sys,subprocess,types
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from gpu_policy import prepare_cuda
output='GPU-small, RTX 4060, 8188, 7800\nGPU-big, RTX 5080, 16303, 15000\n'
def run(cfg, text=output, env=None):
 with patch.dict(os.environ,env or {},clear=True),patch('subprocess.run',return_value=types.SimpleNamespace(stdout=text)):
  gpu=prepare_cuda(cfg);assert os.environ['CUDA_VISIBLE_DEVICES']==gpu['uuid'];return gpu
assert run({})['uuid']=='GPU-big'
assert run({'gpu_uuid':'GPU-big'})['uuid']=='GPU-big'
assert run({},env={'CUDA_VISIBLE_DEVICES':'0'})['uuid']=='GPU-small'
for cfg,text,env in [({'gpu_uuid':'GPU-missing'},output,None),({'gpu_uuid':'GPU-big'},output.replace('15000','5000'),None),({'gpu_uuid':'GPU-big'},output,{'CUDA_VISIBLE_DEVICES':'0'}),({},output,{'CUDA_VISIBLE_DEVICES':''})]:
 try:run(cfg,text,env);raise AssertionError('unsafe selection accepted')
 except RuntimeError:pass
with patch('subprocess.run',side_effect=subprocess.TimeoutExpired('nvidia-smi',3)):
 try:prepare_cuda({});raise AssertionError('timeout accepted')
 except RuntimeError:pass
print('PASS: UUID pinning, sufficient memory, unavailable/low-memory fail closed, visibility restrictions and query timeout')
# The worker must return a Chinese error before importing faster-whisper at all.
import io,runpy
root=Path(__file__).resolve().parents[1]
original_import=__import__
def guarded_import(name,*args,**kwargs):
 if name=='faster_whisper':raise AssertionError('CUDA inference imported despite blocked preflight')
 return original_import(name,*args,**kwargs)
out=io.StringIO()
with patch.dict(sys.modules,{'numpy':types.ModuleType('numpy')}),patch('gpu_policy.prepare_cuda',side_effect=RuntimeError('显存不足，已停止加载')),patch('builtins.__import__',side_effect=guarded_import),patch.object(sys,'argv',['asr.py','fake','cuda']),patch.object(sys,'stdout',out),patch.object(sys,'stderr',io.StringIO()):
 try:runpy.run_path(str(root/'python/asr.py'))
 except SystemExit as exc:assert exc.code==1
assert '显存不足' in out.getvalue()
print('PASS: blocked preflight never imports CUDA inference; worker returns structured Chinese error')
