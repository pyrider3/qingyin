"""Deterministic, offline Simplified Chinese output; English stays unchanged."""
from opencc import OpenCC
_converter = OpenCC('t2s')

def simplified(text: str) -> str:
    return _converter.convert(text)


def without_final_period(text: str) -> str:
    """Omit the final Chinese full stop, preserving other punctuation and spacing."""
    content = text.rstrip()
    if content.endswith('。'):
        return content[:-1] + text[len(content):]
    return text
