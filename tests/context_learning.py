"""Only stable replacements in Qingyin's inserted span may become candidates."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from context_watch import auto_pairs
assert auto_pairs('打开青英','打开青音')==[('青英','青音')]
assert auto_pairs('诺克塔利亚','Noctalia')==[('诺克塔利亚','Noctalia')]
for before,after in [('打开青英','打开青英然后继续输入'),('打开青英',''),('打开青英','打开'),('你好','你好。'),('我今天想写代码','明天我们出去散步吧'),('青英','青音\n新段落')]:
 assert not auto_pairs(before,after),(before,after)
print('PASS: correction extraction; append, deletion, message clearing, punctuation and rewrite ignored')

# Sending immediately after an edit may finalize the last replacement, but the
# subsequent empty message must never be learned.
import json, tempfile, os
import context_watch
from unittest.mock import patch
with tempfile.TemporaryDirectory() as tmp:
 home=Path(tmp);(home/'.config/qingyin').mkdir(parents=True)
 (home/'.config/qingyin/config.json').write_text('{"learning":true}')
 snapshot={'watch':True,'confirmed':True,'finished':True,'id':'test-id','event':'test-event','original':'打开青英','edited':'打开青音'}
 commands=[]
 def fake_request(command):
  commands.append(command)
  return snapshot if command=='watch' else 'ok'
 with patch.dict(os.environ,{'HOME':tmp}),patch.object(context_watch,'request',fake_request):
  context_watch.run()
  import learning
  assert learning.load()['rules'][0]['target']=='青音'
 assert commands==['watch','stop-watch:test-id']
print('PASS: immediate-send finalization saves correction only, then ends tracking')
