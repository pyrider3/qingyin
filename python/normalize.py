"""Deterministic, offline Simplified Chinese output; English stays unchanged."""
import re
from opencc import OpenCC
_converter = OpenCC('t2s')
_CJK_PUNCT = r'[，。？！；：、]'


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


def without_final_period(text: str) -> str:
    """Omit the final Chinese full stop, preserving other punctuation and spacing."""
    content = text.rstrip()
    if content.endswith('。'):
        return content[:-1] + text[len(content):]
    return text
