"""Zero-dependency offline Mandarin/ASCII phonetic similarity using Rime Ice character readings."""
import difflib
import os
from pathlib import Path
import re

_CACHE = None
_CJK_RE = re.compile(r'^[\u4e00-\u9fff]+$')


def _rime_dir() -> Path:
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'qingyin/dictionaries/rime-ice'


def _load_pinyin_map() -> dict[str, set[str]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    mapping: dict[str, set[str]] = {}
    root = _rime_dir()
    for fname in ('8105.dict.yaml', '41448.dict.yaml'):
        path = root / fname
        if not path.is_file():
            continue
        in_body = False
        try:
            with path.open('r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if not in_body:
                        if line.startswith('...'):
                            in_body = True
                        continue
                    if not line or line[0] in '# \t\r\n':
                        continue
                    parts = line.split('\t')
                    if len(parts) >= 2 and len(parts[0]) == 1:
                        ch = parts[0]
                        py = parts[1].strip().lower()
                        if py and py.isalpha():
                            mapping.setdefault(ch, set()).add(py)
        except OSError:
            pass
        if fname == '8105.dict.yaml' and len(mapping) >= 4000:
            break
    _CACHE = mapping
    return mapping


def _fuzzy(py: str) -> str:
    """Collapse common Mandarin ASR phonetic confusions (retroflex, nasals, n/l)."""
    if py.startswith(('zh', 'ch', 'sh')):
        py = py[0] + py[2:]
    if py.startswith('l'):
        py = 'n' + py[1:]
    if py.endswith(('ing', 'eng', 'ang')):
        py = py[:-1]
    return py.replace('v', 'u')


_SOFT_PAIRS = ({'f', 'h'}, {'r', 'n'}, {'g', 'k'}, {'d', 't'}, {'b', 'p'}, {'j', 'q'}, {'z', 'c'})


def _syllable_similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    fa, fb = _fuzzy(a), _fuzzy(b)
    if fa == fb:
        return 0.92
    # Handle common Mandarin consonant aspiration / accent pairs with matching rimes.
    if len(fa) >= 2 and len(fb) >= 2 and fa[1:] == fb[1:] and {fa[0], fb[0]} in _SOFT_PAIRS:
        return 0.85
    ratio = difflib.SequenceMatcher(None, fa, fb).ratio()
    if fa[0] == fb[0]:
        ratio = max(ratio, 0.62)
    return ratio


def _char_similarity(c1: str, c2: str, pmap: dict[str, set[str]]) -> float:
    if c1 == c2:
        return 1.0
    p1 = pmap.get(c1)
    p2 = pmap.get(c2)
    if not p1 or not p2:
        return 0.6  # Unknown rare char: do not harshly reject.
    return max(_syllable_similarity(a, b) for a in p1 for b in p2)


def is_phonetic_match(source: str, target: str) -> bool:
    """Return True if target is a plausible phonetic ASR correction of source (not a semantic rewrite)."""
    s = source.strip()
    t = target.strip()
    if not s or not t or s == t:
        return False

    # Cross-script transliteration (e.g., 诺克塔利亚 -> Noctalia) is always plausible.
    s_ascii = s.isascii()
    t_ascii = t.isascii()
    if s_ascii != t_ascii:
        return len(s) <= 16 and len(t) <= 24

    # Pure ASCII word corrections (e.g., neovim -> Neovim, Club -> Claw).
    if s_ascii and t_ascii:
        sl, tl = s.casefold(), t.casefold()
        if sl == tl:
            return True
        if abs(len(sl) - len(tl)) > max(3, min(len(sl), len(tl))):
            return False
        ratio = difflib.SequenceMatcher(None, sl, tl).ratio()
        return ratio >= 0.45 or (sl[0] == tl[0] and ratio >= 0.35)

    # Pure CJK phrases: check length consistency and syllable-level phonetic similarity.
    if not (_CJK_RE.match(s) and _CJK_RE.match(t)):
        return abs(len(s) - len(t)) <= 2

    pmap = _load_pinyin_map()
    if not pmap:
        # No Rime pinyin dictionary installed (e.g. minimal CI environment): fail open conservatively.
        return abs(len(s) - len(t)) <= 1

    if abs(len(s) - len(t)) > 1:
        return False

    if len(s) == len(t):
        scores = [_char_similarity(a, b, pmap) for a, b in zip(s, t)]
        changed = [sc for a, b, sc in zip(s, t, scores) if a != b]
        if not changed:
            return False
        has_shared = len(changed) < len(s)
        avg_changed = sum(changed) / len(changed)
        if has_shared:
            return avg_changed >= 0.50
        return avg_changed >= 0.56 and max(changed) >= 0.65

    # Length differs by 1 (e.g. merged/split syllable): align shorter against longer strictly.
    short, long_ = (s, t) if len(s) < len(t) else (t, s)
    if len(short) < 2:
        return False
    best = 0.0
    for skip in range(len(long_)):
        aligned = long_[:skip] + long_[skip + 1:]
        avg = sum(_char_similarity(a, b, pmap) for a, b in zip(short, aligned)) / len(short)
        best = max(best, avg)
    return best >= 0.80


def reset_cache():
    global _CACHE
    _CACHE = None
