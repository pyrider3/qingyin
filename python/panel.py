"""GTK4 Obsidian Dynamic Island overlay; compositor rule prevents focus stealing."""
import array
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk

state_path = Path(sys.argv[1])
cli = sys.argv[2]

CSS = b"""
window.qp {
    background: #101115;
    color: #f2f4f8;
    border-radius: 20px;
    border: 1px solid rgba(52, 211, 153, 0.34);
    font-family: "Source Han Sans CN", "Noto Sans CJK SC", "Adwaita Sans", sans-serif;
}
window.qp.error {
    border-color: rgba(245, 158, 11, 0.45);
}
.dot { font-size: 10px; color: #34d399; }
.dot.rec { color: #fb7185; }
.dot.err { color: #f59e0b; }
.heading { color: #f2f4f8; font-size: 13.5px; font-weight: 700; }
.timer { font-family: "JetBrainsMono NF", monospace; font-size: 12px; color: #96a0b0; }
.sub { color: #96a0b0; font-size: 12px; }
.body { color: #e6ecf5; font-size: 13.5px; }
button {
    background: rgba(255, 255, 255, 0.06);
    color: #e6ecf5;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 9px;
    box-shadow: none;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
    transition: background 160ms ease, border-color 160ms ease;
}
button:hover { background: rgba(255, 255, 255, 0.11); border-color: rgba(255, 255, 255, 0.2); }
button.accent { background: #34d399; color: #052e1e; border: none; font-weight: 800; }
button.accent:hover { background: #6ee7b7; }
"""


class Panel(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='dev.qingyin.Panel')
        self.once = '--once' in sys.argv
        self.target = [0.08] * 28
        self.shown = [0.08] * 28
        self.recording = False
        self.pulse = 0.0

    def do_activate(self):
        self.window = Gtk.ApplicationWindow(application=self, title='青音')
        self.window.set_default_size(380, 64)
        self.window.set_decorated(False)
        self.window.add_css_class('qp')
        self.window.connect('close-request', self.dismiss)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side, px in (('top', 12), ('bottom', 12), ('start', 16), ('end', 16)):
            getattr(root, f'set_margin_{side}')(px)

        # Compact island header row: pulse dot + title + timer + cancel
        top = Gtk.Box(spacing=8)
        top.set_valign(Gtk.Align.CENTER)
        self.dot = Gtk.Label(label='●')
        self.dot.add_css_class('dot')
        self.title = Gtk.Label(xalign=0)
        self.title.add_css_class('heading')
        self.title.set_hexpand(True)
        self.timer_lbl = Gtk.Label(label='')
        self.timer_lbl.add_css_class('timer')
        top.append(self.dot)
        top.append(self.title)
        top.append(self.timer_lbl)
        root.append(top)

        self.wave = Gtk.DrawingArea()
        self.wave.set_content_height(24)
        self.wave.set_draw_func(self.draw_wave)
        root.append(self.wave)

        self.sub = Gtk.Label(xalign=0, wrap=True)
        self.sub.set_max_width_chars(46)
        self.sub.add_css_class('sub')
        root.append(self.sub)

        self.text = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.text.set_max_width_chars(46)
        self.text.set_focusable(False)
        self.text.add_css_class('body')
        root.append(self.text)

        self.buttons = Gtk.Box(spacing=8)
        for caption, action in (('复制', 'copy'), ('纠正学习', 'edit'), ('关闭', 'cancel')):
            btn = Gtk.Button(label=caption)
            btn.connect('clicked', lambda _, a=action: subprocess.Popen([cli, a]))
            self.buttons.append(btn)
            if action == 'edit':
                self.edit_button = btn
            elif action == 'copy':
                self.copy_button = btn
                btn.add_css_class('accent')
        root.append(self.buttons)

        self.window.set_child(root)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        GLib.timeout_add(160, self.tick)
        self.wave.add_tick_callback(self.animate)
        self.tick()

    def read_levels(self):
        levels = [0.08] * 28
        try:
            with (state_path.parent / 'recording.wav').open('rb') as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 4096))
                raw = f.read()
            samples = array.array('h', raw[:len(raw) // 2 * 2])
            if samples:
                step = max(1, len(samples) // 28)
                levels = [
                    min(
                        1.0,
                        math.sqrt(
                            sum((v / 32768) ** 2 for v in samples[i * step:(i + 1) * step])
                            / max(1, len(samples[i * step:(i + 1) * step]))
                        )
                        * 5.2,
                    )
                    for i in range(28)
                ]
        except (OSError, ValueError):
            pass
        return levels

    def animate(self, _widget, _clock):
        goal = self.target if self.recording else [0.08] * 28
        self.shown = [a + (b - a) * 0.30 for a, b in zip(self.shown, goal)]
        if self.wave.get_visible():
            self.wave.queue_draw()
        return GLib.SOURCE_CONTINUE

    def draw_wave(self, _area, ctx, width, height):
        n = len(self.shown)
        slot = width / n
        bar = max(2.2, slot - 4.5)
        for i, level in enumerate(self.shown):
            h = max(3.5, height * level)
            x = i * slot + (slot - bar) / 2
            y = (height - h) / 2
            r = min(bar / 2, h / 2)
            ctx.set_source_rgba(0.20, 0.83, 0.60, 0.35 + 0.65 * level)
            ctx.new_sub_path()
            ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
            ctx.arc(x + bar - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
            ctx.arc(x + bar - r, y + h - r, r, 0, 0.5 * math.pi)
            ctx.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
            ctx.close_path()
            ctx.fill()

    def dismiss(self, *_):
        subprocess.Popen([cli, 'dismiss'])
        self.window.set_visible(False)
        if self.once:
            self.quit()
        return True

    def tick(self):
        try:
            data = json.loads(state_path.read_text())
        except (OSError, ValueError):
            return True
        phase = data.get('phase', 'idle')
        if phase == 'idle':
            self.window.set_visible(False)
            if self.once:
                self.quit()
            return True

        titles = {
            'loading': '正在加载本地模型',
            'recording': '正在聆听',
            'transcribing': '本地转写中…',
            'result': '转写完成',
            'error': '录音 / 转写失败',
        }
        self.title.set_text(titles.get(phase, phase))
        self.recording = phase == 'recording'

        for cls in ('rec', 'err'):
            self.dot.remove_css_class(cls)
        if self.recording:
            self.dot.add_css_class('rec')
            elapsed = max(0, int(time.time() - data.get('started', time.time())))
            self.timer_lbl.set_text(f'{elapsed // 60}:{elapsed % 60:02d}')
            self.target = self.read_levels()
        else:
            self.timer_lbl.set_text('')
            if phase == 'error':
                self.dot.add_css_class('err')

        if phase == 'error':
            self.window.add_css_class('error')
        else:
            self.window.remove_css_class('error')

        msg = data.get('message', '').strip()
        txt = data.get('text', '').strip()
        self.sub.set_text(msg)
        self.sub.set_visible(bool(msg) and not self.recording)
        self.text.set_text(txt)
        self.text.set_visible(bool(txt))
        self.wave.set_visible(self.recording)

        self.buttons.set_visible(phase in ('result', 'error'))
        self.copy_button.set_visible(phase == 'result' and bool(txt))
        self.edit_button.set_visible(phase == 'result' and bool(txt))
        if not self.window.get_visible():
            self.window.set_visible(True)
        return True


if __name__ == '__main__':
    Panel().run([])
