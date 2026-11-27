"""Deterministic, offline Simplified Chinese output; English stays unchanged."""
import re
from opencc import OpenCC
_converter = OpenCC('t2s')
_CJK_PUNCT = r'[，。？！；：、]'
_DIGIT_ZH = {
    '0': '(?:0|零|〇)',
    '1': '(?:1|一|幺)',
    '2': '(?:2|二|两)',
    '3': '(?:3|三)',
    '4': '(?:4|四)',
    '5': '(?:5|五)',
    '6': '(?:6|六)',
    '7': '(?:7|七)',
    '8': '(?:8|八)',
    '9': '(?:9|九)',
}
_FILLER_LEAD = re.compile(r'^(?:(?:呃|嗯|那个)[，,、\s]+|(?:就是说|怎么说呢)[，,、\s]*)+')
_FILLER_MID = re.compile(r'([，。？！；：])(?:呃|嗯|那个|就是说|怎么说呢|然后那个)[，,、\s]+')


def simplified(text: str) -> str:
    return _converter.convert(text)


def clean_spacing(text: str) -> str:
    """Trim stray spaces around full-width CJK punctuation while preserving English spacing."""
    if not text:
        return text
    text = re.sub(rf'[ \t]+({_CJK_PUNCT})', r'\1', text)
    text = re.sub(rf'({_CJK_PUNCT})[ \t]+', r'\1', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


def clean_fillers(text: str) -> str:
    """Remove standalone spoken hesitation particles without altering meaningful words."""
    if not text:
        return text
    text = _FILLER_LEAD.sub('', text)
    text = _FILLER_MID.sub(r'\1', text)
    return text.strip()


def apply_alnum_hotwords(text: str, phrases) -> str:
    """Normalize digit-bearing hotwords (e.g. fcitx5, RTX 5080, large-v3-turbo) after ASR."""
    if not text or not phrases:
        return text
    for raw in phrases:
        term = raw.strip()
        if not term or not term.isascii():
            continue
        if not (any(c.isalpha() for c in term) and any(c.isdigit() for c in term)):
            continue
        # Build a flexible regex matching spaced/hyphenated/Chinese-numeral spoken forms.
        pieces = []
        i = 0
        while i < len(term):
            ch = term[i]
            if ch.isalpha():
                j = i
                while j < len(term) and term[j].isalpha():
                    j += 1
                pieces.append(re.escape(term[i:j]))
                i = j
            elif ch.isdigit():
                pieces.append(_DIGIT_ZH[ch])
                i += 1
            elif ch in ' -_':
                i += 1
            else:
                pieces.append(re.escape(ch))
                i += 1
        if len(pieces) < 2:
            continue
        pattern = r'(?<![A-Za-z0-9_])' + r'[\s\-]*'.join(pieces) + r'(?![A-Za-z0-9_])'
        text = re.sub(pattern, term, text, flags=re.IGNORECASE)
    return text


def without_final_period(text: str) -> str:
    """Omit the final Chinese full stop, preserving other punctuation and spacing."""
    content = text.rstrip()
    if content.endswith('。'):
        return content[:-1] + text[len(content):]
    return text
