"""Local correction vocabulary. Persist word pairs/counts only, never transcripts."""
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

LIMIT = 256
THRESHOLD = 3

def store_path():
    return Path.home() / '.local/share/qingyin/private/learning.json'

def load(path=None):
    path = Path(path or store_path())
    if not path.exists():
        return {'version': 1, 'rules': []}
    data = json.loads(path.read_text())
    if data.get('version') != 1 or not isinstance(data.get('rules'), list):
        raise ValueError('个人词库格式错误，请在设置中检查学习记录')
    return data

def mutate(action, path=None):
    path = Path(path or store_path())
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    with path.with_suffix('.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load(path)
        result = action(data)
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp.flush(); os.fsync(tmp.fileno())
        os.replace(tmp.name, path)
        return result

def propose(before, after):
    pairs = []
    if len(after) > 2*len(before)+8 or len(before) > 2*len(after)+8:
        return pairs
    for tag, a, b, c, d in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag != 'replace':
            continue
        ascii_word = lambda ch: ch.isascii() and (ch.isalpha() or ch in '-_')
        if all(ascii_word(ch) for ch in before[a:b]+after[c:d]):
            while a and ascii_word(before[a-1]): a -= 1
            while b < len(before) and ascii_word(before[b]): b += 1
            while c and ascii_word(after[c-1]): c -= 1
            while d < len(after) and ascii_word(after[d]): d += 1
        # Expand single-character edits with an unchanged neighbor so learning
        # never creates a dangerous global one-character replacement.
        if b-a == 1 or d-c == 1:
            if a and c and before[a-1] == after[c-1] and before[a-1].isalnum():
                a -= 1; c -= 1
            elif b < len(before) and d < len(after) and before[b] == after[d] and before[b].isalnum():
                b += 1; d += 1
        source, target = before[a:b], after[c:d]
        if not (2 <= len(source) <= 24 and 2 <= len(target) <= 24):
            continue
        if not all(ch.isalpha() or ch in '-_' for ch in source+target):
            continue
        if source == target:
            continue
        pair = (source, target)
        if pair not in pairs:
            pairs.append(pair)
    return pairs

def record(pairs, event, path=None):
    def action(data):
        added = 0
        for source, target in pairs:
            key = hashlib.sha256((source.casefold()+'\0'+target).encode()).hexdigest()[:24]
            row = next((r for r in data['rules'] if r['id'] == key), None)
            if row is None:
                if len(data['rules']) >= LIMIT:
                    raise ValueError('个人词库已达 256 条，请先删除不需要的记录')
                row = {'id': key, 'source': source, 'target': target, 'count': 0, 'events': []}
                data['rules'].append(row)
            if event not in row['events']:
                row['count'] += 1
                row['events'] = (row['events']+[event])[-32:]
                added += 1
        return added
    return mutate(action, path)

def active_rules(data):
    groups = {}
    for row in data['rules']:
        groups.setdefault(row['source'].casefold(), []).append(row)
    return [rows[0] for rows in groups.values() if len(rows)==1 and rows[0]['count']>=THRESHOLD]

def apply(text, data):
    rules = sorted(active_rules(data), key=lambda r: len(r['source']), reverse=True)
    if not rules:
        return text
    parts = []
    lookup = {}
    for index, row in enumerate(rules):
        key = f'r{index}'
        word = re.escape(row['source'])
        if row['source'].isascii():
            word = r'(?<![A-Za-z0-9_])(?i:'+word+r')(?![A-Za-z0-9_])'
        parts.append(f'(?P<{key}>{word})')
        lookup[key] = row['target']
    return re.sub('|'.join(parts), lambda m: lookup[m.lastgroup], text)

def hints(data):
    targets = list(dict.fromkeys(r['target'] for r in sorted(data['rules'], key=lambda r:r['count'], reverse=True)))
    return ', '.join(targets[:64])[:512]

def delete(rule_id=None, path=None):
    def action(data):
        data['rules'] = [r for r in data['rules'] if rule_id is not None and r['id']!=rule_id]
    mutate(action, path)
