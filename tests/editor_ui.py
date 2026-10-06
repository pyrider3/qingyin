"""Optional GTK regression on a live Wayland session; synthetic test data only."""
import tempfile,os,json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
os.environ['WAYLAND_DISPLAY']=str(Path(os.environ['XDG_RUNTIME_DIR'])/os.environ['WAYLAND_DISPLAY'])
with tempfile.TemporaryDirectory() as tmp:
 home=Path(tmp);os.environ['HOME']=tmp;os.environ['XDG_RUNTIME_DIR']=tmp+'/run'
 rt=home/'run/qingyin';rt.mkdir(parents=True)
 (home/'.config/qingyin').mkdir(parents=True);(home/'.config/qingyin/config.json').write_text('{"learning":true}')
 (rt/'state.json').write_text(json.dumps({'phase':'result','started':123.0,'text':'打开青英','message':'测试'}))
 cli=home/'.local/bin/qingyin';cli.parent.mkdir(parents=True);cli.write_text('#!/bin/sh\nexit 0\n');cli.chmod(0o755)
 sys.path.insert(0,str(root/'python'))
 import editor,learning
 from gi.repository import GLib
 app=editor.Editor();assert app.register(None);app.activate()
 app.text.get_buffer().set_text('打开青音')
 assert [(s,t) for _,s,t in app.selected]==[('青英','青音')]
 app.save();app.save()
 data=learning.load();assert data['rules'][0]['count']==1
 assert json.loads((rt/'state.json').read_text())['text']=='打开青音'
 # A new recording must prevent stale editor results from overwriting it.
 (rt/'state.json').write_text('{"phase":"result","started":456,"text":"新结果"}')
 app.save();assert json.loads((rt/'state.json').read_text())['text']=='新结果'
 app.window.destroy();app.quit()
 sys.argv.append('--vocabulary');manage=editor.Editor();assert manage.register(None);manage.activate()
 assert manage.rows.get_first_child()
 manage.remove(data['rules'][0]['id']);assert not learning.load()['rules']
 manage.window.destroy();manage.quit()
 print('PASS: GTK correction preview/save, repeated-save dedup, stale-result rejection and vocabulary deletion')
