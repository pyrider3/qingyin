"""Tests for the 2026 Qingyin overhaul: zero-ffmpeg WAV, spacing, unified sherpa engine, idle unload & direct Rust socket."""
import io
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import types
from unittest.mock import patch
import wave

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'python'))

import audio_io
import normalize
import sherpa_engine

# 1. Zero-ffmpeg direct WAV reading for 16kHz mono s16 PCM
with tempfile.TemporaryDirectory() as tmp:
    wav_path = Path(tmp) / 'sample.wav'
    with wave.open(str(wav_path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack('<4h', 0, 16384, -16384, 32767))

    def forbid_ffmpeg(*_a, **_k):
        raise AssertionError('ffmpeg must not run on 16kHz mono s16 WAV')

    samples = audio_io.load_audio(wav_path, run=forbid_ffmpeg)
    assert len(samples) == 4 and abs(samples[1] - 0.5) < 1e-4 and abs(samples[2] + 0.5) < 1e-4, samples
print('PASS: zero-ffmpeg direct WAV loading')

# 2. CJK punctuation spacing cleanup
assert normalize.clean_spacing('昨天是 Monday, today is 礼拜二， the day after tomorrow 是星期三。') == \
    '昨天是 Monday, today is 礼拜二，the day after tomorrow 是星期三。'
assert normalize.clean_spacing('第一句是个什么时态？ 加了 es 是一般现在时， 我们写上。') == \
    '第一句是个什么时态？加了 es 是一般现在时，我们写上。'
assert normalize.clean_spacing('使用 Neovim 和 ChatGPT') == '使用 Neovim 和 ChatGPT'
print('PASS: CJK punctuation spacing cleanup')

# 3. Unified sherpa_engine model detection + BPE hotword formatting & OOV filtering
with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)

    # X-ASR transducer with SentencePiece punctuation tokens
    xasr = base / 'x-asr-zh-en'
    xasr.mkdir()
    for f in ('encoder-epoch-99-avg-1.int8.onnx', 'decoder-epoch-99-avg-1.onnx', 'joiner-epoch-99-avg-1.int8.onnx'):
        (xasr / f).write_bytes(b'x')
    (xasr / 'tokens.txt').write_text('<blk> 0\n▁， 1\n▁。 2\n▁青 3\n▁音 4\n▁Q 5\n▁n 6\ni 7\nr 8\n')
    spec = sherpa_engine.detect_model(xasr)
    assert spec['kind'] == 'transducer' and spec['native_punctuation'] and spec['is_sentencepiece'], spec
    hw = sherpa_engine.format_transducer_hotwords(['青音', 'fcitx5', 'niri'], spec['token_set'], True)
    assert '青 音 :2' in hw and 'niri :2' in hw and 'fcitx5' not in hw, hw

    # FunASR-Nano
    fn = base / 'funasr-nano'
    (fn / 'Qwen3-0.6B').mkdir(parents=True)
    for f in ('encoder_adaptor.int8.onnx', 'llm.int8.onnx', 'embedding.int8.onnx'):
        (fn / f).write_bytes(b'x')
    spec = sherpa_engine.detect_model(fn)
    assert spec['kind'] == 'funasr-nano' and spec['native_punctuation'] and spec['supports_context'], spec

    # Qwen3-ASR
    q3 = base / 'qwen3-asr-0.6b'
    (q3 / 'tokenizer').mkdir(parents=True)
    for f in ('conv_frontend.onnx', 'encoder.int8.onnx', 'decoder.int8.onnx'):
        (q3 / f).write_bytes(b'x')
    spec = sherpa_engine.detect_model(q3)
    assert spec['kind'] == 'qwen3-asr' and spec['native_punctuation'] and spec['supports_hotwords'], spec

    # SenseVoice via engine.json & FireRedASR2-CTC via engine.json
    sv = base / 'sv'
    sv.mkdir()
    (sv / 'model.int8.onnx').write_bytes(b'x')
    (sv / 'tokens.txt').write_text('<unk> 0\n')
    (sv / 'engine.json').write_text(json.dumps({'engine': 'sense-voice'}))
    assert sherpa_engine.detect_model(sv)['kind'] == 'sense-voice'

    fr = base / 'fr'
    fr.mkdir()
    (fr / 'model.int8.onnx').write_bytes(b'x')
    (fr / 'tokens.txt').write_text('<blk> 0\n')
    (fr / 'engine.json').write_text(json.dumps({'engine': 'fire-red-asr-ctc'}))
    assert sherpa_engine.detect_model(fr)['kind'] == 'fire-red-asr-ctc'
