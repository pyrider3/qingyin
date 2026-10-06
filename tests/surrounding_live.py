"""Optional live fcitx/GTK context test; temporary vocabulary, synthetic input only."""
import os,sys,json,tempfile,subprocess,time
from pathlib import Path
import gi
gi.require_version('Gtk','4.0')
from gi.repository import Gtk,GLib
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'python'))
from context_watch import request
import learning
home=tempfile.TemporaryDirectory();fake=Path(home.name);(fake/'.config/qingyin').mkdir(parents=True);(fake/'.config/qingyin/config.json').write_text('{"learning":true}')
class Probe(Gtk.Application):
 def __init__(self):super().__init__(application_id='dev.qingyin.ContextProbe');self.proc=None;self.errors=[]
 def do_activate(self):
  self.window=Gtk.ApplicationWindow(application=self,title='青音自动学习测试（仅测试文字）');self.entry=Gtk.Entry(text='上下文测试：');self.window.set_child(self.entry);self.window.set_default_size(500,100);self.window.present();self.entry.grab_focus()
  GLib.timeout_add(500,self.focus)
 def focus(self):
  windows=json.loads(subprocess.check_output(['niri','msg','--json','windows']))
  w=next(w for w in windows if w.get('app_id')=='dev.qingyin.ContextProbe')
  subprocess.run(['niri','msg','action','focus-window','--id',str(w['id'])],check=True,stdout=subprocess.DEVNULL)
  self.entry.grab_focus();self.entry.set_position(-1);GLib.timeout_add(800,self.start);return False
 def start(self):
  try:
   assert request('learn:test-context-1\n打开青英')=='ok'
   GLib.timeout_add(700,self.correct)
  except Exception as e:self.fail(e)
  return False
 def correct(self):
  try:
   context=request('context');assert context['supported'] and '上下文测试' in context['text']
   r=request('watch');assert r['watch'] and r['confirmed'],r
   assert r['original']=='打开青英' and r['edited']=='打开青英',r
   self.watch_id=r['id'];before=self.entry.get_text()
   assert request('stop-watch:stale-id')=='ok'
   assert request('unknown-command')=='invalid-command'
   assert request('learn:malformed')=='invalid-command'
   assert request('watch')['id']==self.watch_id
   assert self.entry.get_text()==before
   env={**os.environ,'HOME':home.name}
   self.proc=subprocess.Popen(['/usr/bin/python3',str(root/'python/context_watch.py')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
   self.entry.set_text('上下文测试：打开青音');self.entry.set_position(-1)
   controllers=self.entry.get_delegate().observe_controllers()
   for i in range(controllers.get_n_items()):
    controller=controllers.get_item(i)
    if isinstance(controller,Gtk.EventControllerKey) and controller.get_im_context():
     context=controller.get_im_context();text=self.entry.get_text();size=len(text.encode())
     context.set_surrounding_with_selection(text,size,size,size)
   GLib.timeout_add(2600,self.verify)
  except Exception as e:self.fail(e)
  return False
 def verify(self):
  try:
   data=learning.load(fake/'.local/share/qingyin/private/learning.json')
   assert data['rules'] and data['rules'][0]['source']=='青英' and data['rules'][0]['target']=='青音',data
   assert '上下文测试' not in json.dumps(data,ensure_ascii=False)
   self.entry.set_text('')
   controllers=self.entry.get_delegate().observe_controllers()
   for i in range(controllers.get_n_items()):
    controller=controllers.get_item(i)
    if isinstance(controller,Gtk.EventControllerKey) and controller.get_im_context():
     controller.get_im_context().set_surrounding_with_selection('',0,0,0)
   GLib.timeout_add(600,self.password)
   print('PASS: live GTK surrounding context, insertion tracking, implicit correction learning; no surrounding paragraph saved',flush=True)
  except Exception as e:self.fail(e)
  return False
 def password(self):
  try:
   assert request('watch')['watch']==False
   assert request('stop-watch:'+self.watch_id)=='ok'
   assert request('stop-watch:'+self.watch_id)=='ok'
   GLib.timeout_add(300,self.check_stale_stop)
  except Exception as e:self.fail(e)
  return False
 def check_stale_stop(self):
  try:
   assert self.entry.get_text()==''
   print('PASS: stale/repeated stop and unknown protocol messages never enter the text box; stale stop preserves newer watch',flush=True)
   self.entry.set_visibility(False);self.entry.set_input_purpose(Gtk.InputPurpose.PASSWORD);self.entry.set_text('测试密码')
   controllers=self.entry.get_delegate().observe_controllers()
   for i in range(controllers.get_n_items()):
    controller=controllers.get_item(i)
    if isinstance(controller,Gtk.EventControllerKey) and controller.get_im_context():
     controller.get_im_context().set_property('input-purpose',Gtk.InputPurpose.PASSWORD)
   GLib.timeout_add(500,self.verify_password)
  except Exception as e:self.fail(e)
  return False
 def verify_password(self):
  try:
   r=request('context');assert not r.get('supported'),r
   assert request('watch')['watch']==False
   print('PASS: password contexts excluded and clearing ends observation',flush=True)
  except Exception as e:self.errors.append(str(e))
  self.quit();return False
 def fail(self,e):
  import traceback
  traceback.print_exc();self.errors.append(str(e));self.quit()
a=Probe();a.run([])
if a.proc:
 try:a.proc.wait(timeout=2)
 except subprocess.TimeoutExpired:a.proc.kill();a.proc.wait()
home.cleanup()
assert not a.errors,a.errors
