"""One session-scoped, offline-only Whisper model; JSON lines over stdin/stdout."""
import json, os, sys, subprocess
import numpy as np
from pathlib import Path
from gpu_policy import prepare_cuda
from normalize import simplified, without_final_period
from punctuation import restore_isolated
import learning
import rime_dictionary
from prompt_budget import prepare
model_dir = Path(sys.argv[1])
device = sys.argv[2] if len(sys.argv) > 2 else "cuda"
import paraformer_engine
if paraformer_engine.is_model(model_dir):
    paraformer_engine.serve(model_dir)  # CPU only; never touches CUDA
    sys.exit(0)
try:
    if device == "cuda":
        gpu = prepare_cuda()
        print(f"识别显卡：{gpu['name']} · {gpu['uuid']} · 可用 {gpu['free']} MiB", file=sys.stderr, flush=True)
    from faster_whisper import WhisperModel
    model = WhisperModel(str(model_dir), device=device,
                         compute_type=sys.argv[3] if len(sys.argv) > 3 else ("float16" if device == "cuda" else "int8"),
                         local_files_only=True, cpu_threads=8)
except Exception as exc:
    print(f"模型加载失败：{exc}", file=sys.stderr, flush=True)
    print(json.dumps({"error": str(exc)}, ensure_ascii=False), flush=True)
    sys.exit(1)
print(json.dumps({"ready": True, "device": device}), flush=True)
for line in sys.stdin:
    try:
        request = json.loads(line)
        audio = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", request["path"], "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"], check=True, capture_output=True).stdout
        samples = np.frombuffer(audio, dtype=np.float32).copy()
        vocabulary = {'rules': []}
        if request.get('learning', True):
            try:
                vocabulary = learning.load()
            except Exception as exc:
                print(f'个人词库读取失败，保留原识别：{exc}', file=sys.stderr, flush=True)
        hotwords = ', '.join(filter(None, [request.get('hotwords'), learning.hints(vocabulary)]))
        context = request.get('context', '')[-512:] if request.get('learning', True) else ''
        if request.get('rime_dictionary', True):
            try:
                dictionary_hints = rime_dictionary.hints(context)
                hotwords = ', '.join(filter(None, [hotwords, dictionary_hints]))
            except Exception as exc:
                print(f'雾凇词库读取失败，保留原识别：{exc}', file=sys.stderr, flush=True)
        context, hotwords = prepare(context, hotwords, model.hf_tokenizer)
        segments, info = model.transcribe(samples, language=None if request.get("language") == "auto" else request.get("language", "zh"),
                                         vad_filter=True,
                                         vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 400},
                                         beam_size=int(request.get("beam_size", 5)),
                                         temperature=(0.0, 0.2, 0.4),
                                         condition_on_previous_text=True,
                                         prompt_reset_on_temperature=0.3,
                                         hotwords=hotwords or None,
                                         initial_prompt=context or None)
        text = simplified("".join(s.text for s in segments).strip())
        text = learning.apply(text, vocabulary)
        if request.get("punctuation", True):
            try:
                text = restore_isolated(text)
            except Exception as exc:
                # Keep the recognized words even if optional punctuation fails.
                print(f"补标点失败，保留原转写：{exc}", file=sys.stderr, flush=True)
        text = without_final_period(text)
        print(json.dumps({"text": text}, ensure_ascii=False), flush=True)
    except Exception as exc:
        print(f"转写失败：{exc}", file=sys.stderr, flush=True)
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), flush=True)

    finally:
        # Residency retains weights only, not the last recording or input context.
        for key in ('request','audio','samples','vocabulary','hotwords','context','segments','info','text','line','dictionary_hints'):
            globals().pop(key, None)
