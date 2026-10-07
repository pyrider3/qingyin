"""Qingyin preferences: local hardware, models and output controls."""
import json
import subprocess
import threading
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib
import settings_data as data
from model_catalog import MODELS

CONFIG = Path.home()/'.config/qingyin/config.json'
CLI = str(Path.home()/'.local/bin/qingyin')
CSS = '''
window { background: #0b1119; color: #e4edf5; }
headerbar { background: #101923; border-bottom: 1px solid #223343; box-shadow: none; }
.sidebar { background: #101923; border-right: 1px solid #223343; padding: 22px 12px; }
.brand { font-size: 26px; font-weight: 800; color: #5fe2d5; }
.wordmark { font-size: 10px; letter-spacing: 3px; color: #8398ae; }
.wave { font-size: 26px; color: #5fe2d5; margin-top: 12px; margin-bottom: 28px; }
.nav { background: transparent; border: none; box-shadow: none; padding: 12px; border-radius: 12px; color: #9eb0c4; }
.nav.active { background: #183b40; color: #73f0dd; }
.page-title { font-size: 25px; font-weight: 800; }
.muted { color: #8da1b6; font-size: 12px; }
.section { font-size: 11px; font-weight: 700; color: #61dace; margin-top: 8px; }
.card { background: #141f2b; border: 1px solid #283a4c; border-radius: 16px; padding: 18px; }
.row-title { font-weight: 600; font-size: 14px; }
.separator { background: #283a4c; min-height: 1px; margin-top: 6px; margin-bottom: 6px; }
dropdown, entry, spinbutton { background: #0e1721; color: #e4edf5; border: 1px solid #31475c; border-radius: 10px; }
button { background: #1c2b3a; color: #d4e4f0; border: 1px solid #31475c; border-radius: 10px; box-shadow: none; }
button:hover { background: #284052; }
button.primary { background: #54decd; color: #082b2a; border: none; font-weight: 800; padding: 10px 22px; }
button.primary:hover { background: #84f5e8; }
switch { background: #28394c; border: none; }
switch:checked { background: #36bbaa; }
switch slider { background: #edf7fc; border: none; }
.footer { border-top: 1px solid #223343; background: #101923; padding: 14px 24px; }
.good { color: #6ae5ca; }
.warning { color: #ffcd85; }
'''


def label(text, style=None):
    widget = Gtk.Label(label=text, xalign=0, wrap=True)
    if style: widget.add_css_class(style)
    return widget


def box(spacing=12):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


