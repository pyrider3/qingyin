"""Local preferences. Changes apply on the next on-demand recording."""
import gi, json, subprocess, os
from pathlib import Path
gi.require_version('Gtk','4.0')
from gi.repository import Gtk, Gdk
config_path=Path.home()/'.config/qingyin/config.json'
cli=str(Path.home()/'.local/bin/qingyin')
class Settings(Gtk.Application):
 def __init__(self): super().__init__(application_id='dev.qingyin.Settings')
 def do_activate(self):
  if self.get_active_window():self.get_active_window().present();return
  self.config=json.loads(config_path.read_text())
  w=Gtk.ApplicationWindow(application=self,title='青音 · 设置');w.set_default_size(460,380)
  box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14)
  for f in ('top','bottom','start','end'):getattr(box,'set_margin_'+f)(24)
  box.append(Gtk.Label(label='青音 · 完全本地语音输入',xalign=0))
  def row(label,widget):
   line=Gtk.Box(spacing=16);text=Gtk.Label(label=label,xalign=0);text.set_hexpand(True);line.append(text);line.append(widget);box.append(line)
  self.device=Gtk.DropDown.new_from_strings(['NVIDIA 显卡','CPU'])
  self.device.set_selected(0 if self.config['device']=='cuda' else 1);row('识别设备',self.device)
  self.language=Gtk.DropDown.new_from_strings(['中文（可中英混说）','自动识别语言'])
  self.language.set_selected(0 if self.config['language']=='zh' else 1);row('识别语言',self.language)
  self.auto=Gtk.Switch(active=self.config['auto_input']);row('转写后自动输入',self.auto)
  self.panel=Gtk.Switch(active=self.config.get('show_panel',False));row('显示悬浮预览',self.panel)
  model_parent=Path(self.config['model']).parent
  self.models=[p for p in sorted(model_parent.iterdir()) if (p/'model.bin').exists()]
  self.model=Gtk.DropDown.new_from_strings([p.name for p in self.models])
  self.model.set_selected(next((i for i,p in enumerate(self.models) if str(p)==self.config['model']),0));row('识别模型',self.model)
  self.hotwords=Gtk.Entry(text=self.config.get('hotwords',''))
  self.hotwords.set_placeholder_text('人名、软件名、专业词，逗号分隔');row('识别热词',self.hotwords)
  self.sources=[(None,'系统默认麦克风')]
  try:
   nodes=json.loads(subprocess.check_output(['pw-dump']))
   for node in nodes:
    props=node.get('info',{}).get('props',{})
    if props.get('media.class')=='Audio/Source':
     self.sources.append((props['node.name'],props.get('node.description',props['node.name'])))
  except Exception:pass
  self.mic=Gtk.DropDown.new_from_strings([name for _,name in self.sources])
  self.mic.set_selected(next((i for i,(key,_) in enumerate(self.sources) if key==self.config['microphone']),0));row('麦克风',self.mic)
  box.append(Gtk.Label(label='Win+A：开始 / 停止\nWin+Alt+Esc：取消\n按需启动 · 结束后释放内存 / 显存\n中文输出统一为简体\n精度优先：GPU FP16 · beam 5\n录音识别后删除，不保存文字历史。',xalign=0,wrap=True))
  self.notice=Gtk.Label(xalign=0,wrap=True);box.append(self.notice)
  save=Gtk.Button(label='保存设置');save.connect('clicked',self.save);box.append(save)
  w.set_child(box);w.present()
 def save(self,_):
  try:
   state=json.loads(subprocess.check_output([cli,'status']))
   if state.get('running',False) and state['phase'] in ('recording','transcribing'):
    self.notice.set_text('请先停止或取消录音 / 转写，再保存设置。');return
  except Exception:pass
  self.config.update(device='cuda' if self.device.get_selected()==0 else 'cpu',language='zh' if self.language.get_selected()==0 else 'auto',auto_input=self.auto.get_active(),microphone=self.sources[self.mic.get_selected()][0],show_panel=self.panel.get_active(),model=str(self.models[self.model.get_selected()]),hotwords=self.hotwords.get_text().strip())
  temporary=config_path.with_suffix('.tmp');temporary.write_text(json.dumps(self.config,ensure_ascii=False,indent=2)+'\n');temporary.replace(config_path)
  self.notice.set_text('已保存，下次录音时生效；模型按需加载，输出统一为简体。')
Settings().run([])
