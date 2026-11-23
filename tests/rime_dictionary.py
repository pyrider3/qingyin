"""Dictionary hints are local, contextual, bounded and optional."""
import os
import sys
import sqlite3
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
import rime_dictionary as r
with tempfile.TemporaryDirectory() as temporary:
    os.environ['XDG_DATA_HOME']=temporary
    assert r.hints('没有词库') == ''
    r.root().mkdir(parents=True)
    with sqlite3.connect(r.root()/'words.sqlite3') as db:
        db.execute('CREATE TABLE words(word TEXT PRIMARY KEY, weight INTEGER)')
        db.executemany('INSERT INTO words VALUES (?,?)',[('人工智能',10),('智能',20),('显存',30),('不相关',999)])
    assert r.hints('人工智能占用显存') == '人工智能, 显存'
    assert r.hints('') == ''
    assert r.hints('人工智能占用显存',limit=1) == '人工智能'
    assert len(r.hints('人工智能占用显存',budget=8)) <= 8
print('Rime dictionary tests passed')
