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
        self.target = [0.06]*36; self.shown = [0.06]*36; self.recording = False
    def do_activate(self):
        self.window = Gtk.ApplicationWindow(application=self, title='青音')
        self.window.set_default_size(460, 140)
        self.window.set_decorated(False); self.window.add_css_class('qp')
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
        self.text.set_max_width_chars(56); self.text.set_focusable(False); self.text.add_css_class('body')
        box.append(self.text)
        self.buttons = Gtk.Box(spacing=10)
        for label, action in [('复制', 'copy'), ('纠正并学习', 'edit'), ('取消 / 关闭', 'cancel')]:
            button = Gtk.Button(label=label)
            button.connect('clicked', lambda _, a=action: subprocess.Popen([cli, a]))
            self.buttons.append(button)
            if action == 'edit': self.edit_button = button
            if action == 'copy': self.copy_button = button; button.add_css_class('accent')
        box.append(self.buttons)
        self.window.set_child(box)
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
window.qp { background: linear-gradient(160deg, #0d1620, #0a1118); color: #eef5fb; border-radius: 20px; border: 1px solid rgba(95,226,213,0.28); }
.heading { color: #7ef2e2; font-size: 17px; font-weight: 800; }
.heading.error { color: #ffb38a; }
.body { color: #d6e3ee; font-size: 14px; }
button { background: rgba(255,255,255,0.06); color: #e6f1fa; border: 1px solid rgba(255,255,255,0.1); border-radius: 11px; box-shadow: none; padding: 6px 16px; transition: background 200ms ease, border-color 200ms ease; }
button:hover { background: rgba(95,226,213,0.14); border-color: rgba(95,226,213,0.45); }
button.accent { background: linear-gradient(135deg, #5fe2d5, #3fc2de); color: #06292b; border: none; font-weight: 800; }
""")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        GLib.timeout_add(200, self.tick)
        self.wave.add_tick_callback(self.animate)
        self.tick()
    def read_levels(self):
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
        return levels
    def animate(self, widget, clock):
        # Ease bars toward the latest levels each frame; fall back to a calm line when idle.
        goal = self.target if self.recording else [0.06]*36
        self.shown = [a + (b-a)*0.28 for a, b in zip(self.shown, goal)]
        if self.wave.get_visible(): self.wave.queue_draw()
        return GLib.SOURCE_CONTINUE
    def draw_wave(self, area, ctx, width, height):
        n = 36; slot = width/n; bar = max(2, slot-5)
        for i, level in enumerate(self.shown):
            h = max(4, height * level); x = i*slot; y = (height-h)/2; r = min(bar/2, h/2)
            ctx.set_source_rgba(0.37, 0.89, 0.84, 0.45 + 0.55*level)
            ctx.new_sub_path()
            ctx.arc(x+r, y+r, r, math.pi, 1.5*math.pi); ctx.arc(x+bar-r, y+r, r, 1.5*math.pi, 2*math.pi)
            ctx.arc(x+bar-r, y+h-r, r, 0, .5*math.pi); ctx.arc(x+r, y+h-r, r, .5*math.pi, math.pi)
            ctx.close_path(); ctx.fill()
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
        self.recording = phase == 'recording'
        if self.recording: self.target = self.read_levels()
        self.wave.set_visible(self.recording)
        if phase == 'error': self.title.add_css_class('error')
        else: self.title.remove_css_class('error')
        self.buttons.set_visible(phase in ('result', 'error', 'recording'))
        self.copy_button.set_visible(phase == 'result' and bool(data.get('text')))
        self.edit_button.set_visible(phase == 'result' and bool(data.get('text')))
        if not self.window.get_visible(): self.window.set_visible(True)
        return True
Panel().run([])
