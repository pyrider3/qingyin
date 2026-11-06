"""Qingyin preferences: local hardware, models and output controls."""
import json
import subprocess
import threading
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib
import settings_data as data
import preview as live
from model_catalog import MODELS, installed

CONFIG = Path.home()/'.config/qingyin/config.json'
CLI = str(Path.home()/'.local/bin/qingyin')
PAGES = [('engine', '◈', '识别引擎'), ('output', '✎', '输出与学习'), ('input', '◉', '输入与快捷键')]
CSS = '''
@define-color accent #5fe2d5;
window.qy { background: linear-gradient(160deg, #0b121a 0%, #0d1620 55%, #0a1118 100%); color: #e6eef6; }
window.qy headerbar { background: transparent; border: none; box-shadow: none; min-height: 0; }
window.qy headerbar label { color: #7d92a8; font-size: 12px; letter-spacing: 1px; }

.sidebar { background: rgba(255,255,255,0.025); border-right: 1px solid rgba(255,255,255,0.06); padding: 8px 14px 18px 14px; }
.brand { font-size: 28px; font-weight: 800; color: @accent; }
.wordmark { font-size: 10px; letter-spacing: 4px; color: #6f849a; }
.nav { background: transparent; border: none; box-shadow: none; padding: 11px 14px; border-radius: 12px; color: #93a6ba;
       transition: background 220ms ease, color 220ms ease; }
.nav:hover { background: rgba(255,255,255,0.05); color: #dbe7f2; }
.nav.active { background: rgba(95,226,213,0.14); color: #7ef2e2; font-weight: 700; }
.nav-icon { font-size: 15px; min-width: 22px; }
.side-note { color: #6f849a; font-size: 11px; }

.page-title { font-size: 28px; font-weight: 800; color: #f1f7fc; }
.muted { color: #8296ab; font-size: 12px; }
.section { font-size: 11px; font-weight: 700; letter-spacing: 2px; color: #62d8cc; margin-top: 10px; }
.card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.07); border-radius: 18px; padding: 6px 20px;
        transition: border-color 250ms ease, background 250ms ease; }
.card:hover { border-color: rgba(95,226,213,0.22); background: rgba(255,255,255,0.05); }
.row { padding: 14px 0; }
.row-title { font-weight: 600; font-size: 14px; color: #eef5fb; }
.hairline { background: rgba(255,255,255,0.06); min-height: 1px; }

dropdown > button, entry, spinbutton { background: rgba(8,14,21,0.7); color: #e6eef6; border: 1px solid rgba(255,255,255,0.1);
        border-radius: 11px; min-height: 36px; box-shadow: none; transition: border-color 200ms ease, background 200ms ease, box-shadow 200ms ease; }
dropdown > button:hover, entry:hover, spinbutton:hover { border-color: rgba(95,226,213,0.45); }
entry:focus-within, spinbutton:focus-within { border-color: @accent; box-shadow: 0 0 0 3px rgba(95,226,213,0.16); }
spinbutton button { background: transparent; border: none; box-shadow: none; color: #b7c7d7; }
popover > contents { background: #121c27; border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; color: #e6eef6; }
popover modelbutton, popover row { border-radius: 8px; }

button.ghost { background: rgba(255,255,255,0.05); color: #d4e4f0; border: 1px solid rgba(255,255,255,0.09); border-radius: 11px;
        box-shadow: none; padding: 7px 16px; transition: background 200ms ease, border-color 200ms ease; }
button.ghost:hover { background: rgba(95,226,213,0.12); border-color: rgba(95,226,213,0.4); }
button.ghost:active { background: rgba(95,226,213,0.2); }
button.ghost:disabled { opacity: 0.45; }
button.primary { background: linear-gradient(135deg, #5fe2d5, #3fc2de); color: #06292b; border: none; border-radius: 12px; font-weight: 800;
        padding: 10px 26px; box-shadow: 0 6px 18px rgba(63,194,222,0.28); transition: box-shadow 220ms ease, opacity 220ms ease; }
button.primary:hover { box-shadow: 0 8px 26px rgba(95,226,213,0.45); }
button.primary:active { opacity: 0.85; }

switch { background: rgba(255,255,255,0.12); border: none; min-width: 46px; min-height: 26px; border-radius: 13px;
        transition: background 240ms ease; }
switch:checked { background: #34bfae; }
switch slider { background: #f4fafe; border: none; border-radius: 11px; min-width: 22px; min-height: 22px; margin: 2px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.4); transition: all 240ms cubic-bezier(0.3, 0.9, 0.3, 1); }

progressbar.meter trough { background: rgba(255,255,255,0.08); border-radius: 6px; min-height: 8px; border: none; }
progressbar.meter progress { background: linear-gradient(90deg, #3fc2de, #5fe2d5); border-radius: 6px; min-height: 8px; min-width: 0; border: none; margin: 0; }
progressbar.meter.low progress { background: linear-gradient(90deg, #ff9d5c, #ffcd85); }

.footer { background: rgba(10,17,24,0.92); border-top: 1px solid rgba(255,255,255,0.07); padding: 14px 28px; }
.pill { padding: 5px 12px; border-radius: 999px; background: rgba(255,255,255,0.06); font-size: 12px; color: #9fb2c5; }
.pill.good { background: rgba(95,226,213,0.16); color: #7ef2e2; }
.pill.warning { background: rgba(255,205,133,0.16); color: #ffcd85; }
.pill.dirty { background: rgba(95,226,213,0.1); color: #9fe9e0; }
.kbd { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.12); border-bottom-width: 2px; border-radius: 8px;
       padding: 4px 10px; font-family: monospace; font-size: 12px; color: #dcebf7; }
scrollbar slider { background: rgba(255,255,255,0.18); border-radius: 4px; min-width: 6px; }
'''


