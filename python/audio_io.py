"""Fast 16 kHz mono PCM WAV reader with ffmpeg fallback for non-standard audio."""
from pathlib import Path
import subprocess
import wave


def load_audio(path, run=None):
    """Return float32 16 kHz mono samples in [-1, 1] without spawning ffmpeg when possible."""
    import numpy as np

    audio_path = Path(path)
    if audio_path.is_file():
        try:
            with wave.open(str(audio_path), 'rb') as wav:
                if wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getframerate() == 16000:
                    pcm = wav.readframes(wav.getnframes())
                    if not pcm:
                        return np.zeros(0, dtype=np.float32)
                    return np.frombuffer(pcm, dtype='<i2').astype(np.float32) * (1.0 / 32768.0)
        except (wave.Error, OSError, EOFError):
            pass

    runner = run or subprocess.run
    raw = runner(
        ['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path), '-f', 'f32le', '-ac', '1', '-ar', '16000', 'pipe:1'],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()
