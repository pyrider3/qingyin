"""Deterministic, offline Simplified Chinese output; English stays unchanged."""
from opencc import OpenCC
_converter = OpenCC('t2s')

def simplified(text: str) -> str:
    return _converter.convert(text)
