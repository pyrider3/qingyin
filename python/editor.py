"""Explicit correction editor and locally learned vocabulary management."""
import json
import os
from pathlib import Path
import subprocess
import sys
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
import learning

cli = str(Path.home()/'.local/bin/qingyin')
state_path = Path(os.environ['XDG_RUNTIME_DIR'])/'qingyin/state.json'
config_path = Path.home()/'.config/qingyin/config.json'

class Editor(Gtk.Application):
    def __init__(self):
        self.manage = '--vocabulary' in sys.argv
        super().__init__(application_id='dev.qingyin.Vocabulary' if self.manage else 'dev.qingyin.Editor')
    def do_activate(self):
        if self.get_active_window():
            self.get_active_window().present(); return
        self.window = Gtk.ApplicationWindow(application=self, title='青音 · 个人词库' if self.manage else '青音 · 纠正结果')
        self.window.set_default_size(620, 440)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top','bottom','start','end'):getattr(box,'set_margin_'+side)(20)
        box.append(Gtk.Label(label='只保存词语纠正和次数，不保存整段文字；三次不同录音确认后自动应用。', wrap=True, xalign=0))
        self.notice = Gtk.Label(wrap=True, xalign=0)
        if self.manage:
            scroll = Gtk.ScrolledWindow(vexpand=True)
            self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            scroll.set_child(self.rows);box.append(scroll)
            self.refresh()
            clear=Gtk.Button(label='清空全部学习记录');clear.connect('clicked',self.confirm_clear);box.append(clear)
        else:
            try:self.snapshot=json.loads(state_path.read_text())
            except (OSError,ValueError):self.snapshot={}
            self.original=self.snapshot.get('text','')
            scroll=Gtk.ScrolledWindow(vexpand=True)
            self.text=Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
            self.text.get_buffer().set_text(self.original)
            scroll.set_child(self.text);box.append(scroll)
            self.choices=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6);box.append(self.choices)
            self.text.get_buffer().connect('changed',self.preview)
            self.preview()
            save=Gtk.Button(label='保存纠正并复制');save.connect('clicked',self.save);save.set_sensitive(bool(self.original));box.append(save)
            if not self.original:self.notice.set_text('没有可纠正的结果，请先按 Win+A 完成一次录音。')
        box.append(self.notice);self.window.set_child(box);self.window.present()
    def edited(self):
        buf=self.text.get_buffer();return buf.get_text(buf.get_start_iter(),buf.get_end_iter(),True)
    def preview(self,*_):
        child=self.choices.get_first_child()
        while child:
            next_child=child.get_next_sibling();self.choices.remove(child);child=next_child
        self.selected=[]
        for source,target in learning.propose(self.original,self.edited()):
            check=Gtk.CheckButton(label=f'学习：{source} → {target}',active=True)
            self.choices.append(check);self.selected.append((check,source,target))
        if not self.selected:self.choices.append(Gtk.Label(label='只学习短词纠正；改标点或大段改写不会加入词库。',xalign=0,wrap=True))
    def save(self,*_):
        try:
            current=json.loads(state_path.read_text())
            if current.get('started')!=self.snapshot.get('started') or current.get('phase')!='result':
                self.notice.set_text('已产生新的录音结果，请关闭后重新打开，避免混淆纠正。');return
            enabled=json.loads(config_path.read_text()).get('learning',True)
            pairs=[(s,t) for check,s,t in self.selected if check.get_active()]
            n=learning.record(pairs,str(self.snapshot.get('started')),None) if enabled and pairs else 0
            corrected=self.edited()
            current['text']=corrected;current['message']='纠正已保存，可复制后粘贴'
            tmp=state_path.with_suffix('.tmp');tmp.write_text(json.dumps(current,ensure_ascii=False));tmp.replace(state_path)
            subprocess.run([cli,'copy'],check=True,capture_output=True)
            self.notice.set_text(f'已复制；确认了 {n} 条词语纠正。' if enabled else '已复制；自动学习已关闭。')
        except Exception as exc:self.notice.set_text(f'保存失败：{exc}')
    def refresh(self):
        child=self.rows.get_first_child()
        while child:
            nxt=child.get_next_sibling();self.rows.remove(child);child=nxt
        data=learning.load();active={r['id'] for r in learning.active_rules(data)}
        if not data['rules']:self.rows.append(Gtk.Label(label='还没有学习记录。纠正结果后会在这里出现。',wrap=True))
        for row in data['rules']:
            line=Gtk.Box(spacing=10)
            status='自动应用' if row['id'] in active else '候选 / 有冲突'
            label=Gtk.Label(label=f"{row['source']} → {row['target']}\n已确认 {row['count']} 次 · {status}",wrap=True,xalign=0,hexpand=True)
            button=Gtk.Button(label='删除');button.connect('clicked',lambda _,rid=row['id']:self.remove(rid))
            line.append(label);line.append(button);self.rows.append(line)
    def remove(self,rule_id):
        learning.delete(rule_id);self.refresh()
    def confirm_clear(self,*_):
        dialog=Gtk.MessageDialog(transient_for=self.window,modal=True,buttons=Gtk.ButtonsType.OK_CANCEL,text='清空全部学习记录？')
        def response(d,r):
            if r==Gtk.ResponseType.OK:learning.delete();self.refresh()
            d.destroy()
        dialog.connect('response',response);dialog.present()
if __name__ == '__main__':
    Editor().run([])