print('PASS: multi-family sherpa_engine detection and OOV-safe BPE hotwords')

# 4. Resident idle auto-unload + direct Rust UnixStream resident session
binary = root / 'target/release/qingyin'
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp)
    app = p / 'app'
    (app / '.venv/bin').mkdir(parents=True)
    (app / 'python').mkdir(parents=True)
    (app / '.venv/bin/python').symlink_to('/usr/bin/python3')
    rt = p / 'run'
    rt.mkdir()
    cfg_dir = p / '.config/qingyin'
    cfg_dir.mkdir(parents=True)
    bin_dir = p / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'notify-send').symlink_to('/usr/bin/true')
    (bin_dir / 'niri').write_text('#!/bin/sh\nprintf \'[{"id":1,"is_focused":true}]\\n\'\n')
    (bin_dir / 'niri').chmod(0o755)
    rec = bin_dir / 'pw-record'
    rec.write_text('''#!/usr/bin/python3
import sys, wave, time, signal
w = wave.open(sys.argv[-1], 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b'\\0'*3200); w.close()
signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
time.sleep(60)
''')
    rec.chmod(0o755)
    (app / 'python/asr.py').write_text('''import json, os, sys
print(json.dumps({'ready': True}), flush=True)
for line in sys.stdin:
    print(json.dumps({'text': f'直连成功-{os.getpid()}'}), flush=True)
''')
    # Intentionally DO NOT provide app/python/resident.py so Rust must connect directly without Python bridge!
    env = {
        **os.environ,
        'HOME': str(p),
        'QINGYIN_HOME': str(app),
        'XDG_RUNTIME_DIR': str(rt),
        'PATH': str(bin_dir) + ':' + os.environ['PATH'],
    }
    code = 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import resident; resident.ROOT=Path(sys.argv[2]); resident.serve(idle_unload_seconds=1.2, exit_on_idle=True)'
    server = subprocess.Popen([sys.executable, '-c', code, str(root / 'python'), str(app)], env=env, start_new_session=True)
    sock = rt / 'qingyin/model.sock'
    for _ in range(100):
        if sock.exists():
            break
        time.sleep(0.02)
    assert sock.exists(), 'resident socket failed to appear'

    (cfg_dir / 'config.json').write_text(json.dumps({
        'resident_model': True,
        'idle_unload_seconds': 2,
        'model': 'fake',
        'device': 'cpu',
        'language': 'zh',
        'auto_input': False,
        'microphone': None,
        'max_seconds': 10,
        'live_preview': False,
    }))
    try:
        # Two consecutive Rust sessions must reuse the exact same worker PID via direct UnixStream!
        pids = []
        for _ in range(2):
            sess = subprocess.Popen([binary, 'session'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(100):
                st = json.loads(subprocess.check_output([binary, 'status'], env=env).decode())
                if st['phase'] == 'recording':
                    break
                time.sleep(0.02)
            subprocess.check_output([binary, 'toggle'], env=env)
            sess.wait(timeout=5)
            st = json.loads(subprocess.check_output([binary, 'status'], env=env).decode())
            assert st['text'].startswith('直连成功-'), st
            pids.append(st['text'])
        assert pids[0] == pids[1], f'worker was not reused across Rust direct resident sessions: {pids}'

        # Now wait >1.2s idle; resident server with exit_on_idle=True must unload and exit to 0 MB!
        server.wait(timeout=5)
        assert server.returncode == 0 and not sock.exists()
        print('PASS: Rust direct resident UnixStream reuse + idle auto-unload to 0 MB')
    finally:
        if server.poll() is None:
            os.killpg(server.pid, signal.SIGTERM)
            server.wait(timeout=3)
