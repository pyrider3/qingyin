"""Offline, bounded Rime Ice context hints. Never replaces recognized text."""
import os
import re
import sqlite3
from pathlib import Path


def root():
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'qingyin/dictionaries/rime-ice'


def hints(context, limit=16, budget=120):
    path = root()/'words.sqlite3'
    if not context or not path.is_file():
        return ''
    # Exact phrases from nearby text; no broad single-character associations.
    phrases = set()
    for chunk in re.findall(r'[\u4e00-\u9fff]{2,}', context[-512:]):
        for size in range(2, min(12, len(chunk))+1):
            phrases.update(chunk[i:i+size] for i in range(len(chunk)-size+1))
    if not phrases:
        return ''
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.2) as db:
        rows = []
        terms = sorted(phrases)
        for offset in range(0, len(terms), 400):
            batch = terms[offset:offset+400]
            rows.extend(db.execute('SELECT word,weight FROM words WHERE word IN ('+','.join('?' for _ in batch)+')', batch))
    selected = []
    used = 0
    for word, weight in sorted(rows, key=lambda row: (-len(row[0]), -row[1], row[0])):
        if any(word in other for other in selected):
            continue
        if used+len(word)+2 > budget:
            continue
        selected.append(word); used += len(word)+2
        if len(selected) >= limit:
            break
    return ', '.join(selected)
