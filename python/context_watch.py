"""Bounded observation of only the last Qingyin insertion, no models/history."""
import difflib
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import learning

PREFIX = '\x1fqingyin:'

def request(command):
    root=Path(os.environ['XDG_RUNTIME_DIR'])
    with tempfile.TemporaryDirectory(dir=root,prefix='qingyin-context-') as tmp:
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as client:
            client.bind(tmp+'/client');client.settimeout(.3)
            client.sendto((PREFIX+command).encode(),str(root/'qingyin-fcitx.sock'))
            reply=client.recv(60000).decode()
            return json.loads(reply) if reply.startswith('{') else reply

def auto_pairs(before, after):
    if not before or not after or '\n' in after or len(after)>len(before)+80:
        return []
    changes=[op for op in difflib.SequenceMatcher(None,before,after,autojunk=False).get_opcodes() if op[0]!='equal']
    # New typing, deletion, and sending a message are not confirmation of words.
    if not changes or any(tag!='replace' for tag,*_ in changes):
        return []
    if len(changes)>3:
        return []
    if difflib.SequenceMatcher(None,before,after,autojunk=False).ratio()<.5:
        # Allow a standalone Chinese-name -> English-name correction only.
        if not (before.isalpha() and after.isascii() and after.isalpha() and len(before)<=12 and len(after)<=24):
            return []
    return learning.propose(before,after)

def run():
    deadline=time.monotonic()+60
    previous=None;stable_since=time.monotonic();last_saved=None;active_id=None
    try:
        while time.monotonic()<deadline:
            config=json.loads((Path.home()/'.config/qingyin/config.json').read_text())
            if not config.get('learning',True):break
            data=request('watch')
            if not isinstance(data,dict) or not data.get('watch'):break
            active_id=data['id']
            if data.get('finished'):
                if data.get('confirmed'):
                    pairs=auto_pairs(data['original'],data['edited'])
                    if pairs:learning.record(pairs,data['event'])
                break
            fingerprint=(active_id,data['edited'])
            if fingerprint!=previous:
                if previous and previous[0]!=active_id:deadline=time.monotonic()+60
                previous=fingerprint;stable_since=time.monotonic()
            elif data.get('confirmed') and fingerprint!=last_saved and time.monotonic()-stable_since>=1.5:
                pairs=auto_pairs(data['original'],data['edited'])
                if pairs:learning.record(pairs,data['event'])
                last_saved=fingerprint
            time.sleep(.25)
    finally:
        if active_id:
            try:request('stop-watch:'+active_id)
            except (OSError,ValueError):pass

if __name__=='__main__':
    try:run()
    except Exception:
        # Never log input-box contents, even on malformed client data.
        print('青音自动学习已停止：输入框连接或词库不可用。')
