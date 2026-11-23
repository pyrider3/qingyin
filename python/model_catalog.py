"""Installable models: 2026 sherpa-onnx CPU engines and multilingual Whisper."""
from pathlib import Path
import sherpa_engine

MODELS = {
    'x-asr-zh-en': ('sherpa:x-asr-zipformer-transducer-zh-en-punct-int8-2026-06-03', '推荐 · 中英极速 · 自带标点 · 支持热词 · 0 显存'),
    'funasr-nano': ('sherpa:funasr-nano-int8-2025-12-30', 'LLM 语义纠错 · 中英/方言 · 自带标点与上下文 · 0 显存'),
    'qwen3-asr-0.6b': ('sherpa:qwen3-asr-0.6B-int8-2026-03-25', '通义千问 3 · 52 语种/22 方言 · 支持热词 · 0 显存'),
    'fire-red-asr2-ctc': ('sherpa:fire-red-asr2-ctc-zh_en-int8-2026-02-25', '小红书二代中英 CTC · 仅 CPU · 0 显存'),
    'sense-voice': ('sherpa:sense-voice-zh-en-ja-ko-yue-int8-2024-07-17', '中英粤日韩极速 · 自带标点 · 0 显存'),
    'paraformer-zh': ('sherpa:paraformer-zh-int8-2025-10-07', '普通话专用 · 仅 CPU · 不支持热词'),
    'tiny': ('Systran/faster-whisper-tiny', 'Whisper 极轻量 · 速度最快，精度较低'),
    'base': ('Systran/faster-whisper-base', 'Whisper 轻量 · 适合简单短句'),
    'small': ('Systran/faster-whisper-small', 'Whisper 小模型 · 低显存'),
    'medium': ('Systran/faster-whisper-medium', 'Whisper 中等大小 · 精度与占用折中'),
    'large-v3-turbo': ('mobiuslabsgmbh/faster-whisper-large-v3-turbo', 'Whisper 大模型加速版'),
    'large-v3': ('Systran/faster-whisper-large-v3', 'Whisper 完整大模型 · 高显存占用'),
}


def installed(path):
    path = Path(path)
    return (path / 'model.bin').is_file() or sherpa_engine.is_model(path)
