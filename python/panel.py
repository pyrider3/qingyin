"""GTK4 preview; compositor rule keeps recording overlay from taking focus."""
import json, sys, time, subprocess, array, math
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gdk
state_path = Path(sys.argv[1])
cli = sys.argv[2]
class Panel(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='dev.qingyin.Panel')
        self.last = None
        self.once = "--once" in sys.argv
        self.was_visible = False
    def do_activate(self):
        self.window = Gtk.ApplicationWindow(application=self, title='青音')
        self.window.set_default_size(460, 140)
        self.window.set_decorated(False)
        self.window.connect('close-request', self.dismiss)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18); box.set_margin_bottom(18)
        box.set_margin_start(22); box.set_margin_end(22)
        self.title = Gtk.Label(xalign=0)
        self.title.add_css_class('heading')
        box.append(self.title)
        self.wave = Gtk.DrawingArea()
        self.wave.set_content_height(26)
        self.wave.set_draw_func(self.draw_wave)
        box.append(self.wave)
        self.text = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.text.set_max_width_chars(56)
        box.append(self.text)
        self.buttons = Gtk.Box(spacing=10)
        for label, action in [('复制', 'copy'), ('取消 / 关闭', 'cancel')]:
            button = Gtk.Button(label=label)
            button.connect('clicked', lambda _, a=action: subprocess.Popen([cli, a]))
            self.buttons.append(button)
            if action == 'copy': self.copy_button = button
        box.append(self.buttons)
        self.window.set_child(box)
        provider = Gtk.CssProvider()
        provider.load_from_data(b'window { background: #0a1118; color: #f0f5fa; border-radius: 16px; } .heading { color: #59d8ff; font-size: 18px; font-weight: bold; } button { background: #182630; color: #e9f4ff; border-radius: 10px; }')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        GLib.timeout_add(200, self.tick)
        self.tick()
    def draw_wave(self, area, ctx, width, height):
        levels = [0.06] * 36
        try:
            with (state_path.parent / 'recording.wav').open('rb') as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 4096))
                raw = f.read()
            samples = array.array('h', raw[:len(raw)//2*2])
            if samples:
                step = max(1, len(samples)//36)
                levels = [min(1.0, math.sqrt(sum((v/32768)**2 for v in samples[i*step:(i+1)*step]) / max(1, len(samples[i*step:(i+1)*step]))) * 5) for i in range(36)]
        except (OSError, ValueError): pass
        ctx.set_source_rgb(0.35, 0.85, 1.0)
        for i, level in enumerate(levels):
            h = max(3, height * level)
            ctx.rectangle(i * width/36, (height-h)/2, max(2, width/36-5), h)
        ctx.fill()
    def dismiss(self, *_):
        subprocess.Popen([cli, 'dismiss'])
        self.window.set_visible(False)
        if self.once: self.quit()
        return True
    def tick(self):
        try: data = json.loads(state_path.read_text())
        except (OSError, ValueError): return True
        phase = data.get('phase', 'idle')
        if phase == 'idle':
            self.window.set_visible(False)
            if self.once: self.quit()
            return True
        self.was_visible = True
        titles = {'loading': '◌ 正在加载本地模型', 'recording': '● 正在录音', 'transcribing': '◌ 本地转写中', 'result': '✓ 转写完成', 'error': '录音 / 转写失败'}
        title = titles.get(phase, phase)
        if phase == 'recording': title += f" · {int(time.time() - data.get('started', time.time()))} 秒"
        self.title.set_text(title)
        self.text.set_text(data.get('message', '') + ('\n\n' + data['text'] if data.get('text') else ''))
        self.wave.set_visible(phase == 'recording')
        self.wave.queue_draw()
        self.buttons.set_visible(phase in ('result', 'error', 'recording'))
        self.copy_button.set_visible(phase == 'result' and bool(data.get('text')))
        if not self.window.get_visible(): self.window.set_visible(True)
        return True
Panel().run([])
