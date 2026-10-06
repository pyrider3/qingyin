"""Local vocabulary regression checks; never touch the user's learning data."""
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
import learning
assert learning.propose('neovim','Neovim')==[('neovim','Neovim')]
assert learning.propose('打开青英','打开青音')==[('青英','青音')]
assert learning.propose('打开诺克塔利亚','打开Noctalia')==[('诺克塔利亚','Noctalia')]
assert not learning.propose('你好','你好，')
assert not learning.propose('打开文件','删除整个目录这是很长的一段改写内容完全不是原文')
with tempfile.TemporaryDirectory() as tmp:
 path=Path(tmp)/'private/learning.json'
 learning.record([('青英','青音')],'recording1',path)
 data=learning.load(path)
 assert learning.apply('打开青英',data)=='打开青英'
 assert '青音' in learning.hints(data)
 learning.record([('青英','青音')],'recording1',path)
 assert learning.load(path)['rules'][0]['count']==1
 for event in ('recording2','recording3'):learning.record([('青英','青音')],event,path)
 assert learning.apply('打开青英',learning.load(path))=='打开青音'
 learning.record([('青英','清音')],'recording4',path)
 assert learning.apply('打开青英',learning.load(path))=='打开青英'
 conflict=next(r for r in learning.load(path)['rules'] if r['target']=='清音')
 learning.delete(conflict['id'],path)
 assert learning.apply('打开青英',learning.load(path))=='打开青音'
 for event in ('1','2','3'):
  learning.record([('neovim','Neovim'),('Neovim','Editor')],event,path)
 # English boundaries and conflicting correction targets must be conservative.
 assert learning.apply('myneovim neovim',learning.load(path))=='myneovim neovim'
 learning.delete(None,path)
 for event in ('a','b','c'):learning.record([('nvim','Neovim'),('Neovim','Editor')],event,path)
 assert learning.apply('nvim',learning.load(path))=='Neovim' # No replacement cascade.
 assert learning.apply('mynvim NVIM',learning.load(path))=='mynvim Neovim'
 assert path.stat().st_mode & 0o777 == 0o600
 assert path.parent.stat().st_mode & 0o777 == 0o700
 assert set(learning.load(path))=={'version','rules'}
 learning.delete(None,path);assert not learning.load(path)['rules']
print('PASS: explicit short corrections, three independent confirmations, dedup, conflicts, English boundaries, no cascades, private storage and deletion')
