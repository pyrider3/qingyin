import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from prompt_budget import prepare
model=Path.home()/'.local/share/qingyin/models/medium/tokenizer.json'
if model.exists():
    from tokenizers import Tokenizer
    tokenizer=Tokenizer.from_file(str(model))
else:
    from types import SimpleNamespace
    tokenizer=SimpleNamespace(encode=lambda s:SimpleNamespace(ids=list(s)),decode=lambda t:''.join(t))
context,hotwords=prepare('上下文人工智能'*500,'雾凇拼音、青音、语音输入、显存、量化、模型常驻'*500,tokenizer)
assert len(tokenizer.encode(' '+context.strip()).ids) <= 96
assert len(tokenizer.encode(' '+hotwords.strip()).ids) <= 80
assert 223+len(tokenizer.encode(' '+hotwords.strip()).ids)+8 < 448
assert prepare('', '', tokenizer)==('','')
print('PASS: long Chinese context and hotwords stay within decoder budget')
