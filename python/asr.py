"""One session-scoped, offline-only Whisper model; JSON lines over stdin/stdout."""
import json, os, sys, subprocess
import numpy as np
from pathlib import Path
from faster_whisper import WhisperModel
from normalize import simplified
model_dir = Path(sys.argv[1])
device = sys.argv[2] if len(sys.argv) > 2 else "cuda"
model = WhisperModel(str(model_dir), device=device,
                     compute_type=sys.argv[3] if len(sys.argv) > 3 else ("float16" if device == "cuda" else "int8"),
                     local_files_only=True, cpu_threads=8)
print(json.dumps({"ready": True, "device": device}), flush=True)
for line in sys.stdin:
    try:
        request = json.loads(line)
        audio = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", request["path"], "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"], check=True, capture_output=True).stdout
        samples = np.frombuffer(audio, dtype=np.float32).copy()
        segments, info = model.transcribe(samples, language=None if request.get("language") == "auto" else request.get("language", "zh"),
                                         vad_filter=True,
                                         vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 400},
                                         beam_size=int(request.get("beam_size", 5)),
                                         temperature=(0.0, 0.2, 0.4),
                                         condition_on_previous_text=True,
                                         prompt_reset_on_temperature=0.3,
                                         hotwords=request.get("hotwords") or None)
        text = simplified("".join(s.text for s in segments).strip())
        print(json.dumps({"text": text}, ensure_ascii=False), flush=True)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), flush=True)
