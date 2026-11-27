"""Obsidian Studio correction editor and locally learned vocabulary manager."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gtk

import learning
import phonetics
import settings_data

cli = str(Path.home() / '.local/bin/qingyin')
state_path = Path(os.environ['XDG_RUNTIME_DIR']) / 'qingyin/state.json'
config_path = Path.home() / '.config/qingyin/config.json'

CSS = b"""
window.qe {
    background-color: #101115;
    color: #f2f4f8;
    font-family: "Source Han Sans CN", "Noto Sans CJK SC", "Adwaita Sans", sans-serif;
}
window.qe headerbar {
    background: #101115;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    box-shadow: none;
}
.title-lg { font-size: 20px; font-weight: 800; color: #f2f4f8; }
.muted { font-size: 12px; color: #96a0b0; }
.card {
    background: #181a20;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 13px;
    padding: 12px 14px;
}
.rule-row {
    background: #181a20;
    border: 1px solid rgba(255, 255, 255, 0.065);
    border-radius: 12px;
    padding: 10px 14px;
}
.rule-row.active-rule {
    border-color: rgba(52, 211, 153, 0.34);
    background: rgba(52, 211, 153, 0.06);
}
.rule-pair { font-size: 14px; font-weight: 700; color: #f2f4f8; }
.badge {
    font-size: 10.5px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.07);
    color: #96a0b0;
}
.badge.good { background: rgba(52, 211, 153, 0.16); color: #6ee7b7; }
.badge.amber { background: rgba(245, 158, 11, 0.16); color: #fcd34d; }
.editor-wrap {
    background: rgba(0, 0, 0, 0.30);
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 12px;
    padding: 10px 12px;
}
.editor-wrap:focus-within { border-color: rgba(52, 211, 153, 0.55); }
textview.edit, textview.edit text {
    background: transparent;
    color: #f2f4f8;
    font-size: 14px;
}
button.ghost {
    background: rgba(255, 255, 255, 0.05);
    color: #e6ecf5;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 9px;
    box-shadow: none;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
}
button.ghost:hover { background: rgba(255, 255, 255, 0.10); }
button.compact { padding: 4px 10px; font-size: 11.5px; border-radius: 8px; }
button.danger { color: #fca5a5; border-color: rgba(248, 113, 113, 0.25); }
button.danger:hover { background: rgba(248, 113, 113, 0.14); }
button.primary {
    background: #34d399;
    color: #052e1e;
    border: none;
    border-radius: 10px;
    font-weight: 800;
    font-size: 13px;
    padding: 8px 18px;
}
button.primary:hover { background: #6ee7b7; }
.notice { font-size: 12.5px; color: #6ee7b7; font-weight: 600; }
"""


def _lbl(text, cls=None, xalign=0, wrap=True):
    w = Gtk.Label(label=text, xalign=xalign, wrap=wrap)
    if cls:
        for c in cls.split():
            w.add_css_class(c)
    return w


class Editor(Gtk.Application):
    def __init__(self):
        self.manage = '--vocabulary' in sys.argv
        super().__init__(application_id='dev.qingyin.Vocabulary' if self.manage else 'dev.qingyin.Editor')

    def do_activate(self):
        if self.get_active_window():
            self.get_active_window().present()
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.window = Gtk.ApplicationWindow(
            application=self,
            title='青音 · 个人词库' if self.manage else '青音 · 纠正结果',
        )
        self.window.add_css_class('qe')
        self.window.set_default_size(700, 560 if self.manage else 480)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{side}')(22)

        self.notice = _lbl('', 'notice')

        if self.manage:
            head = Gtk.Box(spacing=10)
            title_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            title_col.set_hexpand(True)
            title_col.append(_lbl('个人纠错词库', 'title-lg', wrap=False))
            self.summary = _lbl('只保存短词纠错对与确认次数，不保存整段录音或对话。', 'muted')
            title_col.append(self.summary)
            head.append(title_col)

            prune_btn = Gtk.Button(label='清理非同音噪声')
            prune_btn.add_css_class('ghost')
            prune_btn.set_valign(Gtk.Align.CENTER)
            prune_btn.connect('clicked', self.prune_noise)
            head.append(prune_btn)

            clear_btn = Gtk.Button(label='清空全部')
            clear_btn.add_css_class('ghost')
            clear_btn.add_css_class('danger')
            clear_btn.set_valign(Gtk.Align.CENTER)
            clear_btn.connect('clicked', self.confirm_clear)
            head.append(clear_btn)
            box.append(head)

            scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
            self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            scroll.set_child(self.rows)
            box.append(scroll)
            self.refresh()
        else:
            box.append(_lbl('纠正上一条识别结果', 'title-lg'))
            box.append(_lbl('直接修改错字，自动提取短词纠错对；勾选立即生效可跳过 3 次确认等待。', 'muted'))
            try:
                self.snapshot = json.loads(state_path.read_text())
            except (OSError, ValueError):
                self.snapshot = {}
            self.original = self.snapshot.get('text', '')

            scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroll.add_css_class('editor-wrap')
            self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
            self.text.add_css_class('edit')
            self.text.get_buffer().set_text(self.original)
            scroll.set_child(self.text)
            box.append(scroll)

            choices_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            choices_card.add_css_class('card')
            self.choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            choices_card.append(self.choices)
            box.append(choices_card)

            self.text.get_buffer().connect('changed', self.preview)
            self.preview()

            actions = Gtk.Box(spacing=12)
            self.promote_check = Gtk.CheckButton(label='保存并立即生效（自动替换同类错字）', active=False)
            self.promote_check.set_hexpand(True)
            save = Gtk.Button(label='保存纠正并复制')
            save.add_css_class('primary')
            save.connect('clicked', self.save)
            save.set_sensitive(bool(self.original))
            actions.append(self.promote_check)
            actions.append(save)
            box.append(actions)
            if not self.original:
                self.notice.set_text('没有可纠正的结果，请先按 Win+A 完成一次录音。')

        box.append(self.notice)
        self.window.set_child(box)
        self.window.present()

    def edited(self):
        buf = self.text.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)

    def preview(self, *_):
        child = self.choices.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.choices.remove(child)
            child = next_child
        self.selected = []
        for source, target in learning.propose(self.original, self.edited()):
            check = Gtk.CheckButton(label=f'学习：{source} → {target}', active=True)
            self.choices.append(check)
            self.selected.append((check, source, target))
        if not self.selected:
            self.choices.append(_lbl('只学习短词纠正；改标点或大段改写不会加入词库。', 'muted'))

    def save(self, *_):
        try:
            current = json.loads(state_path.read_text())
            if current.get('started') != self.snapshot.get('started') or current.get('phase') != 'result':
                self.notice.set_text('已产生新的录音结果，请关闭后重新打开，避免混淆纠正。')
                return
            enabled = json.loads(config_path.read_text()).get('learning', True)
            pairs = [(s, t) for check, s, t in self.selected if check.get_active()]
            promote_now = bool(getattr(self, 'promote_check', None) and self.promote_check.get_active())
            n = learning.record(pairs, str(self.snapshot.get('started')), None, promote_now=promote_now) if enabled and pairs else 0
            corrected = self.edited()
            current['text'] = corrected
            current['message'] = '纠正已保存，可复制后粘贴'
            tmp = state_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(current, ensure_ascii=False))
            tmp.replace(state_path)
            subprocess.run([cli, 'copy'], check=True, capture_output=True)
            suffix = '（已立即生效）' if promote_now and n else ''
            self.notice.set_text(f'已复制；确认了 {n} 条词语纠正{suffix}。' if enabled else '已复制；自动学习已关闭。')
        except Exception as exc:
            self.notice.set_text(f'保存失败：{exc}')

    def refresh(self):
        child = self.rows.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.rows.remove(child)
            child = nxt
        data = learning.load()
        active_ids = {r['id'] for r in learning.active_rules(data)}
        total = len(data['rules'])
        if hasattr(self, 'summary'):
            self.summary.set_text(
                f'已生效 {len(active_ids)} 条 · 候选 {total - len(active_ids)} 条 · 容量 {total} / {learning.LIMIT}'
            )
        if not data['rules']:
            self.rows.append(_lbl('还没有学习记录。纠正结果后会在这里出现。', 'muted'))
            return
        ranked = sorted(data['rules'], key=lambda r: (r['id'] in active_ids, r.get('count', 0)), reverse=True)
        for row in ranked:
            is_active = row['id'] in active_ids
            phonetic_ok = phonetics.is_phonetic_match(row['source'], row['target'])
            line = Gtk.Box(spacing=10)
            line.add_css_class('rule-row')
            if is_active:
                line.add_css_class('active-rule')

            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            info.set_hexpand(True)
            top_line = Gtk.Box(spacing=8)
            top_line.append(_lbl(f"{row['source']}  →  {row['target']}", 'rule-pair', wrap=False))
            status_badge = _lbl(
                '✓ 自动生效' if is_active else f"候选 {row['count']}/{learning.THRESHOLD}",
                'badge good' if is_active else 'badge',
                wrap=False,
            )
            top_line.append(status_badge)
            if not phonetic_ok and not is_active:
                top_line.append(_lbl('疑似改写', 'badge amber', wrap=False))
            info.append(top_line)
            line.append(info)

            if not is_active:
                promote_btn = Gtk.Button(label='立即生效')
                promote_btn.add_css_class('ghost')
                promote_btn.add_css_class('compact')
                promote_btn.set_valign(Gtk.Align.CENTER)
                promote_btn.connect('clicked', lambda _, rid=row['id']: self.promote(rid))
                line.append(promote_btn)

            hw_btn = Gtk.Button(label='+ 热词')
            hw_btn.add_css_class('ghost')
            hw_btn.add_css_class('compact')
            hw_btn.set_valign(Gtk.Align.CENTER)
            hw_btn.connect('clicked', lambda _, word=row['target']: self.add_hotword(word))
            line.append(hw_btn)

            del_btn = Gtk.Button(label='删除')
            del_btn.add_css_class('ghost')
            del_btn.add_css_class('compact')
            del_btn.add_css_class('danger')
            del_btn.set_valign(Gtk.Align.CENTER)
            del_btn.connect('clicked', lambda _, rid=row['id']: self.remove(rid))
            line.append(del_btn)
            self.rows.append(line)

    def promote(self, rule_id):
        learning.promote(rule_id)
        self.notice.set_text('已升格为自动生效规则 ✓')
        self.refresh()

    def add_hotword(self, word):
        try:
            cfg = json.loads(config_path.read_text())
            existing = [w.strip() for w in re.split(r'[,，;\n]+', cfg.get('hotwords', '')) if w.strip()]
            if any(w.casefold() == word.casefold() for w in existing):
                self.notice.set_text(f'「{word}」已在热词列表中')
                return
            existing.insert(0, word)
            settings_data.save(config_path, {'hotwords': ', '.join(existing)})
            self.notice.set_text(f'已将「{word}」加入识别热词 ✓ 下次录音生效')
        except Exception as exc:
            self.notice.set_text(f'加入热词失败：{exc}')

    def prune_noise(self, *_):
        removed = learning.prune_noise()
        self.notice.set_text(f'已清理 {removed} 条非同音改写噪声 ✓' if removed else '当前没有可清理的非同音噪声')
        self.refresh()

    def remove(self, rule_id):
        learning.delete(rule_id)
        self.refresh()

    def confirm_clear(self, *_):
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text='清空全部学习记录？',
        )

        def response(d, r):
            if r == Gtk.ResponseType.OK:
                learning.delete()
                self.notice.set_text('已清空全部学习记录')
                self.refresh()
            d.destroy()

        dialog.connect('response', response)
        dialog.present()


if __name__ == '__main__':
    Editor().run([])
