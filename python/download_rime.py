"""Explicit online installation; inference itself never accesses the network."""
import json
import os
import sqlite3
import tempfile
import urllib.request
from rime_dictionary import root


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Qingyin-dictionary'}), timeout=120) as response:
        return response.read()


def main():
    target = root(); target.mkdir(parents=True, exist_ok=True)
    revision = json.loads(fetch('https://api.github.com/repos/iDvel/rime-ice/commits/main'))['sha']
    base = f'https://raw.githubusercontent.com/iDvel/rime-ice/{revision}/'
    files = ['8105.dict.yaml','41448.dict.yaml','base.dict.yaml','ext.dict.yaml','others.dict.yaml','tencent.dict.yaml']
    with tempfile.TemporaryDirectory(dir=target) as temporary:
        temp = __import__('pathlib').Path(temporary)
        db = sqlite3.connect(temp/'words.sqlite3')
        db.execute('CREATE TABLE words(word TEXT PRIMARY KEY, weight INTEGER NOT NULL) WITHOUT ROWID')
        for name in files:
            print('正在下载 '+name, flush=True)
            content = fetch(base+'cn_dicts/'+name)
            (temp/name).write_bytes(content)
            started = False
            batch = []
            for line in content.decode('utf-8-sig').splitlines():
                if line.strip() == '...': started = True; continue
                if not started or not line or line.startswith('#'): continue
                parts = line.split('\t'); word = parts[0].strip()
                if not 2 <= len(word) <= 12 or not all('\u4e00' <= c <= '\u9fff' for c in word): continue
                try: weight = int(parts[2]) if len(parts)>2 else 0
                except ValueError: weight = 0
                batch.append((word, weight))
            db.executemany('INSERT INTO words VALUES(?,?) ON CONFLICT(word) DO UPDATE SET weight=max(weight,excluded.weight)', batch)
            db.commit()
        count = db.execute('SELECT count(*) FROM words').fetchone()[0]
        db.close()
        (temp/'LICENSE').write_bytes(fetch(base+'LICENSE'))
        (temp/'source.json').write_text(json.dumps({'source':'https://github.com/iDvel/rime-ice','revision':revision,'files':files,'words':count},ensure_ascii=False,indent=2))
        for file in temp.iterdir():
            if file.name != 'words.sqlite3': os.replace(file, target/file.name)
        os.replace(temp/'words.sqlite3', target/'words.sqlite3')
    print(f'已导入 {count:,} 个词条；源文件、许可和版本已保留：{target}')

if __name__ == '__main__': main()
