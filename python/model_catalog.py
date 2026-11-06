"""Installable models: multilingual Whisper (.en variants excluded) and offline Paraformer."""
from pathlib import Path

MODELS = {
    'tiny': ('Systran/faster-whisper-tiny', '极轻量 · 速度最快，精度较低'),
    'base': ('Systran/faster-whisper-base', '轻量 · 适合简单短句'),
    'small': ('Systran/faster-whisper-small', '低显存 · 推荐先试'),
    'medium': ('Systran/faster-whisper-medium', '中等大小 · 精度与占用折中'),
    'large-v3-turbo': ('mobiuslabsgmbh/faster-whisper-large-v3-turbo', '大模型加速版'),
    'large-v3': ('Systran/faster-whisper-large-v3', '完整大模型 · 精度优先'),
    'paraformer-zh': ('sherpa:paraformer-zh-int8-2025-10-07', '普通话专用 · 仅 CPU · 不支持热词'),
}


def installed(path):
    path = Path(path)
    return (path/'model.bin').is_file() or ((path/'model.int8.onnx').is_file() and (path/'tokens.txt').is_file())