class Settings(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='dev.qingyin.Settings')
        self.cards = []; self.closed = False

    def do_activate(self):
        if self.get_active_window(): self.get_active_window().present(); return
        self.config = json.loads(CONFIG.read_text())
        provider = Gtk.CssProvider(); provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window = Gtk.ApplicationWindow(application=self, title='青音 · 设置')
        self.window.set_default_size(880, 720)
        self.window.connect('close-request', self.close)
        header = Gtk.HeaderBar(); title = label('青音  /  控制中心', 'muted'); title.set_wrap(False); header.set_title_widget(title)
        self.window.set_titlebar(header)
        root = box(0); body = Gtk.Box(); body.set_vexpand(True)
        sidebar = box(8); sidebar.add_css_class('sidebar'); sidebar.set_size_request(170, -1)
        sidebar.append(label('青音', 'brand')); sidebar.append(label('Q I N G Y I N', 'wordmark'))
        sidebar.append(label('▂ ▅ ▃ ▇ ▄ ▆ ▂', 'wave'))
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=180)
        self.stack.set_hexpand(True); self.buttons = {}
        for name, title in [('engine', '识别引擎'), ('output', '输出与学习'), ('input', '输入与快捷键')]:
            button = Gtk.Button(label=title); button.add_css_class('nav')
            button.connect('clicked', lambda _, page=name: self.navigate(page))
            self.buttons[name] = button; sidebar.append(button)
        spacer = box(); spacer.set_vexpand(True); sidebar.append(spacer)
        sidebar.append(label('完全本地\n按需加载 · 用完释放', 'muted'))
        body.append(sidebar); body.append(self.stack); root.append(body)
        self.engine(); self.output(); self.input()
        footer = Gtk.Box(spacing=16); footer.add_css_class('footer')
        self.notice = label('修改后点击保存，下次录音生效', 'muted'); self.notice.set_hexpand(True)
        footer.append(self.notice)
        save = Gtk.Button(label='保存设置'); save.add_css_class('primary'); save.connect('clicked', self.save)
        footer.append(save); root.append(footer)
        self.window.set_child(root); self.navigate('engine'); self.window.present()
        self.refresh()

    def close(self, *_): self.closed = True; return False

    def navigate(self, name):
        self.stack.set_visible_child_name(name)
        for key, button in self.buttons.items():
            if key == name: button.add_css_class('active')
            else: button.remove_css_class('active')

    def page(self, name, title, subtitle):
        content = box(18)
        for side in ('top', 'bottom', 'start', 'end'): getattr(content, 'set_margin_'+side)(28)
        content.append(label(title, 'page-title')); content.append(label(subtitle, 'muted'))
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(content); self.stack.add_named(scroll, name)
        return content

    def card(self, page, title):
        page.append(label(title, 'section')); card = box(14); card.add_css_class('card'); page.append(card)
        return card

    def row(self, card, title, description, widget):
        line = Gtk.Box(spacing=20); text = box(5); text.set_hexpand(True)
        text.append(label(title, 'row-title')); text.append(label(description, 'muted'))
        line.append(text); widget.set_valign(Gtk.Align.CENTER); line.append(widget); card.append(line)

    def engine(self):
        page = self.page('engine', '让声音，变成文字', '选择算力和模型。设置界面不会加载识别模型。')
        card = self.card(page, '计算设备')
        self.devices = [('cpu', '', 'CPU · 本机处理器'), ('cuda', '', 'GPU · 自动选择最大显存')]
        if self.config.get('gpu_uuid'):
            self.devices.append(('cuda', self.config['gpu_uuid'], '已固定显卡 · 正在查询'))
        self.device = Gtk.DropDown.new_from_strings([item[2] for item in self.devices])
        self.device.set_hexpand(True); card.append(self.device)
        self.device.set_selected(0 if self.config['device']=='cpu' else (2 if self.config.get('gpu_uuid') else 1))
        self.device.connect('notify::selected', lambda *_: self.device_info())
        self.gpu_info = label('正在读取显卡状态…', 'muted'); card.append(self.gpu_info)
        refresh = Gtk.Button(label='刷新设备'); refresh.set_halign(Gtk.Align.START)
        refresh.connect('clicked', lambda _: self.refresh()); card.append(refresh)
        self.minimum = max(6144, int(self.config.get('gpu_min_free_mib', 6144)))
        card.append(label(f'显存保护：加载前至少需要 {self.minimum/1024:g} GiB 空闲显存；指定显卡不可用时停止加载。', 'muted'))
        self.resident = Gtk.Switch(active=self.config.get('resident_model', False))
        self.row(card, '模型常驻', '首次录音加载后保留模型，加快后续识别；持续占用内存 / 显存', self.resident)
        card = self.card(page, '本地识别模型')
        self.models = data.models(self.config)
        names = [p.name+' · '+MODELS.get(p.name, ('','自定义模型'))[1] for p in self.models]
        self.model = Gtk.DropDown.new_from_strings(names)
        self.model.set_selected(next(i for i,p in enumerate(self.models) if str(p)==self.config['model']))
        card.append(self.model)
        self.model_info = label('', 'muted'); card.append(self.model_info)
        self.model.connect('notify::selected', lambda *_: self.update_model()); self.update_model()
        card.append(label('以上只显示已安装模型，支持中文和中英混说。', 'muted'))
        self.catalog_names = list(MODELS)
        self.catalog = Gtk.DropDown.new_from_strings([name+' · '+MODELS[name][1] for name in self.catalog_names])
        self.catalog.set_selected(self.catalog_names.index('small')); card.append(self.catalog)
        self.download_button = Gtk.Button(label='下载所选模型'); self.download_button.set_halign(Gtk.Align.START)
        self.download_button.connect('clicked', self.download_model); card.append(self.download_button)
        self.download_notice = label('下载需要联网；识别仍完全离线。小模型更省资源，准确率可能下降。', 'muted'); card.append(self.download_notice)
        self.compute = Gtk.DropDown.new_from_strings(['FP16 · 标准精度', 'INT8 + FP16 · 降低显存占用'])
        self.compute.set_selected(1 if self.config.get('compute_type')=='int8_float16' else 0)
        self.row(card, 'GPU 推理精度', 'CPU 始终使用 INT8；显存保护保持开启', self.compute)
        card = self.card(page, '识别偏好')
        self.language = Gtk.DropDown.new_from_strings(['中文 / 中英混说', '自动识别语言'])
        self.language.set_selected(0 if self.config['language']=='zh' else 1)
        self.row(card, '识别语言', '中文输出统一为简体', self.language)
        self.beam = Gtk.SpinButton.new_with_range(1, 10, 1); self.beam.set_value(self.config.get('beam_size', 5))
        self.row(card, '解码精度', '1 更快；5 精度优先，数值越高通常越慢', self.beam)

    def download_model(self, *_):
        name = self.catalog_names[self.catalog.get_selected()]
        self.download_button.set_sensitive(False); self.download_notice.set_text('正在下载 '+name+'… 完成后刷新模型列表')
        def work():
            try:
                root = Path(__file__).resolve().parents[1]
                result = subprocess.run([str(root/'.venv/bin/python'), str(root/'download_model.py'), name], capture_output=True, text=True)
                error = '' if result.returncode==0 else '下载失败，请检查网络或磁盘空间后重试'
            except Exception: error = '无法启动下载程序，请检查安装环境'
            GLib.idle_add(self.download_finished, name, error)
        threading.Thread(target=work, daemon=True).start()

    def download_finished(self, name, error):
        if self.closed: return False
        self.download_button.set_sensitive(True)
        if error: self.download_notice.set_text(error); return False
        previous = str(self.models[self.model.get_selected()])
        self.models = data.models(self.config)
        self.model.set_model(Gtk.StringList.new([p.name+' · '+MODELS.get(p.name, ('','自定义模型'))[1] for p in self.models]))
        self.model.set_selected(next((i for i,p in enumerate(self.models) if str(p)==previous),0))
        self.download_notice.set_text(name+' 已安装；在上方选择后保存即可使用')
        self.update_model(); return False

    def update_model(self):
        index = self.model.get_selected()
        if index >= len(self.models): return
        p = self.models[index]
        self.model_info.set_text(str(p) + ('\n模型文件缺失，请重新安装' if not (p/'model.bin').is_file() else ''))

    def refresh(self):
        selected = self.devices[self.device.get_selected()][:2]
        def work():
            try: cards, error = data.graphics(), ''
            except Exception: cards, error = [], '无法读取 NVIDIA 设备；CPU 仍可使用'
            GLib.idle_add(self.apply_devices, selected, cards, error)
        threading.Thread(target=work, daemon=True).start()

    def apply_devices(self, selected, cards, error):
        if self.closed: return False
        # Keep the user's latest choice if they changed it while discovery ran.
        selected = self.devices[self.device.get_selected()][:2]
        self.cards = cards; self.gpu_error = error
        self.devices = [('cpu', '', 'CPU · 本机处理器'), ('cuda', '', 'GPU · 自动选择最大显存')]
        for gpu in cards:
            self.devices.append(('cuda', gpu['uuid'], f"{gpu['name'].removeprefix('NVIDIA GeForce ')} · {gpu['total']/1024:.0f} GB"))
        if selected[0]=='cuda' and selected[1] and not any(g['uuid']==selected[1] for g in cards):
            self.devices.append(('cuda', selected[1], '已选择显卡 · 当前不可用'))
        self.device.set_model(Gtk.StringList.new([d[2] for d in self.devices]))
        self.device.set_selected(next(i for i,d in enumerate(self.devices) if d[:2]==selected))
        self.device_info(); return False

    def device_info(self):
        index = self.device.get_selected()
        if index >= len(self.devices): return
        device, uuid, _ = self.devices[index]
        if device=='cpu': text = 'CPU 识别使用 INT8，不占显存；大模型可能较慢。'
        else:
            gpu = next((g for g in self.cards if g['uuid']==uuid), None) if uuid else max(self.cards,key=lambda g:g['total'],default=None)
            text = (f"空闲 {gpu['free']/1024:.1f} / 总计 {gpu['total']/1024:.1f} GiB\n" +
                    ('余量充足' if gpu['free']>=getattr(self,'minimum',6144) else '显存余量不足，识别时会停止加载')) if gpu else getattr(self,'gpu_error','正在查询显卡…') or '指定显卡不可用'
        self.gpu_info.set_text(text)

    def output(self):
        page = self.page('output', '你的表达，你做主', '只调整输出方式，识别始终留在本机。')
        card = self.card(page, '文字输出')
        self.punctuation = Gtk.Switch(active=self.config.get('punctuation', True))
        self.row(card, '自动补标点', 'CPU 本地处理；不换段，不在末尾追加句号', self.punctuation)
        self.auto = Gtk.Switch(active=self.config.get('auto_input', True))
        self.row(card, '自动输入文本框', '关闭后可用 qingyin copy 复制结果', self.auto)
        self.panel = Gtk.Switch(active=self.config.get('show_panel', False))
        self.row(card, '悬浮预览', '录音和转写时显示状态窗口', self.panel)
        card = self.card(page, '个人词库')
        self.learning = Gtk.Switch(active=self.config.get('learning', True))
        self.row(card, '上下文与自动学习', '在支持的输入框中学习短词纠正，密码框除外', self.learning)
        self.hotwords = Gtk.Entry(text=self.config.get('hotwords', '')); self.hotwords.set_placeholder_text('人名、软件名、专业词，逗号分隔')
        card.append(label('识别热词', 'row-title')); card.append(self.hotwords)
        button = Gtk.Button(label='管理个人词库'); button.set_halign(Gtk.Align.START)
        button.connect('clicked', lambda _: subprocess.Popen([CLI,'vocabulary'])); card.append(button)

    def input(self):
        page = self.page('input', '按一下，开始说', '默认用完即释放；开启常驻后保留模型供下次使用。')
        card = self.card(page, '音频输入')
        try: self.sources = data.microphones()
        except Exception: self.sources = [(None, '系统默认麦克风')]
        current = self.config.get('microphone')
        if current and not any(key==current for key,_ in self.sources): self.sources.append((current,'已选择麦克风 · 当前不可用'))
        self.mic = Gtk.DropDown.new_from_strings([name for _,name in self.sources])
        self.mic.set_selected(next(i for i,(key,_) in enumerate(self.sources) if key==current)); card.append(self.mic)
        card.append(label('蓝牙耳机麦克风可能影响清晰度，优先选择内置或 USB 麦克风。','muted'))
        card = self.card(page, '快捷键')
        for title, hint in [('Win + A','开始录音 / 停止并转写'), ('Win + Alt + Esc','取消录音或转写'), ('Win + Alt + A','纠正上一条结果')]:
            self.row(card,title,hint,label(''))
        card = self.card(page, '本地与隐私')
        card.append(label('语音、识别和补标点均在本地运行。录音识别后删除；个人词库只保存短词对和次数。','muted'))

    def save(self, *_):
        try:
            state = json.loads(subprocess.check_output([CLI,'status'], timeout=2))
            if state.get('running') and state['phase'] in ('recording','transcribing'):
                self.notice.set_text('请先停止或取消录音 / 转写'); return
            device, uuid, _ = self.devices[self.device.get_selected()]
            model = self.models[self.model.get_selected()]
            if not (model/'model.bin').is_file(): raise ValueError('模型文件不存在，无法保存')
            if device=='cuda' and uuid and not any(g['uuid']==uuid for g in self.cards):
                raise ValueError('指定显卡当前不可用，请刷新或选择 CPU')
            stopped = subprocess.run(['systemctl','--user','stop','qingyin-model.service'], capture_output=True, timeout=5)
            if stopped.returncode: raise ValueError('无法释放常驻模型，请重试；设置未保存')
            self.config = data.save(CONFIG, dict(resident_model=self.resident.get_active(),device=device,gpu_uuid=uuid,model=str(model),
                compute_type='int8_float16' if self.compute.get_selected()==1 else 'float16',
                beam_size=self.beam.get_value_as_int(),language='zh' if self.language.get_selected()==0 else 'auto',
                punctuation=self.punctuation.get_active(),learning=self.learning.get_active(),
                auto_input=self.auto.get_active(),show_panel=self.panel.get_active(),
                microphone=self.sources[self.mic.get_selected()][0],hotwords=self.hotwords.get_text().strip()))
            self.notice.set_text('已保存 ✓ 下次录音生效'); self.notice.remove_css_class('muted'); self.notice.add_css_class('good')
        except Exception as exc:
            self.notice.set_text('保存失败：'+str(exc)); self.notice.add_css_class('warning')


if __name__=='__main__': Settings().run([])