def label(text, style=None):
    widget = Gtk.Label(label=text, xalign=0, wrap=True)
    if style: widget.add_css_class(style)
    return widget


def box(spacing=12):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def animate(widget, target, duration=420):
    """Ease a ProgressBar to its new fraction on the frame clock; a newer call replaces an older one."""
    start = widget.get_fraction(); state = {'t0': None}; token = widget._animation = object()
    def step(w, clock):
        if w._animation is not token: return GLib.SOURCE_REMOVE
        now = clock.get_frame_time()
        if state['t0'] is None: state['t0'] = now
        t = min(1.0, (now-state['t0'])/(duration*1000))
        eased = 1-(1-t)**3
        w.set_fraction(start+(target-start)*eased)
        return GLib.SOURCE_CONTINUE if t < 1 else GLib.SOURCE_REMOVE
    widget.add_tick_callback(step)


class Settings(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='dev.qingyin.Settings')
        self.cards = []; self.closed = False; self.loading = True; self.dirty = False
        self.page_order = []; self.current = None; self.hide_timer = 0

    def do_activate(self):
        if self.get_active_window(): self.get_active_window().present(); return
        self.config = json.loads(CONFIG.read_text())
        provider = Gtk.CssProvider(); provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window = Gtk.ApplicationWindow(application=self, title='青音 · 设置')
        self.window.add_css_class('qy'); self.window.set_default_size(940, 740)
        self.window.connect('close-request', self.close)
        header = Gtk.HeaderBar(); header.set_show_title_buttons(True)
        title = label('青音 / 控制中心', 'muted'); title.set_wrap(False); header.set_title_widget(title)
        self.window.set_titlebar(header)
        root = box(0); body = Gtk.Box(); body.set_vexpand(True)
        sidebar = box(6); sidebar.add_css_class('sidebar'); sidebar.set_size_request(190, -1)
        sidebar.append(label('青音', 'brand')); wordmark = label('Q I N G Y I N', 'wordmark'); wordmark.set_margin_bottom(26)
        sidebar.append(wordmark)
        self.stack = Gtk.Stack(transition_duration=260)
        self.stack.set_hexpand(True); self.buttons = {}
        for name, icon, title in PAGES:
            inner = Gtk.Box(spacing=10); glyph = label(icon, 'nav-icon'); glyph.set_xalign(.5)
            inner.append(glyph); inner.append(label(title))
            button = Gtk.Button(child=inner); button.add_css_class('nav')
            button.connect('clicked', lambda _, page=name: self.navigate(page))
            self.buttons[name] = button; self.page_order.append(name); sidebar.append(button)
        spacer = box(0); spacer.set_vexpand(True); sidebar.append(spacer)
        sidebar.append(label('完全本地\n按需加载 · 用完释放', 'side-note'))
        body.append(sidebar); body.append(self.stack); root.append(body)
        self.engine(); self.output(); self.input()
        # Footer slides up only when there is something to say or save.
        self.footer_reveal = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, transition_duration=260)
        footer = Gtk.Box(spacing=16); footer.add_css_class('footer')
        self.notice = Gtk.Label(label='', xalign=0); self.notice.add_css_class('pill'); self.notice.set_hexpand(False)
        pill_wrap = Gtk.Box(); pill_wrap.set_hexpand(True); pill_wrap.set_valign(Gtk.Align.CENTER); pill_wrap.append(self.notice)
        footer.append(pill_wrap)
        self.save_button = Gtk.Button(label='保存设置'); self.save_button.add_css_class('primary')
        self.save_button.connect('clicked', self.save); footer.append(self.save_button)
        self.footer_reveal.set_child(footer); root.append(self.footer_reveal)
        self.window.set_child(root); self.navigate('engine'); self.window.present()
        self.hook_dirty(); self.loading = False
        self.refresh()

    def close(self, *_): self.closed = True; return False

    # --- state feedback -------------------------------------------------
    def say(self, text, kind=''):
        if self.hide_timer: GLib.source_remove(self.hide_timer); self.hide_timer = 0
        for css in ('good', 'warning', 'dirty'): self.notice.remove_css_class(css)
        if kind: self.notice.add_css_class(kind)
        self.notice.set_text(text); self.footer_reveal.set_reveal_child(bool(text))
        if kind == 'good': self.hide_timer = GLib.timeout_add(2600, self.fade_notice)

    def fade_notice(self):
        self.hide_timer = 0
        if not self.dirty: self.footer_reveal.set_reveal_child(False)
        return GLib.SOURCE_REMOVE

    def mark_dirty(self, *_):
        if self.loading or self.dirty: return
        self.dirty = True; self.say('有未保存的更改 · 保存后下次录音生效', 'dirty')

    def hook_dirty(self):
        for widget in (self.device, self.model, self.compute, self.language, self.mic):
            widget.connect('notify::selected', self.mark_dirty)
        for widget in (self.resident, self.punctuation, self.auto, self.panel, self.preview, self.learning, self.rime):
            widget.connect('notify::active', self.mark_dirty)
        self.beam.connect('value-changed', self.mark_dirty); self.hotwords.connect('changed', self.mark_dirty)

    def navigate(self, name):
        if name == self.current: return
        if self.current is None: self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        else:
            forward = self.page_order.index(name) > self.page_order.index(self.current)
            self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP if forward else Gtk.StackTransitionType.SLIDE_DOWN)
        self.current = name; self.stack.set_visible_child_name(name)
        for key, button in self.buttons.items():
            if key == name: button.add_css_class('active')
            else: button.remove_css_class('active')

    # --- building blocks ------------------------------------------------
    def page(self, name, title, subtitle):
        content = box(14)
        for side in ('top', 'bottom'): getattr(content, 'set_margin_'+side)(28)
        for side in ('start', 'end'): getattr(content, 'set_margin_'+side)(34)
        content.append(label(title, 'page-title')); sub = label(subtitle, 'muted'); sub.set_margin_bottom(6); content.append(sub)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(content); self.stack.add_named(scroll, name)
        return content

    def card(self, page, title):
        page.append(label(title, 'section')); card = box(0); card.add_css_class('card'); page.append(card)
        return card

    def separate(self, card):
        if card.get_first_child(): line = Gtk.Box(); line.add_css_class('hairline'); card.append(line)

    def row(self, card, title, description, widget):
        self.separate(card)
        line = Gtk.Box(spacing=20); line.add_css_class('row'); text = box(4); text.set_hexpand(True)
        text.append(label(title, 'row-title')); text.append(label(description, 'muted'))
        line.append(text); widget.set_valign(Gtk.Align.CENTER); line.append(widget); card.append(line)

    def block(self, card, *widgets):
        self.separate(card)
        inner = box(10); inner.add_css_class('row')
        for widget in widgets: inner.append(widget)
        card.append(inner); return inner

    def ghost(self, text, handler):
        button = Gtk.Button(label=text); button.add_css_class('ghost'); button.set_halign(Gtk.Align.START)
        button.connect('clicked', handler); return button

    # --- pages ----------------------------------------------------------
    def engine(self):
        page = self.page('engine', '让声音，变成文字', '选择算力和模型。设置界面不会加载识别模型。')
        card = self.card(page, '计算设备')
        self.devices = [('cpu', '', 'CPU · 本机处理器'), ('cuda', '', 'GPU · 自动选择最大显存')]
        if self.config.get('gpu_uuid'):
            self.devices.append(('cuda', self.config['gpu_uuid'], '已固定显卡 · 正在查询'))
        self.device = Gtk.DropDown.new_from_strings([item[2] for item in self.devices])
        self.device.set_hexpand(True)
        self.device.set_selected(0 if self.config['device']=='cpu' else (2 if self.config.get('gpu_uuid') else 1))
        self.device.connect('notify::selected', lambda *_: self.device_info())
        self.gpu_info = label('正在读取显卡状态…', 'muted')
        self.meter = Gtk.ProgressBar(); self.meter.add_css_class('meter'); self.meter.set_visible(False)
        refresh = self.ghost('刷新设备', lambda _: self.refresh())
        self.minimum = max(6144, int(self.config.get('gpu_min_free_mib', 6144)))
        guard = label(f'显存保护：加载前至少需要 {self.minimum/1024:g} GiB 空闲显存；指定显卡不可用时停止加载。', 'muted')
        self.block(card, self.device, self.meter, self.gpu_info, refresh, guard)
        self.resident = Gtk.Switch(active=self.config.get('resident_model', False))
        self.row(card, '模型常驻', '首次录音加载后保留模型，加快后续识别；持续占用内存 / 显存', self.resident)
        card = self.card(page, '本地识别模型')
        self.models = data.models(self.config)
        names = [p.name+' · '+MODELS.get(p.name, ('','自定义模型'))[1] for p in self.models]
        self.model = Gtk.DropDown.new_from_strings(names)
        self.model.set_selected(next(i for i,p in enumerate(self.models) if str(p)==self.config['model']))
        self.model_info = label('', 'muted')
        self.model.connect('notify::selected', lambda *_: self.update_model()); self.update_model()
        self.block(card, self.model, self.model_info, label('以上只显示已安装模型，支持中文和中英混说。', 'muted'))
        self.catalog_names = list(MODELS)
        self.catalog = Gtk.DropDown.new_from_strings([name+' · '+MODELS[name][1] for name in self.catalog_names])
        self.catalog.set_selected(self.catalog_names.index('small'))
        self.download_button = self.ghost('下载所选模型', self.download_model)
        self.download_notice = label('下载需要联网；识别仍完全离线。小模型更省资源，准确率可能下降。', 'muted')
        self.download_bar = Gtk.ProgressBar(); self.download_bar.add_css_class('meter'); self.download_bar.set_visible(False)
        self.block(card, self.catalog, self.download_button, self.download_bar, self.download_notice)
        self.compute = Gtk.DropDown.new_from_strings(['FP16 · 标准精度', 'INT8 + FP16 · 降低显存占用'])
        self.compute.set_selected(1 if self.config.get('compute_type')=='int8_float16' else 0)
        self.row(card, 'GPU 推理精度', 'CPU 始终使用 INT8；显存保护保持开启', self.compute)
        card = self.card(page, '识别偏好')
        self.language = Gtk.DropDown.new_from_strings(['中文 / 中英混说', '自动识别语言'])
        self.language.set_selected(0 if self.config['language']=='zh' else 1)
        self.row(card, '识别语言', '中文输出统一为简体', self.language)
        self.beam = Gtk.SpinButton.new_with_range(1, 10, 1); self.beam.set_value(self.config.get('beam_size', 5))
        self.row(card, '解码精度', '1 更快；5 精度优先，数值越高通常越慢', self.beam)

    def run_download(self, key, label, button, notice, bar, finished):
        """Run download_model.py, streaming its PROGRESS lines into a smooth progress bar."""
        button.set_sensitive(False); bar.set_fraction(0); bar.set_visible(True)
        notice.set_text('正在连接下载源… '+label)
        def work():
            try:
                root = Path(__file__).resolve().parents[1]
                proc = subprocess.Popen([str(root/'.venv/bin/python'), str(root/'download_model.py'), key],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                reason = ''
                for line in proc.stdout:
                    if line.startswith('下载失败'): reason = line.strip()[:140]
                    if line.startswith('PROGRESS '):
                        try: _, done, total = line.split(); GLib.idle_add(self.download_progress, bar, notice, label, int(done), int(total))
                        except ValueError: pass
                error = '' if proc.wait()==0 else (reason or '下载失败，请检查网络或磁盘空间后重试')+'；已下载的部分会保留，再点一次继续'
            except Exception: error = '无法启动下载程序，请检查安装环境'
            GLib.idle_add(self.download_done, bar, finished, error)
        threading.Thread(target=work, daemon=True).start()

    def download_progress(self, bar, notice, label, done, total):
        if self.closed or not total: return False
        animate(bar, min(1.0, done/total), 260)
        notice.set_text(f'正在下载 {label}… {done*100//total}% · {done/1e6:.0f} / {total/1e6:.0f} MB')
        return False

    def download_done(self, bar, finished, error):
        if self.closed: return False
        bar.set_visible(False); return finished(error)

    def download_model(self, *_):
        name = self.catalog_names[self.catalog.get_selected()]
        self.run_download(name, name, self.download_button, self.download_notice, self.download_bar,
                          lambda error: self.download_finished(name, error))

    def download_finished(self, name, error):
        if self.closed: return False
        self.download_button.set_sensitive(True)
        if error: self.download_notice.set_text(error); return False
        previous = str(self.models[self.model.get_selected()])
        self.models = data.models(self.config)
        was = self.loading; self.loading = True  # refreshing the list is not a user edit
        self.model.set_model(Gtk.StringList.new([p.name+' · '+MODELS.get(p.name, ('','自定义模型'))[1] for p in self.models]))
        self.model.set_selected(next((i for i,p in enumerate(self.models) if str(p)==previous),0))
        self.loading = was
        self.download_notice.set_text(name+' 已安装；在上方选择后保存即可使用')
        self.update_model(); return False

    def download_preview(self, *_):
        self.run_download('streaming-preview', '实时预览模型', self.preview_button, self.preview_notice, self.preview_bar,
                          self.preview_finished)

    def preview_finished(self, error):
        if self.closed: return False
        self.preview_button.set_sensitive(True)
        if error: self.preview_notice.set_text(error)
        else: self.preview_box.set_visible(False)
        return False

    def update_model(self):
        index = self.model.get_selected()
        if index >= len(self.models): return
        p = self.models[index]
        self.model_info.set_text(str(p) + ('\n模型文件缺失，请重新安装' if not installed(p) else '') + ('\nParaformer 仅用 CPU 识别；手填热词和词库筛词不生效，个人纠错仍生效' if (p/'tokens.txt').is_file() else ''))

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
        was = self.loading; self.loading = True  # rebuilding the list is not a user edit
        self.device.set_model(Gtk.StringList.new([d[2] for d in self.devices]))
        self.device.set_selected(next(i for i,d in enumerate(self.devices) if d[:2]==selected))
        self.loading = was
        self.device_info(); return False

    def device_info(self):
        index = self.device.get_selected()
        if index >= len(self.devices): return
        device, uuid, _ = self.devices[index]
        gpu = None
        if device=='cpu': text = 'CPU 识别使用 INT8，不占显存；大模型可能较慢。'
        else:
            gpu = next((g for g in self.cards if g['uuid']==uuid), None) if uuid else max(self.cards,key=lambda g:g['total'],default=None)
            text = (f"空闲 {gpu['free']/1024:.1f} / 总计 {gpu['total']/1024:.1f} GiB\n" +
                    ('余量充足' if gpu['free']>=getattr(self,'minimum',6144) else '显存余量不足，识别时会停止加载')) if gpu else getattr(self,'gpu_error','正在查询显卡…') or '指定显卡不可用'
        self.gpu_info.set_text(text)
        self.meter.set_visible(gpu is not None)
        if gpu:
            if gpu['free'] < getattr(self, 'minimum', 6144): self.meter.add_css_class('low')
            else: self.meter.remove_css_class('low')
            animate(self.meter, gpu['free']/max(1, gpu['total']))

    def output(self):
        page = self.page('output', '你的表达，你做主', '只调整输出方式，识别始终留在本机。')
        card = self.card(page, '文字输出')
        self.punctuation = Gtk.Switch(active=self.config.get('punctuation', True))
        self.row(card, '自动补标点', 'CPU 本地处理；不换段，不在末尾追加句号', self.punctuation)
        self.auto = Gtk.Switch(active=self.config.get('auto_input', True))
        self.row(card, '自动输入文本框', '关闭后可用 qingyin copy 复制结果', self.auto)
        self.panel = Gtk.Switch(active=self.config.get('show_panel', False))
        self.row(card, '悬浮预览', '录音和转写时显示状态窗口', self.panel)
        self.preview = Gtk.Switch(active=self.config.get('live_preview', True))
        self.row(card, '边说边出字', '录音时在输入框显示带下划线的预览，停止后由正式识别结果替换；仅用 CPU，不影响最终准确率', self.preview)
        self.preview_button = self.ghost('下载预览模型（约 237 MB）', self.download_preview)
        self.preview_notice = label('需要联网下载一次；识别仍完全离线。需重新编译并加载 fcitx5 插件后，输入框内才显示预览，悬浮预览不受影响。', 'muted')
        self.preview_bar = Gtk.ProgressBar(); self.preview_bar.add_css_class('meter'); self.preview_bar.set_visible(False)
        self.preview_box = self.block(card, self.preview_button, self.preview_bar, self.preview_notice)
        self.preview_box.set_visible(not live.installed())
        card = self.card(page, '个人词库')
        self.learning = Gtk.Switch(active=self.config.get('learning', True))
        self.row(card, '上下文与自动学习', '在支持的输入框中学习短词纠正，密码框除外', self.learning)
        self.rime = Gtk.Switch(active=self.config.get('rime_dictionary', True))
        self.row(card, '雾凇拼音词库', '从输入框上下文筛选本地词条；最多 16 个，不强制替换', self.rime)
        self.hotwords = Gtk.Entry(text=self.config.get('hotwords', '')); self.hotwords.set_placeholder_text('人名、软件名、专业词，逗号分隔')
        self.block(card, label('识别热词', 'row-title'), self.hotwords,
                   self.ghost('管理个人词库', lambda _: subprocess.Popen([CLI,'vocabulary'])))

    def input(self):
        page = self.page('input', '按一下，开始说', '默认用完即释放；开启常驻后保留模型供下次使用。')
        card = self.card(page, '音频输入')
        try: self.sources = data.microphones()
        except Exception: self.sources = [(None, '系统默认麦克风')]
        current = self.config.get('microphone')
        if current and not any(key==current for key,_ in self.sources): self.sources.append((current,'已选择麦克风 · 当前不可用'))
        self.mic = Gtk.DropDown.new_from_strings([name for _,name in self.sources])
        self.mic.set_selected(next(i for i,(key,_) in enumerate(self.sources) if key==current))
        self.block(card, self.mic, label('蓝牙耳机麦克风可能影响清晰度，优先选择内置或 USB 麦克风。','muted'))
        card = self.card(page, '快捷键')
        for title, hint in [('Win + A','开始录音 / 停止并转写'), ('Win + Alt + Esc','取消录音或转写'), ('Win + Alt + A','纠正上一条结果')]:
            keys = Gtk.Box(spacing=6)
            for part in title.split(' + '):
                chip = Gtk.Label(label=part); chip.add_css_class('kbd'); keys.append(chip)
            self.row(card, hint, '', keys)
        card = self.card(page, '本地与隐私')
        self.block(card, label('语音、识别和补标点均在本地运行。录音识别后删除；个人词库只保存短词对和次数。','muted'))

    def save(self, *_):
        try:
            state = json.loads(subprocess.check_output([CLI,'status'], timeout=2))
            if state.get('running') and state['phase'] in ('recording','transcribing'):
                self.say('请先停止或取消录音 / 转写', 'warning'); return
            device, uuid, _ = self.devices[self.device.get_selected()]
            model = self.models[self.model.get_selected()]
            if not installed(model): raise ValueError('模型文件不存在，无法保存')
            if device=='cuda' and uuid and not any(g['uuid']==uuid for g in self.cards):
                raise ValueError('指定显卡当前不可用，请刷新或选择 CPU')
            stopped = subprocess.run(['systemctl','--user','stop','qingyin-model.service'], capture_output=True, timeout=5)
            if stopped.returncode: raise ValueError('无法释放常驻模型，请重试；设置未保存')
            self.config = data.save(CONFIG, dict(resident_model=self.resident.get_active(),device=device,gpu_uuid=uuid,model=str(model),
                compute_type='int8_float16' if self.compute.get_selected()==1 else 'float16',
                beam_size=self.beam.get_value_as_int(),language='zh' if self.language.get_selected()==0 else 'auto',
                rime_dictionary=self.rime.get_active(),punctuation=self.punctuation.get_active(),learning=self.learning.get_active(),
                auto_input=self.auto.get_active(),show_panel=self.panel.get_active(),live_preview=self.preview.get_active(),
                microphone=self.sources[self.mic.get_selected()][0],hotwords=self.hotwords.get_text().strip()))
            self.dirty = False; self.say('已保存 ✓ 下次录音生效', 'good')
        except Exception as exc:
            self.say('保存失败：'+str(exc), 'warning')


if __name__=='__main__': Settings().run([])
