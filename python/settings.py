"""Qingyin Studio Settings: modern GTK4 control center for local models, memory and output."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import threading
import time

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk

from model_catalog import MODELS, installed
import preview as live
import settings_data as data
import sherpa_engine

CONFIG = Path.home() / '.config/qingyin/config.json'
CLI = str(Path.home() / '.local/bin/qingyin')

PAGES = [
    ('models', '✦', '模型与概览', '1'),
    ('engine', '◈', '性能与硬件', '2'),
    ('output', '✎', '文字与词库', '3'),
    ('input', '◉', '音频与快捷键', '4'),
]

IDLE_PRESETS = [
    (0, '不释放'),
    (3, '3 分钟'),
    (5, '5 分钟'),
    (10, '10 分钟'),
    (30, '30 分钟'),
]

AUTO_STOP_PRESETS = [
    (0, '关闭'),
    (1000, '1.0 秒'),
    (1300, '1.3 秒'),
    (1800, '1.8 秒'),
]

MODEL_META = {
    'x-asr-zh-en': dict(
        title='X-ASR 中英极速',
        badge='推荐',
        badge_cls='accent',
        summary='2026 新一代中英双语引擎，毫秒级响应、原生标点与大小写，完美支持动态热词。',
        tags=('167 MB', '~0.2s', '0 显存', '自带标点', '动态热词'),
        group='modern',
        size='136 MB',
    ),
    'funasr-nano': dict(
        title='Fun-ASR-Nano',
        badge='LLM 语义',
        badge_cls='indigo',
        summary='0.8B 声学 + Qwen 语义纠错模型，极强方言口音与上下文纠错能力。',
        tags=('964 MB', '~1.0s', '0 显存', '自带标点', '上下文提示'),
        group='modern',
        size='842 MB',
    ),
    'qwen3-asr-0.6b': dict(
        title='Qwen3-ASR 0.6B',
        badge='多语种',
        badge_cls='indigo',
        summary='通义千问 3 统一语音模型，覆盖 52 语种与 22 种中文方言，支持热词。',
        tags=('942 MB', '~1.4s', '0 显存', '52 语种', '22 方言'),
        group='modern',
        size='879 MB',
    ),
    'fire-red-asr2-ctc': dict(
        title='FireRedASR2 CTC',
        badge='声学',
        badge_cls='neutral',
        summary='小红书二代中英双语 CTC 模型，纯声学路线无幻觉，依赖常驻标点。',
        tags=('521 MB', '极快', '0 显存', '中英双语'),
        group='modern',
        size='521 MB',
    ),
    'sense-voice': dict(
        title='SenseVoice Small',
        badge='五语种',
        badge_cls='neutral',
        summary='非自回归轻量模型，覆盖中/英/粤/日/韩，内置 ITN 与标点。',
        tags=('227 MB', '~0.2s', '0 显存', '中英粤日韩'),
        group='modern',
        size='163 MB',
    ),
    'paraformer-zh': dict(
        title='Paraformer 普通话',
        badge='经典',
        badge_cls='neutral',
        summary='纯普通话轻量引擎，不支持热词与英文混说，仅推荐纯中文环境。',
        tags=('228 MB', '~0.15s', '0 显存', '纯普通话'),
        group='modern',
        size='228 MB',
    ),
    'large-v3-turbo': dict(title='Whisper large-v3-turbo', badge='GPU', badge_cls='amber',
                           summary='大模型蒸馏加速版，需占用较多显存。', tags=('1.6 GB', 'GPU 推荐'), group='whisper', size='1.6 GB'),
    'large-v3': dict(title='Whisper large-v3', badge='GPU', badge_cls='amber',
                     summary='完整多语种大模型，显存与内存占用较高。', tags=('2.9 GB', '高显存'), group='whisper', size='2.9 GB'),
    'medium': dict(title='Whisper medium', badge='GPU', badge_cls='amber',
                   summary='中等体积多语种模型。', tags=('1.5 GB', '中显存'), group='whisper', size='1.5 GB'),
    'small': dict(title='Whisper small', badge='旧默认', badge_cls='neutral',
                  summary='早期 244M 小模型，中文同音字与显存效率均落后于 X-ASR。', tags=('464 MB', '旧架构'), group='whisper', size='464 MB'),
    'base': dict(title='Whisper base', badge='轻量', badge_cls='neutral',
                 summary='极简短句模型，中文精度有限。', tags=('142 MB', '轻量'), group='whisper', size='142 MB'),
    'tiny': dict(title='Whisper tiny', badge='极轻', badge_cls='neutral',
                 summary='最小体积测试模型，精度较低。', tags=('75 MB', '极轻'), group='whisper', size='75 MB'),
}

CSS = '''
@define-color bg #101115;
@define-color rail #15171c;
@define-color surface #181a20;
@define-color surface_hi #1d2028;
@define-color ink #f2f4f8;
@define-color ink_sub #96a0b0;
@define-color ink_dim #646e7f;
@define-color accent #34d399;
@define-color accent_hi #6ee7b7;
@define-color indigo #818cf8;
@define-color amber #f59e0b;

window.qy {
    background-color: @bg;
    color: @ink;
    font-family: "Source Han Sans CN", "Noto Sans CJK SC", "Adwaita Sans", sans-serif;
}
window.qy headerbar {
    background: @bg;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    box-shadow: none;
    min-height: 40px;
}
window.qy headerbar label {
    color: @ink_dim;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.8px;
}

.rail {
    background-color: @rail;
    border-right: 1px solid rgba(255, 255, 255, 0.06);
    padding: 18px 14px 16px 14px;
}
.brand-title { font-size: 21px; font-weight: 800; color: @ink; letter-spacing: 0.5px; }
.brand-sub { font-family: "JetBrainsMono NF", monospace; font-size: 10px; color: @ink_dim; letter-spacing: 1.6px; }

button.nav {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    box-shadow: none;
    padding: 9px 12px;
    color: @ink_sub;
    transition: background 180ms ease, color 180ms ease, border-color 180ms ease;
}
button.nav:hover { background: rgba(255, 255, 255, 0.045); color: @ink; }
button.nav.active {
    background: rgba(52, 211, 153, 0.11);
    border-color: rgba(52, 211, 153, 0.26);
    color: #ecfdf5;
    font-weight: 700;
}
.nav-icon { font-size: 14px; min-width: 20px; color: @ink_dim; }
button.nav.active .nav-icon { color: @accent; }
.nav-kbd {
    font-family: "JetBrainsMono NF", monospace;
    font-size: 10px;
    color: @ink_dim;
    padding: 1px 5px;
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.04);
}
button.nav.active .nav-kbd { color: @accent_hi; background: rgba(52, 211, 153, 0.14); }

.rail-status {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    padding: 12px 13px;
}
.status-dot { font-size: 10px; color: @ink_dim; }
.status-dot.warm { color: @accent; }
.status-title { font-size: 12px; font-weight: 700; color: @ink; }
.status-metric { font-family: "JetBrainsMono NF", monospace; font-size: 11px; color: @ink_sub; }

.page-title { font-size: 24px; font-weight: 800; color: @ink; letter-spacing: -0.3px; }
.page-sub { font-size: 13px; color: @ink_sub; }
.section-head {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
    color: @ink_dim;
    margin-top: 8px;
    margin-bottom: 2px;
}

.bento {
    background: @surface;
    border: 1px solid rgba(255, 255, 255, 0.065);
    border-radius: 14px;
    padding: 13px 15px;
}
.bento-label { font-size: 11px; font-weight: 600; color: @ink_dim; }
.bento-value { font-size: 16px; font-weight: 800; color: @ink; }
.bento-value.accent { color: @accent_hi; }
.bento-meta { font-size: 11.5px; color: @ink_sub; }

.card {
    background: @surface;
    border: 1px solid rgba(255, 255, 255, 0.065);
    border-radius: 14px;
    padding: 4px 18px;
}
.row { padding: 13px 0; }
.row-title { font-size: 14px; font-weight: 600; color: @ink; }
.muted { font-size: 12px; color: @ink_sub; }
.mono { font-family: "JetBrainsMono NF", monospace; font-size: 11.5px; color: @ink_sub; }
.hairline { background: rgba(255, 255, 255, 0.055); min-height: 1px; }

.model-card {
    background: @surface;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 14px;
    padding: 14px 15px;
    transition: background 180ms ease, border-color 180ms ease;
}
.model-card:hover { background: @surface_hi; border-color: rgba(255, 255, 255, 0.14); }
.model-card.selected {
    background: rgba(52, 211, 153, 0.075);
    border-color: rgba(52, 211, 153, 0.45);
}
.model-name { font-size: 14px; font-weight: 700; color: @ink; }
.model-desc { font-size: 12px; color: @ink_sub; }

.badge {
    font-size: 10.5px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.07);
    color: @ink_sub;
}
.badge.accent { background: rgba(52, 211, 153, 0.15); color: @accent_hi; }
.badge.indigo { background: rgba(129, 140, 248, 0.16); color: #c7d2fe; }
.badge.amber { background: rgba(245, 158, 11, 0.15); color: #fcd34d; }

.tag {
    font-size: 10.5px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.05);
    color: @ink_sub;
}
.model-card.selected .tag { background: rgba(52, 211, 153, 0.10); color: #a7f3d0; }

.callout {
    background: rgba(52, 211, 153, 0.065);
    border: 1px solid rgba(52, 211, 153, 0.22);
    border-radius: 12px;
    padding: 11px 14px;
    color: #bbf7d0;
    font-size: 12px;
}

.whisper-row { padding: 10px 0; }
.expander-card {
    background: @surface;
    border: 1px solid rgba(255, 255, 255, 0.065);
    border-radius: 14px;
    padding: 8px 16px;
}
expander > title {
    padding: 4px 2px;
    color: @ink_sub;
    font-size: 13px;
    font-weight: 600;
}
expander > title:hover { color: @ink; }

.seg-group {
    background: rgba(0, 0, 0, 0.28);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 10px;
    padding: 3px;
}
button.seg {
    background: transparent;
    border: none;
    border-radius: 7px;
    box-shadow: none;
    padding: 5px 11px;
    font-size: 12px;
    font-weight: 600;
    color: @ink_sub;
    transition: background 160ms ease, color 160ms ease;
}
button.seg:hover { color: @ink; background: rgba(255, 255, 255, 0.05); }
button.seg.active {
    background: rgba(52, 211, 153, 0.18);
    color: #ecfdf5;
}

dropdown > button, entry, spinbutton {
    background: rgba(0, 0, 0, 0.26);
    color: @ink;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 10px;
    min-height: 34px;
    box-shadow: none;
    transition: border-color 180ms ease;
}
dropdown > button:hover, entry:hover, spinbutton:hover { border-color: rgba(255, 255, 255, 0.22); }
entry:focus-within, spinbutton:focus-within { border-color: @accent; }
spinbutton button { background: transparent; border: none; box-shadow: none; color: @ink_sub; }
popover > contents {
    background: #1a1d24;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    color: @ink;
}

.hotwords-wrap {
    background: rgba(0, 0, 0, 0.28);
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 12px;
    padding: 8px 10px;
}
.hotwords-wrap:focus-within { border-color: rgba(52, 211, 153, 0.55); }
textview.hotwords, textview.hotwords text {
    background: transparent;
    color: @ink;
    font-family: "JetBrainsMono NF", "Source Han Sans CN", sans-serif;
    font-size: 12.5px;
}

button.ghost {
    background: rgba(255, 255, 255, 0.05);
    color: @ink;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 9px;
    box-shadow: none;
    padding: 6px 13px;
    font-size: 12.5px;
    font-weight: 600;
    transition: background 160ms ease, border-color 160ms ease;
}
button.ghost:hover { background: rgba(255, 255, 255, 0.09); border-color: rgba(255, 255, 255, 0.2); }
button.ghost:disabled { opacity: 0.4; }

button.compact {
    padding: 4px 10px;
    font-size: 11.5px;
    border-radius: 8px;
}
button.select-pill {
    background: rgba(255, 255, 255, 0.06);
    color: @ink;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    box-shadow: none;
    padding: 4px 11px;
    font-size: 11.5px;
    font-weight: 700;
}
button.select-pill:hover { background: rgba(52, 211, 153, 0.14); border-color: rgba(52, 211, 153, 0.4); }
button.select-pill.selected {
    background: rgba(52, 211, 153, 0.18);
    border-color: rgba(52, 211, 153, 0.45);
    color: #a7f3d0;
}
button.danger-pill {
    background: transparent;
    color: #f87171;
    border: 1px solid rgba(248, 113, 113, 0.25);
    border-radius: 8px;
    box-shadow: none;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 600;
}
button.danger-pill:hover { background: rgba(248, 113, 113, 0.14); border-color: rgba(248, 113, 113, 0.5); }

button.primary {
    background: @accent;
    color: #052e1e;
    border: none;
    border-radius: 10px;
    font-weight: 800;
    font-size: 13px;
    padding: 8px 20px;
    box-shadow: 0 4px 14px rgba(52, 211, 153, 0.22);
    transition: background 160ms ease, opacity 160ms ease;
}
button.primary:hover { background: @accent_hi; }
button.primary:active { opacity: 0.85; }

switch {
    background: rgba(255, 255, 255, 0.12);
    border: none;
    min-width: 42px;
    min-height: 24px;
    border-radius: 12px;
    transition: background 200ms ease;
}
switch:checked { background: @accent; }
switch slider {
    background: #f8fafc;
    border: none;
    border-radius: 10px;
    min-width: 20px;
    min-height: 20px;
    margin: 2px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
}

progressbar.meter trough {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 999px;
    min-height: 6px;
    border: none;
}
progressbar.meter progress {
    background: linear-gradient(90deg, #10b981, #34d399);
    border-radius: 999px;
    min-height: 6px;
    min-width: 0;
    border: none;
    margin: 0;
}
progressbar.meter.low progress { background: linear-gradient(90deg, #f97316, #fbbf24); }

.dock {
    background: rgba(24, 27, 34, 0.96);
    border: 1px solid rgba(255, 255, 255, 0.11);
    border-radius: 16px;
    padding: 10px 14px 10px 18px;
    margin: 0 24px 18px 24px;
    box-shadow: 0 12px 34px rgba(0, 0, 0, 0.55);
}
.pill {
    padding: 4px 11px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.06);
    font-size: 12px;
    font-weight: 600;
    color: @ink_sub;
}
.pill.good { background: rgba(52, 211, 153, 0.16); color: #a7f3d0; }
.pill.warning { background: rgba(245, 158, 11, 0.18); color: #fde68a; }
.pill.dirty { background: rgba(245, 158, 11, 0.14); color: #fcd34d; }

.kbd {
    background: #20242e;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-bottom: 2px solid rgba(0, 0, 0, 0.5);
    border-radius: 7px;
    padding: 3px 9px;
    font-family: "JetBrainsMono NF", monospace;
    font-size: 11.5px;
    font-weight: 700;
    color: @ink;
}
.privacy-tile {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 11px;
    padding: 11px 13px;
}
scrollbar slider { background: rgba(255, 255, 255, 0.14); border-radius: 4px; min-width: 5px; }
'''


def label(text, style=None, xalign=0, wrap=True):
    widget = Gtk.Label(label=text, xalign=xalign, wrap=wrap)
    if style:
        for cls in style.split():
            widget.add_css_class(cls)
    return widget


def vbox(spacing=10):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def hbox(spacing=10):
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)


def animate(widget, target, duration=360):
    """Ease a ProgressBar to its new fraction on the frame clock; newer calls supersede older ones."""
    start = widget.get_fraction()
    state = {'t0': None}
    token = widget._animation = object()

    def step(w, clock):
        if w._animation is not token:
            return GLib.SOURCE_REMOVE
        now = clock.get_frame_time()
        if state['t0'] is None:
            state['t0'] = now
        t = min(1.0, (now - state['t0']) / (duration * 1000))
        eased = 1 - (1 - t) ** 3
        w.set_fraction(start + (target - start) * eased)
        return GLib.SOURCE_CONTINUE if t < 1 else GLib.SOURCE_REMOVE

    widget.add_tick_callback(step)


def count_hotwords(text: str) -> int:
    return len([w for w in re.split(r'[,，;\n]+', text or '') if w.strip()])


class Settings(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='dev.qingyin.Settings')
        self.cards = []
        self.closed = False
        self.loading = True
        self.dirty = False
        self.page_order = []
        self.current = None
        self.hide_timer = 0
        self.status_timer = 0
        self.service_warm = False
        self.emblem_phase = 0.0
        self.model_cards = {}
        self.whisper_buttons = {}
        self.idle_buttons = {}
        self.auto_stop_buttons = {}
        self.lang_buttons = {}
        self.auto_stop_ms = 0
        self.test_recorder = None
        self.test_wav = None

    def do_activate(self):
        if self.get_active_window():
            self.get_active_window().present()
            return
        self.config = json.loads(CONFIG.read_text())
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.window = Gtk.ApplicationWindow(application=self, title='青音 · 设置')
        self.window.add_css_class('qy')
        self.window.set_default_size(1040, 760)
        self.window.connect('close-request', self.close)

        # Keyboard shortcuts: Ctrl+S save, Ctrl+1..4 navigate, Ctrl+W close.
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect('key-pressed', self.on_key_pressed)
        self.window.add_controller(key_ctrl)

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        title = label('青音 · QINGYIN STUDIO', None, xalign=0.5, wrap=False)
        header.set_title_widget(title)
        self.window.set_titlebar(header)

        body = hbox(0)
        body.set_vexpand(True)

        # --- Left navigation rail ---
        rail = vbox(6)
        rail.add_css_class('rail')
        rail.set_size_request(232, -1)

        brand_row = hbox(11)
        brand_row.set_margin_bottom(18)
        brand_row.set_valign(Gtk.Align.CENTER)
        self.emblem = Gtk.DrawingArea()
        self.emblem.set_content_width(34)
        self.emblem.set_content_height(34)
        self.emblem.set_draw_func(self.draw_emblem)
        brand_row.append(self.emblem)
        brand_text = vbox(1)
        brand_text.append(label('青音', 'brand-title', wrap=False))
        brand_text.append(label('LOCAL VOICE v2', 'brand-sub', wrap=False))
        brand_row.append(brand_text)
        rail.append(brand_row)

        self.stack = Gtk.Stack(transition_duration=220)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        self.buttons = {}
        for name, icon, nav_title, shortcut in PAGES:
            inner = hbox(10)
            glyph = label(icon, 'nav-icon', xalign=0.5, wrap=False)
            text_lbl = label(nav_title, None, wrap=False)
            text_lbl.set_hexpand(True)
            hint = label(f'^{shortcut}', 'nav-kbd', wrap=False)
            inner.append(glyph)
            inner.append(text_lbl)
            inner.append(hint)
            btn = Gtk.Button(child=inner)
            btn.add_css_class('nav')
            btn.connect('clicked', lambda _, p=name: self.navigate(p))
            self.buttons[name] = btn
            self.page_order.append(name)
            rail.append(btn)

        spacer = vbox(0)
        spacer.set_vexpand(True)
        rail.append(spacer)

        # Live runtime status widget at bottom of rail
        status_box = vbox(6)
        status_box.add_css_class('rail-status')
        top_status = hbox(7)
        self.status_dot = label('●', 'status-dot', wrap=False)
        self.status_title = label('检测运行状态…', 'status-title', wrap=False)
        self.status_title.set_hexpand(True)
        top_status.append(self.status_dot)
        top_status.append(self.status_title)
        self.status_metric = label('0 MB · 0 显存', 'status-metric', wrap=False)
        self.release_btn = Gtk.Button(label='立即释放内存')
        self.release_btn.add_css_class('ghost')
        self.release_btn.add_css_class('compact')
        self.release_btn.set_visible(False)
        self.release_btn.connect('clicked', self.release_memory)
        status_box.append(top_status)
        status_box.append(self.status_metric)
        status_box.append(self.release_btn)
        rail.append(status_box)

        # --- Build all 4 views ---
        self.build_models_page()
        self.build_engine_page()
        self.build_output_page()
        self.build_input_page()

        # --- Floating overlay save dock ---
        overlay = Gtk.Overlay()
        overlay.set_hexpand(True)
        overlay.set_vexpand(True)
        overlay.set_child(self.stack)

        self.footer_reveal = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
            transition_duration=240,
        )
        self.footer_reveal.set_halign(Gtk.Align.CENTER)
        self.footer_reveal.set_valign(Gtk.Align.END)

        dock = hbox(12)
        dock.add_css_class('dock')
        self.notice = Gtk.Label(label='', xalign=0)
        self.notice.add_css_class('pill')
        dock.append(self.notice)

        self.reset_button = Gtk.Button(label='还原')
        self.reset_button.add_css_class('ghost')
        self.reset_button.connect('clicked', self.revert_changes)
        self.reset_button.set_visible(False)
        dock.append(self.reset_button)

        self.save_button = Gtk.Button(label='保存设置  Ctrl+S')
        self.save_button.add_css_class('primary')
        self.save_button.connect('clicked', self.save)
        dock.append(self.save_button)

        self.footer_reveal.set_child(dock)
        overlay.add_overlay(self.footer_reveal)

        body.append(rail)
        body.append(overlay)
        self.window.set_child(body)

        self.navigate('models')
        self.window.present()
        self.sync_model_ui()
        self.hook_dirty()
        self.loading = False
        self.refresh()
        self.poll_service_status()
        self.status_timer = GLib.timeout_add(3000, self.poll_service_status)

    def close(self, *_):
        self.closed = True
        if self.test_recorder is not None:
            try:
                self.test_recorder.kill()
            except Exception:
                pass
            self.test_recorder = None
        if self.test_wav is not None:
            self.test_wav.unlink(missing_ok=True)
        if self.status_timer:
            GLib.source_remove(self.status_timer)
            self.status_timer = 0
        return False

    def on_key_pressed(self, _ctrl, keyval, _keycode, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if not ctrl:
            return False
        if keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self.save()
            return True
        if keyval in (Gdk.KEY_w, Gdk.KEY_W):
            self.window.close()
            return True
        for idx, (name, *_) in enumerate(PAGES):
            if keyval == getattr(Gdk, f'KEY_{idx + 1}', None):
                self.navigate(name)
                return True
        return False

    def draw_emblem(self, _area, ctx, width, height):
        # Matte rounded tile with 5 minimal acoustic bars.
        r = 9
        ctx.new_sub_path()
        ctx.arc(width - r, r, r, -math.pi / 2, 0)
        ctx.arc(width - r, height - r, r, 0, math.pi / 2)
        ctx.arc(r, height - r, r, math.pi / 2, math.pi)
        ctx.arc(r, r, r, math.pi, 1.5 * math.pi)
        ctx.close_path()
        if self.service_warm:
            ctx.set_source_rgba(0.20, 0.83, 0.60, 0.18)
        else:
            ctx.set_source_rgba(1.0, 1.0, 1.0, 0.06)
        ctx.fill_preserve()
        ctx.set_line_width(1.0)
        if self.service_warm:
            ctx.set_source_rgba(0.20, 0.83, 0.60, 0.45)
        else:
            ctx.set_source_rgba(1.0, 1.0, 1.0, 0.12)
        ctx.stroke()

        heights = [0.28, 0.56, 0.78, 0.50, 0.30]
        bar_w = 2.6
        gap = 2.6
        total_w = len(heights) * bar_w + (len(heights) - 1) * gap
        x0 = (width - total_w) / 2
        for i, frac in enumerate(heights):
            bh = height * frac * 0.78
            x = x0 + i * (bar_w + gap)
            y = (height - bh) / 2
            br = bar_w / 2
            if self.service_warm:
                ctx.set_source_rgba(0.20, 0.83, 0.60, 0.95)
            else:
                ctx.set_source_rgba(0.75, 0.80, 0.88, 0.75)
            ctx.new_sub_path()
            ctx.arc(x + br, y + br, br, math.pi, 2 * math.pi)
            ctx.arc(x + br, y + bh - br, br, 0, math.pi)
            ctx.close_path()
            ctx.fill()

    # --- state feedback -------------------------------------------------
    def say(self, text, kind=''):
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)
            self.hide_timer = 0
        for css in ('good', 'warning', 'dirty'):
            self.notice.remove_css_class(css)
        if kind:
            self.notice.add_css_class(kind)
        self.notice.set_text(text)
        self.reset_button.set_visible(self.dirty)
        self.save_button.set_visible(self.dirty or kind == 'warning')
        self.footer_reveal.set_reveal_child(bool(text))
        if kind == 'good':
            self.hide_timer = GLib.timeout_add(2600, self.fade_notice)

    def fade_notice(self):
        self.hide_timer = 0
        if not self.dirty:
            self.footer_reveal.set_reveal_child(False)
        return GLib.SOURCE_REMOVE

    def mark_dirty(self, *_):
        if self.loading:
            return
        self.update_telemetry_cards()
        if self.dirty:
            return
        self.dirty = True
        self.say('有未保存的更改 · 保存后下次录音生效', 'dirty')

    def revert_changes(self, *_):
        self.loading = True
        cfg = self.config
        self.resident.set_active(cfg.get('resident_model', False))
        self.set_idle_minutes(int(cfg.get('idle_unload_seconds', 300)) // 60)
        self.set_auto_stop_ms(int(cfg.get('auto_stop_silence_ms', 0)))
        self.punctuation.set_active(cfg.get('punctuation', True))
        self.auto.set_active(cfg.get('auto_input', True))
        self.clipboard_fb.set_active(cfg.get('clipboard_fallback', True))
        self.clean_fillers.set_active(cfg.get('clean_fillers', False))
        self.sound_fb.set_active(cfg.get('sound_feedback', True))
        self.panel.set_active(cfg.get('show_panel', False))
        self.preview.set_active(cfg.get('live_preview', True))
        self.learning.set_active(cfg.get('learning', True))
        self.rime.set_active(cfg.get('rime_dictionary', True))
        self.beam.set_value(cfg.get('beam_size', 5))
        self.compute.set_selected(1 if cfg.get('compute_type') == 'int8_float16' else 0)
        self.language.set_selected(0 if cfg.get('language', 'zh') == 'zh' else 1)
        self.sync_lang_pills()
        self.hotwords_buf.set_text(cfg.get('hotwords', ''))
        model_idx = next((i for i, p in enumerate(self.models) if str(p) == cfg['model']), 0)
        self.model.set_selected(model_idx)
        precise_idx = next((i for i, (val, _) in enumerate(self.precise_choices) if val == cfg.get('precise_model', '')), 0)
        self.precise_dd.set_selected(precise_idx)
        dev_target = ('cpu', '') if cfg['device'] == 'cpu' else ('cuda', cfg.get('gpu_uuid', ''))
        dev_idx = next((i for i, d in enumerate(self.devices) if d[:2] == dev_target), 0)
        self.device.set_selected(dev_idx)
        mic_idx = next((i for i, (k, _) in enumerate(self.sources) if k == cfg.get('microphone')), 0)
        self.mic.set_selected(mic_idx)
        self.loading = False
        self.dirty = False
        self.sync_model_ui()
        self.say('已还原未保存的更改', 'good')

    def hook_dirty(self):
        for widget in (self.device, self.model, self.compute, self.language, self.mic, self.precise_dd):
            widget.connect('notify::selected', self.mark_dirty)
        for widget in (
            self.resident, self.punctuation, self.auto, self.clipboard_fb,
            self.clean_fillers, self.sound_fb, self.panel, self.preview, self.learning, self.rime,
        ):
            widget.connect('notify::active', self.mark_dirty)
        self.beam.connect('value-changed', self.mark_dirty)
        self.idle_minutes.connect('value-changed', self.mark_dirty)
        self.hotwords_buf.connect('changed', self.on_hotwords_changed)

    def navigate(self, name):
        if name == self.current:
            return
        if self.current is None:
            self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        else:
            forward = self.page_order.index(name) > self.page_order.index(self.current)
            self.stack.set_transition_type(
                Gtk.StackTransitionType.SLIDE_UP if forward else Gtk.StackTransitionType.SLIDE_DOWN
            )
        self.current = name
        self.stack.set_visible_child_name(name)
        for key, button in self.buttons.items():
            if key == name:
                button.add_css_class('active')
            else:
                button.remove_css_class('active')

    # --- layout helpers -------------------------------------------------
    def make_page(self, name, title_text, subtitle_text):
        outer = vbox(16)
        outer.set_margin_top(26)
        outer.set_margin_bottom(88)  # breathing room above floating save dock
        outer.set_margin_start(32)
        outer.set_margin_end(32)
        head = vbox(4)
        head.append(label(title_text, 'page-title'))
        head.append(label(subtitle_text, 'page-sub'))
        outer.append(head)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(outer)
        self.stack.add_named(scroll, name)
        return outer

    def make_card(self, page, title_text=None):
        if title_text:
            page.append(label(title_text, 'section-head'))
        card = vbox(0)
        card.add_css_class('card')
        page.append(card)
        return card

    def separate(self, card):
        if card.get_first_child():
            line = Gtk.Box()
            line.add_css_class('hairline')
            card.append(line)

    def add_row(self, card, title_text, description, widget, badge=None):
        self.separate(card)
        line = hbox(18)
        line.add_css_class('row')
        text_col = vbox(3)
        text_col.set_hexpand(True)
        title_line = hbox(8)
        title_line.append(label(title_text, 'row-title', wrap=False))
        if badge is not None:
            title_line.append(badge)
        text_col.append(title_line)
        if description:
            text_col.append(label(description, 'muted'))
        line.append(text_col)
        widget.set_valign(Gtk.Align.CENTER)
        line.append(widget)
        card.append(line)
        return line

    def add_block(self, card, *widgets):
        self.separate(card)
        inner = vbox(10)
        inner.add_css_class('row')
        for w in widgets:
            inner.append(w)
        card.append(inner)
        return inner

    def ghost(self, text, handler, compact=False):
        btn = Gtk.Button(label=text)
        btn.add_css_class('ghost')
        if compact:
            btn.add_css_class('compact')
        btn.set_halign(Gtk.Align.START)
        btn.connect('clicked', handler)
        return btn

    # --- Page 1: Models & Overview --------------------------------------
    def build_models_page(self):
        page = self.make_page('models', '模型与概览', '点选任意已安装引擎切换，未安装模型支持断点续传离线安装。')

        # 3-column Bento telemetry strip
        bento_grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        self.bento_engine = self._bento_tile('当前引擎', '—', '检测中…', accent=True)
        self.bento_memory = self._bento_tile('服务占用', '0 MB', '0 MB 显存')
        self.bento_policy = self._bento_tile('驻留策略', '—', '—')
        bento_grid.attach(self.bento_engine[0], 0, 0, 1, 1)
        bento_grid.attach(self.bento_memory[0], 1, 0, 1, 1)
        bento_grid.attach(self.bento_policy[0], 2, 0, 1, 1)
        page.append(bento_grid)

        # Back-end synced dropdowns (also preserve full programmatic/test compatibility)
        self.models = data.models(self.config)
        self.model = Gtk.DropDown.new_from_strings(
            [p.name + ' · ' + MODELS.get(p.name, ('', '自定义模型'))[1] for p in self.models]
        )
        sel = next((i for i, p in enumerate(self.models) if str(p) == self.config['model']), 0)
        self.model.set_selected(sel)
        self.model.connect('notify::selected', lambda *_: self.sync_model_ui())

        self.catalog_names = list(MODELS)
        self.catalog = Gtk.DropDown.new_from_strings(
            [name + ' · ' + MODELS[name][1] for name in self.catalog_names]
        )
        self.catalog.set_selected(
            self.catalog_names.index('x-asr-zh-en') if 'x-asr-zh-en' in self.catalog_names else 0
        )

        # Modern 2026 CPU 0-VRAM engine gallery (2-column grid)
        page.append(label('2026 新一代本地引擎（纯 CPU · 0 显存）', 'section-head'))
        self.modern_grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        modern_keys = [k for k in MODELS if MODEL_META.get(k, {}).get('group') == 'modern']
        for idx, key in enumerate(modern_keys):
            card_box, action_btn, del_btn, bar = self._make_model_card(key)
            self.model_cards[key] = (card_box, action_btn, del_btn, bar)
            self.modern_grid.attach(card_box, idx % 2, idx // 2, 1, 1)
        page.append(self.modern_grid)

        # Inline Live Mic & Speed Test Strip
        test_card = self.make_card(page, '现场试说测速')
        self.test_btn = self.ghost('开始试说', self.toggle_voice_test, compact=True)
        self.test_result = label('点击「开始试说」讲一句，再点停止即可实测识别文本与耗时（不输入到外部窗口）。', 'muted')
        self.add_row(test_card, '实时麦克风与引擎检验', '使用当前常驻引擎与热词列表进行一次离线测试', self.test_btn)
        self.add_block(test_card, self.test_result)

        # Collapsible Whisper classic models section inside a clean card
        whisper_keys = [k for k in MODELS if MODEL_META.get(k, {}).get('group') == 'whisper']
        whisper_shell = vbox(0)
        whisper_shell.add_css_class('expander-card')
        self.whisper_expander = Gtk.Expander(label='Whisper 经典模型（可选 GPU 加速）')
        whisper_list = vbox(0)
        whisper_list.set_margin_top(6)
        for key in whisper_keys:
            meta = MODEL_META[key]
            self.separate(whisper_list)
            row = hbox(12)
            row.add_css_class('whisper-row')
            info = vbox(2)
            info.set_hexpand(True)
            tline = hbox(8)
            tline.append(label(meta['title'], 'row-title', wrap=False))
            tline.append(label(meta['size'], 'tag', wrap=False))
            info.append(tline)
            info.append(label(meta['summary'], 'muted'))
            btn = Gtk.Button(label='选用')
            btn.add_css_class('select-pill')
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect('clicked', lambda _, k=key: self.on_model_action(k))
            row.append(info)
            row.append(btn)
            whisper_list.append(row)
            self.whisper_buttons[key] = btn
        self.whisper_expander.set_child(whisper_list)
        whisper_shell.append(self.whisper_expander)
        page.append(whisper_shell)

        # Compact Download Status & Path Details (advanced catalog dropdown collapsed cleanly)
        self.download_bar = Gtk.ProgressBar()
        self.download_bar.add_css_class('meter')
        self.download_bar.set_visible(False)
        self.download_notice = label('识别完全离线；模型下载支持断点续传与 SHA-256 校验。', 'muted')
        self.model_info = label('', 'mono')

        adv_shell = vbox(8)
        adv_shell.add_css_class('expander-card')
        adv_shell.append(self.download_bar)
        adv_shell.append(self.download_notice)
        adv_expander = Gtk.Expander(label='当前模型路径与高级目录下载')
        adv_body = vbox(10)
        adv_body.set_margin_top(8)
        adv_body.append(self.model_info)
        dl_row = hbox(10)
        self.catalog.set_hexpand(True)
        self.download_button = self.ghost('下载所选', self.download_model)
        dl_row.append(self.catalog)
        dl_row.append(self.download_button)
        adv_body.append(dl_row)
        adv_expander.set_child(adv_body)
        adv_shell.append(adv_expander)
        page.append(adv_shell)

    def _bento_tile(self, title_text, val_text, meta_text, accent=False):
        tile = vbox(4)
        tile.add_css_class('bento')
        tile.append(label(title_text, 'bento-label', wrap=False))
        val = label(val_text, 'bento-value accent' if accent else 'bento-value', wrap=False)
        meta = label(meta_text, 'bento-meta', wrap=False)
        tile.append(val)
        tile.append(meta)
        return tile, val, meta

    def _make_model_card(self, key):
        meta = MODEL_META[key]
        card = vbox(8)
        card.add_css_class('model-card')

        top = hbox(8)
        name_lbl = label(meta['title'], 'model-name', wrap=False)
        badge = label(meta['badge'], f"badge {meta['badge_cls']}", wrap=False)
        badge.set_valign(Gtk.Align.CENTER)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        action_btn = Gtk.Button(label='选用')
        action_btn.add_css_class('select-pill')
        action_btn.set_valign(Gtk.Align.CENTER)
        action_btn.connect('clicked', lambda _, k=key: self.on_model_action(k))
        del_btn = Gtk.Button(label='卸载')
        del_btn.add_css_class('danger-pill')
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.set_visible(False)
        del_btn.connect('clicked', lambda _, k=key: self.confirm_uninstall(k))
        top.append(name_lbl)
        top.append(badge)
        top.append(spacer)
        top.append(del_btn)
        top.append(action_btn)

        desc = label(meta['summary'], 'model-desc')
        desc.set_vexpand(True)

        tags_box = hbox(6)
        for t in meta['tags']:
            tags_box.append(label(t, 'tag', wrap=False))

        bar = Gtk.ProgressBar()
        bar.add_css_class('meter')
        bar.set_visible(False)

        card.append(top)
        card.append(desc)
        card.append(tags_box)
        card.append(bar)

        # Clicking anywhere on an installed card selects it immediately.
        click = Gtk.GestureClick()
        click.connect('released', lambda _g, _n, _x, _y, k=key: self.on_card_clicked(k))
        card.add_controller(click)
        return card, action_btn, del_btn, bar

    def confirm_uninstall(self, key):
        _, path = self._installed_path_for(key)
        models_root = (Path.home() / '.local/share/qingyin/models').resolve()
        if path is None or path.resolve().parent != models_root:
            return
        if str(path) == str(self._selected_model_path()) or str(path) == self.config.get('model'):
            self.say('不能卸载当前正在使用的模型，请先切换并保存其他模型', 'warning')
            return
        title = MODEL_META.get(key, {}).get('title', key)
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f'卸载本地模型「{title}」？',
            secondary_text=f'将删除 {path} 以释放硬盘空间，需要时可随时重新下载。',
        )

        def on_resp(d, resp):
            if resp == Gtk.ResponseType.OK:
                try:
                    shutil.rmtree(path)
                    previous = str(self._selected_model_path())
                    self.models = data.models(self.config)
                    was = self.loading
                    self.loading = True
                    self.model.set_model(Gtk.StringList.new([p.name + ' · ' + MODELS.get(p.name, ('', '自定义模型'))[1] for p in self.models]))
                    self.model.set_selected(next((i for i, p in enumerate(self.models) if str(p) == previous), 0))
                    self.loading = was
                    self.sync_model_ui()
                    self.say(f'已卸载 {title} 并释放硬盘空间 ✓', 'good')
                except Exception as exc:
                    self.say(f'卸载失败：{exc}', 'warning')
            d.destroy()

        dialog.connect('response', on_resp)
        dialog.present()

    def toggle_voice_test(self, *_):
        if self.test_recorder is not None:
            proc = self.test_recorder
            self.test_recorder = None
            self.test_btn.set_sensitive(False)
            self.test_btn.set_label('识别中…')
            self.test_result.set_text('正在本地识别试说音频…')

            def finish():
                wav = self.test_wav
                try:
                    proc.send_signal(signal.SIGINT)
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2)
                    t0 = time.perf_counter()
                    text = self._transcribe_test_wav(wav)
                    ms = int((time.perf_counter() - t0) * 1000)
                    GLib.idle_add(self._voice_test_done, text, ms, '')
                except Exception as exc:
                    GLib.idle_add(self._voice_test_done, '', 0, str(exc))
                finally:
                    if wav:
                        wav.unlink(missing_ok=True)

            threading.Thread(target=finish, daemon=True).start()
            return

        rt = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / 'qingyin'
        rt.mkdir(parents=True, exist_ok=True)
        self.test_wav = rt / 'settings_test.wav'
        self.test_wav.unlink(missing_ok=True)
        cmd = ['pw-record', '--rate', '16000', '--channels', '1', '--format', 's16', '--media-role', 'Communication']
        mic = self.sources[self.mic.get_selected()][0] if hasattr(self, 'mic') else self.config.get('microphone')
        if mic:
            cmd += ['--target', mic]
        cmd.append(str(self.test_wav))
        try:
            self.test_recorder = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.test_btn.set_label('停止并识别')
            self.test_result.set_text('● 正在录音… 说完一句话后点击「停止并识别」。')
        except Exception as exc:
            self.test_result.set_text(f'无法启动试说录音：{exc}')

    def _transcribe_test_wav(self, wav: Path) -> str:
        model_path = str(self._selected_model_path())
        device = self.devices[self.device.get_selected()][0]
        compute = 'int8' if device == 'cpu' else ('int8_float16' if self.compute.get_selected() == 1 else 'float16')
        job = dict(
            path=str(wav),
            language='zh' if self.language.get_selected() == 0 else 'auto',
            beam_size=self.beam.get_value_as_int(),
            hotwords=self.get_hotwords_text(),
            rime_dictionary=False,
            punctuation=self.punctuation.get_active(),
            learning=self.learning.get_active(),
            clean_fillers=self.clean_fillers.get_active(),
            context='',
        )
        sock_path = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / 'qingyin/model.sock'
        if self.resident.get_active() and sock_path.exists():
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(20)
                s.connect(str(sock_path))
                hello = dict(
                    model=model_path,
                    device=device,
                    compute=compute,
                    gpu_uuid=self.config.get('gpu_uuid', ''),
                    gpu_min_free_mib=self.config.get('gpu_min_free_mib', 6144),
                    idle_unload_seconds=self.idle_minutes.get_value_as_int() * 60,
                )
                s.sendall((json.dumps(hello) + '\n').encode())
                f = s.makefile('r', encoding='utf-8')
                ready = json.loads(f.readline())
                if not ready.get('ready'):
                    raise RuntimeError(ready.get('error', '模型未就绪'))
                s.sendall((json.dumps(job) + '\n').encode())
                reply = json.loads(f.readline())
                if 'error' in reply:
                    raise RuntimeError(reply['error'])
                return reply.get('text', '')
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.Popen(
            [str(root / '.venv/bin/python'), str(root / 'python/asr.py'), model_path, device, compute],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            ready = json.loads(proc.stdout.readline())
            if not ready.get('ready'):
                raise RuntimeError(ready.get('error', '模型加载失败'))
            proc.stdin.write(json.dumps(job, ensure_ascii=False) + '\n')
            proc.stdin.flush()
            reply = json.loads(proc.stdout.readline())
            if 'error' in reply:
                raise RuntimeError(reply['error'])
            return reply.get('text', '')
        finally:
            proc.kill()
            proc.wait(timeout=3)

    def _voice_test_done(self, text, ms, error):
        if self.closed:
            return False
        self.test_btn.set_sensitive(True)
        self.test_btn.set_label('开始试说')
        if error:
            self.test_result.set_text(f'试说失败：{error}')
        elif not text:
            self.test_result.set_text(f'未检测到有效语音（耗时 {ms} ms），请检查麦克风输入。')
        else:
            self.test_result.set_text(f'识别结果（{ms} ms）：{text}')
        return False

    def _installed_path_for(self, key):
        for idx, p in enumerate(self.models):
            if p.name == key and installed(p):
                return idx, p
        candidate = Path.home() / '.local/share/qingyin/models' / key
        if installed(candidate):
            return None, candidate
        return None, None

    def on_card_clicked(self, key):
        idx, _ = self._installed_path_for(key)
        if idx is not None:
            self.model.set_selected(idx)

    def on_model_action(self, key):
        idx, _ = self._installed_path_for(key)
        if idx is not None:
            self.model.set_selected(idx)
            return
        if key in self.catalog_names:
            self.catalog.set_selected(self.catalog_names.index(key))
        card_tuple = self.model_cards.get(key)
        btn = card_tuple[1] if card_tuple else self.whisper_buttons.get(key, self.download_button)
        bar = card_tuple[3] if card_tuple else self.download_bar
        self.run_download(key, MODEL_META.get(key, {}).get('title', key), btn, self.download_notice, bar,
                          lambda err, k=key, b=btn: self._card_download_done(k, b, err))

    def _card_download_done(self, key, btn, error):
        if self.closed:
            return False
        btn.set_sensitive(True)
        return self.download_finished(key, error)

    # --- Page 2: Performance & Hardware ---------------------------------
    def build_engine_page(self):
        page = self.make_page('engine', '性能与硬件', '管理常驻内存释放、实时预览与可选 GPU 加速参数。')

        # Memory & residency card
        mem_card = self.make_card(page, '内存与唤醒策略')
        self.resident = Gtk.Switch(active=self.config.get('resident_model', False))
        self.add_row(mem_card, '模型常驻加速', '首次录音加载后保持热态，后续语音约 0.2 秒出字', self.resident)

        self.idle_minutes = Gtk.SpinButton.new_with_range(0, 60, 1)
        cur_min = int(self.config.get('idle_unload_seconds', 300)) // 60
        self.idle_minutes.set_value(cur_min)
        seg = hbox(2)
        seg.add_css_class('seg-group')
        for mins, text in IDLE_PRESETS:
            b = Gtk.Button(label=text)
            b.add_css_class('seg')
            b.connect('clicked', lambda _, m=mins: self.set_idle_minutes(m))
            seg.append(b)
            self.idle_buttons[mins] = b
        self.sync_idle_pills(cur_min)
        self.add_row(mem_card, '空闲自动释放', '超过该时长未语音输入则自动卸载模型并退回 0 MB 内存', seg)

        self.auto_stop_ms = int(self.config.get('auto_stop_silence_ms', 0))
        auto_seg = hbox(2)
        auto_seg.add_css_class('seg-group')
        for ms, text in AUTO_STOP_PRESETS:
            b = Gtk.Button(label=text)
            b.add_css_class('seg')
            b.connect('clicked', lambda _, val=ms: self.set_auto_stop_ms(val))
            auto_seg.append(b)
            self.auto_stop_buttons[ms] = b
        self.sync_auto_stop_pills(self.auto_stop_ms)
        self.add_row(mem_card, '说完自动停录', '检测到说话结束并静音达到该时长时自动提交（无需再按第二次 Win+A）', auto_seg)

        self.precise_choices = [('', '自动（优先 Fun-ASR-Nano / Qwen3-ASR）')]
        for p in self.models:
            self.precise_choices.append((str(p), MODEL_META.get(p.name, {}).get('title', p.name)))
        self.precise_dd = Gtk.DropDown.new_from_strings([lbl for _, lbl in self.precise_choices])
        cur_precise = self.config.get('precise_model', '')
        self.precise_dd.set_selected(next((i for i, (v, _) in enumerate(self.precise_choices) if v == cur_precise), 0))
        self.add_row(mem_card, '高精语义备选模型（Win+Shift+A）', '单次按需运行高精度 LLM-ASR，用完即释且不驱逐常驻极速引擎', self.precise_dd)

        # Live preview card
        prev_card = self.make_card(page, '实时预览')
        self.preview = Gtk.Switch(active=self.config.get('live_preview', False))
        prev_badge = label('已装 X-ASR 流式' if live.is_xasr(live.xasr_model_dir()) else ('已装预览' if live.installed() else '未安装'),
                           'badge accent' if live.installed() else 'badge', wrap=False)
        self.add_row(
            prev_card,
            '边说边出字（fcitx5 行内预览）',
            '常驻模式零冷启；关闭可再省约 300 MB 内存（X-ASR 停录 ~0.2 秒即上屏）',
            self.preview,
            badge=prev_badge,
        )
        self.preview_button = self.ghost('下载 X-ASR 预览模型（约 134 MB）', self.download_preview)
        self.preview_notice = label('需要联网下载一次；识别完全离线。', 'muted')
        self.preview_bar = Gtk.ProgressBar()
        self.preview_bar.add_css_class('meter')
        self.preview_bar.set_visible(False)
        self.preview_box = self.add_block(prev_card, self.preview_button, self.preview_bar, self.preview_notice)
        self.preview_box.set_visible(not live.installed())

        # Compute & Whisper-specific card
        page.append(label('计算设备与 WHISPER 专项参数', 'section-head'))
        self.cpu_callout = label(
            'ⓘ 当前所选为纯 CPU 零显存引擎，下方显卡、量化精度与 Beam 参数仅在切换至 Whisper 模型时生效。',
            'callout',
        )
        page.append(self.cpu_callout)

        hw_card = self.make_card(page)
        self.devices = [('cpu', '', 'CPU · 本机处理器'), ('cuda', '', 'GPU · 自动选择最大显存')]
        if self.config.get('gpu_uuid'):
            self.devices.append(('cuda', self.config['gpu_uuid'], '已固定显卡 · 正在查询'))
        self.device = Gtk.DropDown.new_from_strings([item[2] for item in self.devices])
        self.device.set_hexpand(True)
        self.device.set_selected(0 if self.config['device'] == 'cpu' else (2 if self.config.get('gpu_uuid') else 1))
        self.device.connect('notify::selected', lambda *_: self.device_info())
        self.gpu_info = label('正在读取显卡状态…', 'muted')
        self.meter = Gtk.ProgressBar()
        self.meter.add_css_class('meter')
        self.meter.set_visible(False)
        refresh_btn = self.ghost('刷新设备', lambda _: self.refresh(), compact=True)
        dev_row = hbox(10)
        dev_row.append(self.device)
        dev_row.append(refresh_btn)
        self.minimum = max(6144, int(self.config.get('gpu_min_free_mib', 6144)))
        guard = label(f'显存保护：Whisper CUDA 加载前至少要求 {self.minimum / 1024:g} GiB 空闲显存。', 'muted')
        self.add_block(hw_card, dev_row, self.meter, self.gpu_info, guard)

        self.compute = Gtk.DropDown.new_from_strings(['FP16 · 标准精度', 'INT8 + FP16 · 降低显存占用'])
        self.compute.set_selected(1 if self.config.get('compute_type') == 'int8_float16' else 0)
        self.add_row(hw_card, 'Whisper GPU 精度', '仅对 Whisper GPU 模式生效；CPU 模式始终使用 INT8', self.compute)

        self.beam = Gtk.SpinButton.new_with_range(1, 10, 1)
        self.beam.set_value(self.config.get('beam_size', 5))
        self.add_row(hw_card, 'Whisper 解码 Beam', '1 更快，5 精度优先（仅 Whisper 生效）', self.beam)

    def set_idle_minutes(self, mins):
        self.idle_minutes.set_value(mins)
        self.sync_idle_pills(mins)

    def sync_idle_pills(self, mins):
        for m, btn in self.idle_buttons.items():
            if m == mins:
                btn.add_css_class('active')
            else:
                btn.remove_css_class('active')

    def set_auto_stop_ms(self, ms):
        if self.auto_stop_ms != ms:
            self.auto_stop_ms = ms
            self.sync_auto_stop_pills(ms)
            self.mark_dirty()
        else:
            self.sync_auto_stop_pills(ms)

    def sync_auto_stop_pills(self, ms):
        for val, btn in self.auto_stop_buttons.items():
            if val == ms:
                btn.add_css_class('active')
            else:
                btn.remove_css_class('active')

    # --- Page 3: Output & Vocabulary ------------------------------------
    def build_output_page(self):
        page = self.make_page('output', '文字与词库', '自定义输出排版、个人纠错词库与中英专有热词。')

        out_card = self.make_card(page, '文字输出')
        self.language = Gtk.DropDown.new_from_strings(['中文 / 中英混说', '自动识别语言'])
        self.language.set_selected(0 if self.config.get('language', 'zh') == 'zh' else 1)
        lang_seg = hbox(2)
        lang_seg.add_css_class('seg-group')
        for idx, text in ((0, '中英混说'), (1, '自动检测')):
            b = Gtk.Button(label=text)
            b.add_css_class('seg')
            b.connect('clicked', lambda _, i=idx: self.set_language(i))
            lang_seg.append(b)
            self.lang_buttons[idx] = b
        self.sync_lang_pills()
        self.add_row(out_card, '识别语言', '中文输出统一规范为简体，保留英文原词与大小写', lang_seg)

        self.punct_badge = label('原生内置', 'badge accent', wrap=False)
        self.punctuation = Gtk.Switch(active=self.config.get('punctuation', True))
        self.add_row(out_card, '自动补标点', '不自动分段、不追加结尾句号；支持原生标点的引擎零额外开销',
                     self.punctuation, badge=self.punct_badge)

        self.auto = Gtk.Switch(active=self.config.get('auto_input', True))
        self.add_row(out_card, '自动输入当前文本框', '通过原生 fcitx5 插件直出；关闭后可用 qingyin copy 复制', self.auto)

        self.clipboard_fb = Gtk.Switch(active=self.config.get('clipboard_fallback', True))
        self.add_row(out_card, '非输入法窗口自动复制', '遇到未连接 fcitx5 的特殊窗口自动复制到剪贴板（密码框始终跳过）', self.clipboard_fb)

        self.clean_fillers = Gtk.Switch(active=self.config.get('clean_fillers', False))
        self.add_row(out_card, '口语语气词清理', '自动去掉句首与句间停顿处的「呃、嗯、那个」等口癖词', self.clean_fillers)

        self.panel = Gtk.Switch(active=self.config.get('show_panel', False))
        self.add_row(out_card, '灵动岛状态浮窗', '录音与转写期间顶部浮现迷你黑曜石波形岛（绝不抢占输入框焦点）', self.panel)

        vocab_card = self.make_card(page, '词库与热词增强')
        total_rules, active_rules = data.learning_stats()
        learn_badge = label(f'{active_rules} 条生效 / 共 {total_rules} 条', 'badge', wrap=False)
        self.learning = Gtk.Switch(active=self.config.get('learning', True))
        self.add_row(vocab_card, '上下文与自动学习', '自动记住反复修正的短词对（密码框强制跳过）',
                     self.learning, badge=learn_badge)

        rime_ok = data.rime_installed()
        rime_badge = label('已索引本地词库' if rime_ok else '未下载', 'badge accent' if rime_ok else 'badge', wrap=False)
        self.rime = Gtk.Switch(active=self.config.get('rime_dictionary', True))
        self.add_row(vocab_card, '雾凇拼音上下文词库', '仅按输入框前文动态筛选最多 16 个词提示识别，不强制改字',
                     self.rime, badge=rime_badge)

        # Spacious multi-line hotwords editor with live pill counter
        hw_head = hbox(10)
        hw_head.append(label('自定义识别热词', 'row-title', wrap=False))
        self.hw_count = label(f"{count_hotwords(self.config.get('hotwords', ''))} 个词条", 'badge accent', wrap=False)
        hw_head.append(self.hw_count)
        hw_spacer = Gtk.Box()
        hw_spacer.set_hexpand(True)
        hw_head.append(hw_spacer)
        hw_head.append(self.ghost('管理个人词库', lambda _: subprocess.Popen([CLI, 'vocabulary']), compact=True))

        self.hotwords_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.hotwords_view.add_css_class('hotwords')
        self.hotwords_buf = self.hotwords_view.get_buffer()
        self.hotwords_buf.set_text(self.config.get('hotwords', ''))
        hw_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        hw_scroll.set_min_content_height(136)
        hw_scroll.set_max_content_height(200)
        hw_scroll.add_css_class('hotwords-wrap')
        hw_scroll.set_child(self.hotwords_view)
        self.add_block(
            vocab_card,
            hw_head,
            hw_scroll,
            label('逗号或换行分隔，靠前的词条优先级更高（支持中英文专有名词、项目名、软件名）。', 'muted'),
        )

    def set_language(self, idx):
        self.language.set_selected(idx)
        self.sync_lang_pills()

    def sync_lang_pills(self):
        sel = self.language.get_selected()
        for idx, btn in self.lang_buttons.items():
            if idx == sel:
                btn.add_css_class('active')
            else:
                btn.remove_css_class('active')

    def get_hotwords_text(self):
        return self.hotwords_buf.get_text(
            self.hotwords_buf.get_start_iter(),
            self.hotwords_buf.get_end_iter(),
            True,
        ).strip()

    def on_hotwords_changed(self, *_):
        self.hw_count.set_text(f'{count_hotwords(self.get_hotwords_text())} 个词条')
        self.mark_dirty()

    # --- Page 4: Audio & Shortcuts --------------------------------------
    def build_input_page(self):
        page = self.make_page('input', '音频与快捷键', '选择 PipeWire 录音源、查阅快捷键与本地隐私承诺。')

        mic_card = self.make_card(page, '音频输入设备')
        try:
            self.sources = data.microphones()
        except Exception:
            self.sources = [(None, '系统默认麦克风')]
        current = self.config.get('microphone')
        if current and not any(key == current for key, _ in self.sources):
            self.sources.append((current, '已选择麦克风 · 当前不可用'))
        self.mic = Gtk.DropDown.new_from_strings([name for _, name in self.sources])
        self.mic.set_hexpand(True)
        self.mic.set_selected(next(i for i, (key, _) in enumerate(self.sources) if key == current))
        mic_row = hbox(10)
        mic_row.append(self.mic)
        mic_row.append(self.ghost('刷新麦克风', self.refresh_microphones, compact=True))
        self.add_block(mic_card, mic_row, label('优先使用内置阵列或 USB 麦克风；蓝牙通话模式可能导致采样率下降。', 'muted'))
        self.sound_fb = Gtk.Switch(active=self.config.get('sound_feedback', True))
        self.add_row(mic_card, '轻量提示音反馈', '开始录音与停止转写时播放 35 ms 极轻清脆滴答声（不开浮窗也能确认状态）', self.sound_fb)

        kbd_card = self.make_card(page, '全局快捷键（niri）')
        shortcuts = [
            ('开始录音 / 停止并转写', '极速引擎瞬间上屏（约 0.2 秒）', ['Win', 'A']),
            ('高精语义模式（单次按需）', '调用 LLM-ASR 精准语义纠错，用完立刻释放内存', ['Win', 'Shift', 'A']),
            ('取消当前录音或转写', '立即丢弃录音并释放识别请求', ['Win', 'Alt', 'Esc']),
            ('纠正上一条结果', '快速修正错字并教给个人词库', ['Win', 'Alt', 'A']),
        ]
        for title_text, desc, keys in shortcuts:
            key_row = hbox(6)
            for k in keys:
                key_row.append(label(k, 'kbd', wrap=False))
            self.add_row(kbd_card, title_text, desc, key_row)

        page.append(label('隐私与安全边界', 'section-head'))
        pgrid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        manifesto = [
            ('100% 本地推理', '主服务与识别进程限制网络协议族，零云端上传'),
            ('录音即刻销毁', '转写结束或取消后立即删除内存盘临时录音'),
            ('密码框硬隔离', 'fcitx5 检测到密码 / 敏感字段自动拒绝注入与学习'),
            ('焦点令牌防误触', '识别期间切换窗口自动暂停上屏，结果保留待复制'),
        ]
        for idx, (t, d) in enumerate(manifesto):
            tile = vbox(4)
            tile.add_css_class('privacy-tile')
            tile.append(label(t, 'row-title', wrap=False))
            tile.append(label(d, 'muted'))
            pgrid.attach(tile, idx % 2, idx // 2, 1, 1)
        page.append(pgrid)

    def refresh_microphones(self, *_):
        selected_key = self.sources[self.mic.get_selected()][0]
        try:
            self.sources = data.microphones()
        except Exception:
            self.sources = [(None, '系统默认麦克风')]
        if selected_key and not any(k == selected_key for k, _ in self.sources):
            self.sources.append((selected_key, '已选择麦克风 · 当前不可用'))
        was = self.loading
        self.loading = True
        self.mic.set_model(Gtk.StringList.new([name for _, name in self.sources]))
        self.mic.set_selected(next((i for i, (k, _) in enumerate(self.sources) if k == selected_key), 0))
        self.loading = was

    # --- Live telemetry & memory release --------------------------------
    def poll_service_status(self):
        if self.closed:
            return GLib.SOURCE_REMOVE

        def work():
            st = data.service_status()
            GLib.idle_add(self.apply_service_status, st)

        threading.Thread(target=work, daemon=True).start()
        return GLib.SOURCE_CONTINUE

    def apply_service_status(self, st):
        if self.closed:
            return False
        self.service_warm = st['active']
        self.emblem.queue_draw()
        if st['active']:
            self.status_dot.add_css_class('warm')
            self.status_title.set_text('常驻引擎就绪')
            mem = f"{st['memory_mb']:.0f} MB" if st['memory_mb'] is not None else '运行中'
            self.status_metric.set_text(f'{mem} · 0 显存' if self._selected_is_cpu_engine() else f'{mem} · 活跃')
            self.bento_memory[1].set_text(mem)
            self.bento_memory[2].set_text('常驻热态 · 0 MB VRAM' if self._selected_is_cpu_engine() else '常驻热态')
            self.release_btn.set_visible(True)
        else:
            self.status_dot.remove_css_class('warm')
            self.status_title.set_text('已休眠归零')
            self.status_metric.set_text('0 MB · 按需唤醒')
            self.bento_memory[1].set_text('0 MB')
            self.bento_memory[2].set_text('0 MB VRAM · 空闲休眠')
            self.release_btn.set_visible(False)
        return False

    def release_memory(self, *_):
        self.release_btn.set_sensitive(False)

        def work():
            subprocess.run(['systemctl', '--user', 'stop', 'qingyin-model.service'],
                           capture_output=True, timeout=5)
            st = data.service_status()
            GLib.idle_add(self._after_release, st)

        threading.Thread(target=work, daemon=True).start()

    def _after_release(self, st):
        if self.closed:
            return False
        self.release_btn.set_sensitive(True)
        self.apply_service_status(st)
        self.say('已立即释放常驻模型内存 ✓', 'good')
        return False

    # --- Model selection & downloads ------------------------------------
    def _selected_model_path(self):
        idx = self.model.get_selected()
        return self.models[idx] if idx < len(self.models) else Path(self.config['model'])

    def _selected_is_cpu_engine(self):
        return sherpa_engine.detect_model(self._selected_model_path()) is not None

    def update_telemetry_cards(self):
        p = self._selected_model_path()
        spec = sherpa_engine.detect_model(p)
        meta = MODEL_META.get(p.name)
        self.bento_engine[1].set_text(meta['title'] if meta else p.name)
        if spec:
            self.bento_engine[2].set_text('纯 CPU · 0 显存 · 原生标点' if spec['native_punctuation'] else '纯 CPU · 0 显存')
        else:
            dev = self.devices[self.device.get_selected()][0] if self.devices else 'cpu'
            self.bento_engine[2].set_text('Whisper · GPU 加速' if dev == 'cuda' else 'Whisper · CPU INT8')

        if self.resident.get_active():
            mins = self.idle_minutes.get_value_as_int()
            self.bento_policy[1].set_text(f'常驻 · {mins} 分钟归零' if mins else '永久常驻')
        else:
            self.bento_policy[1].set_text('按需启动')
        hw_n = count_hotwords(self.get_hotwords_text()) if hasattr(self, 'hotwords_buf') else 0
        prev_txt = '流式预览开' if self.preview.get_active() else '无预览省内存'
        self.bento_policy[2].set_text(f'{hw_n} 热词 · {prev_txt}')

    def sync_model_ui(self):
        p = self._selected_model_path()
        cur_name = p.name
        spec = sherpa_engine.detect_model(p)

        # Update modern 2-col cards
        models_root = (Path.home() / '.local/share/qingyin/models').resolve()
        for key, (card, btn, del_btn, _bar) in self.model_cards.items():
            idx, mpath = self._installed_path_for(key)
            is_sel = key == cur_name
            can_del = (not is_sel) and mpath is not None and mpath.resolve().parent == models_root
            del_btn.set_visible(can_del)
            if is_sel:
                card.add_css_class('selected')
                btn.add_css_class('selected')
                btn.set_label('✓ 已选用')
            else:
                card.remove_css_class('selected')
                btn.remove_css_class('selected')
                btn.set_label('选用' if idx is not None else f"下载 · {MODEL_META[key]['size']}")

        # Update whisper rows
        installed_whispers = 0
        for key, btn in self.whisper_buttons.items():
            idx, _ = self._installed_path_for(key)
            if idx is not None:
                installed_whispers += 1
            if key == cur_name:
                btn.add_css_class('selected')
                btn.set_label('✓ 已选用')
            else:
                btn.remove_css_class('selected')
                btn.set_label('选用' if idx is not None else f"下载 · {MODEL_META[key]['size']}")
        self.whisper_expander.set_label(f'Whisper 经典模型（已安装 {installed_whispers} 个 · 可选 GPU 加速）')

        # Update path info & adaptive hints
        if not installed(p):
            note = '模型文件缺失，请重新安装'
        elif spec:
            notes = {
                'transducer': 'X-ASR 极速引擎 · 纯 CPU 0 显存 · 自带标点 · 支持热词与雾凇词库',
                'funasr-nano': 'Fun-ASR-Nano LLM 引擎 · 纯 CPU 0 显存 · 自带标点 · 支持热词与上下文',
                'qwen3-asr': 'Qwen3-ASR LLM 引擎 · 纯 CPU 0 显存 · 自带标点 · 支持热词',
                'sense-voice': 'SenseVoice 引擎 · 纯 CPU 0 显存 · 自带标点 · 个人纠错生效',
                'fire-red-asr-ctc': 'FireRedASR2 CTC 引擎 · 纯 CPU 0 显存 · 个人纠错生效',
                'fire-red-asr': 'FireRedASR2 AED 引擎 · 纯 CPU 0 显存 · 个人纠错生效',
                'paraformer': 'Paraformer 仅用 CPU 识别；手填热词不生效，个人纠错仍生效',
            }
            note = notes.get(spec['kind'], '')
        else:
            note = 'Whisper 模型 · 可在「性能与硬件」配置 GPU 与解码精度'
        self.model_info.set_text(f'{p}\n{note}')

        if hasattr(self, 'cpu_callout'):
            self.cpu_callout.set_visible(spec is not None)
        if hasattr(self, 'punct_badge'):
            if spec and spec.get('native_punctuation'):
                self.punct_badge.set_text('当前引擎原生自带标点')
                self.punct_badge.add_css_class('accent')
            else:
                self.punct_badge.set_text('独立 CPU 标点')
                self.punct_badge.remove_css_class('accent')
        if hasattr(self, 'resident'):
            self.update_telemetry_cards()

    # Keep legacy alias
    update_model = sync_model_ui

    def run_download(self, key, label_text, button, notice, bar, finished):
        """Run download_model.py, streaming its PROGRESS lines into a smooth progress bar."""
        button.set_sensitive(False)
        bar.set_fraction(0)
        bar.set_visible(True)
        notice.set_text('正在连接下载源… ' + label_text)

        def work():
            try:
                root = Path(__file__).resolve().parents[1]
                proc = subprocess.Popen(
                    [str(root / '.venv/bin/python'), str(root / 'download_model.py'), key],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                reason = ''
                for line in proc.stdout:
                    if line.startswith('下载失败'):
                        reason = line.strip()[:140]
                    if line.startswith('PROGRESS '):
                        try:
                            _, done, total = line.split()
                            GLib.idle_add(self.download_progress, bar, notice, label_text, int(done), int(total))
                        except ValueError:
                            pass
                error = '' if proc.wait() == 0 else (reason or '下载失败，请检查网络或磁盘空间后重试') + '；已下载部分已保留，再点一次继续'
            except Exception:
                error = '无法启动下载程序，请检查安装环境'
            GLib.idle_add(self.download_done, bar, finished, error)

        threading.Thread(target=work, daemon=True).start()

    def download_progress(self, bar, notice, label_text, done, total):
        if self.closed or not total:
            return False
        animate(bar, min(1.0, done / total), 240)
        notice.set_text(f'正在下载 {label_text}… {done * 100 // total}% · {done / 1e6:.0f} / {total / 1e6:.0f} MB')
        return False

    def download_done(self, bar, finished, error):
        if self.closed:
            return False
        bar.set_visible(False)
        return finished(error)

    def download_model(self, *_):
        name = self.catalog_names[self.catalog.get_selected()]
        self.run_download(
            name,
            name,
            self.download_button,
            self.download_notice,
            self.download_bar,
            lambda error: self.download_finished(name, error),
        )

    def download_finished(self, name, error):
        if self.closed:
            return False
        self.download_button.set_sensitive(True)
        if error:
            self.download_notice.set_text(error)
            return False
        previous = str(self.models[self.model.get_selected()])
        self.models = data.models(self.config)
        was = self.loading
        self.loading = True
        self.model.set_model(Gtk.StringList.new([p.name + ' · ' + MODELS.get(p.name, ('', '自定义模型'))[1] for p in self.models]))
        self.model.set_selected(next((i for i, p in enumerate(self.models) if str(p) == previous), 0))
        self.loading = was
        self.download_notice.set_text(name + ' 已安装；点选对应卡片并保存即可使用')
        self.sync_model_ui()
        return False

    def download_preview(self, *_):
        self.run_download(
            'x-asr-preview',
            'X-ASR 实时预览模型',
            self.preview_button,
            self.preview_notice,
            self.preview_bar,
            self.preview_finished,
        )

    def preview_finished(self, error):
        if self.closed:
            return False
        self.preview_button.set_sensitive(True)
        if error:
            self.preview_notice.set_text(error)
        else:
            self.preview_box.set_visible(False)
        return False

    # --- GPU discovery --------------------------------------------------
    def refresh(self):
        selected = self.devices[self.device.get_selected()][:2]

        def work():
            try:
                cards, error = data.graphics(), ''
            except Exception:
                cards, error = [], '无法读取 NVIDIA 设备；CPU 零显存引擎不受影响'
            GLib.idle_add(self.apply_devices, selected, cards, error)

        threading.Thread(target=work, daemon=True).start()

    def apply_devices(self, selected, cards, error):
        if self.closed:
            return False
        selected = self.devices[self.device.get_selected()][:2]
        self.cards = cards
        self.gpu_error = error
        self.devices = [('cpu', '', 'CPU · 本机处理器（0 显存）'), ('cuda', '', 'GPU · 自动选择最大显存')]
        for gpu in cards:
            self.devices.append((
                'cuda',
                gpu['uuid'],
                f"{gpu['name'].removeprefix('NVIDIA GeForce ')} · {gpu['total'] / 1024:.0f} GB",
            ))
        if selected[0] == 'cuda' and selected[1] and not any(g['uuid'] == selected[1] for g in cards):
            self.devices.append(('cuda', selected[1], '已选择显卡 · 当前不可用'))
        was = self.loading
        self.loading = True
        self.device.set_model(Gtk.StringList.new([d[2] for d in self.devices]))
        self.device.set_selected(next(i for i, d in enumerate(self.devices) if d[:2] == selected))
        self.loading = was
        self.device_info()
        return False

    def device_info(self):
        index = self.device.get_selected()
        if index >= len(self.devices):
            return
        device, uuid, _ = self.devices[index]
        gpu = None
        if device == 'cpu':
            text = 'CPU 模式不占显存，推荐搭配 X-ASR / Fun-ASR-Nano / Qwen3-ASR。'
        else:
            gpu = (
                next((g for g in self.cards if g['uuid'] == uuid), None)
                if uuid
                else max(self.cards, key=lambda g: g['total'], default=None)
            )
            text = (
                f"空闲 {gpu['free'] / 1024:.1f} / 总计 {gpu['total'] / 1024:.1f} GiB · "
                + ('余量充足' if gpu['free'] >= getattr(self, 'minimum', 6144) else '显存余量不足，Whisper GPU 模式将拒绝加载')
                if gpu
                else getattr(self, 'gpu_error', '正在查询显卡…') or '指定显卡不可用'
            )
        self.gpu_info.set_text(text)
        self.meter.set_visible(gpu is not None)
        if gpu:
            if gpu['free'] < getattr(self, 'minimum', 6144):
                self.meter.add_css_class('low')
            else:
                self.meter.remove_css_class('low')
            animate(self.meter, gpu['free'] / max(1, gpu['total']))
        self.update_telemetry_cards()

    # --- Save -----------------------------------------------------------
    def save(self, *_):
        try:
            state = json.loads(subprocess.check_output([CLI, 'status'], timeout=2))
            if state.get('running') and state['phase'] in ('recording', 'transcribing'):
                self.say('请先停止或取消录音 / 转写', 'warning')
                return
            device, uuid, _ = self.devices[self.device.get_selected()]
            model = self.models[self.model.get_selected()]
            if not installed(model):
                raise ValueError('模型文件不存在，无法保存')
            if device == 'cuda' and uuid and not any(g['uuid'] == uuid for g in self.cards):
                raise ValueError('指定显卡当前不可用，请刷新或选择 CPU')
            stopped = subprocess.run(['systemctl', '--user', 'stop', 'qingyin-model.service'],
                                     capture_output=True, timeout=5)
            if stopped.returncode:
                raise ValueError('无法释放常驻模型，请重试；设置未保存')
            self.config = data.save(
                CONFIG,
                dict(
                    resident_model=self.resident.get_active(),
                    idle_unload_seconds=self.idle_minutes.get_value_as_int() * 60,
                    auto_stop_silence_ms=self.auto_stop_ms,
                    precise_model=self.precise_choices[self.precise_dd.get_selected()][0],
                    device=device,
                    gpu_uuid=uuid,
                    model=str(model),
                    compute_type='int8_float16' if self.compute.get_selected() == 1 else 'float16',
                    beam_size=self.beam.get_value_as_int(),
                    language='zh' if self.language.get_selected() == 0 else 'auto',
                    rime_dictionary=self.rime.get_active(),
                    punctuation=self.punctuation.get_active(),
                    learning=self.learning.get_active(),
                    auto_input=self.auto.get_active(),
                    clipboard_fallback=self.clipboard_fb.get_active(),
                    clean_fillers=self.clean_fillers.get_active(),
                    sound_feedback=self.sound_fb.get_active(),
                    show_panel=self.panel.get_active(),
                    live_preview=self.preview.get_active(),
                    microphone=self.sources[self.mic.get_selected()][0],
                    hotwords=self.get_hotwords_text(),
                ),
            )
            self.dirty = False
            self.say('已保存 ✓ 下次录音生效', 'good')
            self.poll_service_status()
        except Exception as exc:
            self.say('保存失败：' + str(exc), 'warning')


if __name__ == '__main__':
    Settings().run([])
