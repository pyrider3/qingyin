import os, sys
from pathlib import Path
import gi
gi.require_version('Gtk','4.0')
from gi.repository import Gtk, GLib
class Probe(Gtk.Application):
 def __init__(self): super().__init__(application_id='dev.qingyin.InputTest')
 def do_activate(self):
  window=Gtk.ApplicationWindow(application=self,title='青音输入测试')
  entry=Gtk.Entry()
  entry.set_visibility('--password' not in sys.argv)
  entry.connect('changed',lambda e: Path('/tmp/qingyin-input-probe.txt').write_text(e.get_text()))
  window.set_child(entry);window.set_default_size(420,100);window.present();entry.grab_focus()
  GLib.timeout_add_seconds(60,lambda: self.quit())
Probe().run([])
