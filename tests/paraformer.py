"""Paraformer install + worker protocol with a fake archive and fake sherpa_onnx; no network or real weights."""
import hashlib, io, json, os, sys, tarfile, tempfile, types, importlib.util
from pathlib import Path
from unittest.mock import patch
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root/'python'))
import numpy as np
import model_catalog, paraformer_engine
spec = importlib.util.spec_from_file_location('download_model', root/'download_model.py')
dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)


def archive(path, evil=False):
    with tarfile.open(path, 'w:bz2') as t:
        names = ['pkg/model.int8.onnx', 'pkg/tokens.txt', 'pkg/test_wavs/1.wav']
        if evil: names.append('../../escape/tokens.txt')
        for n in names:
            data = b'x'; info = tarfile.TarInfo(n); info.size = 1; t.addfile(info, io.BytesIO(data))


with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'HOME': tmp}):
    good = Path(tmp)/'good.tar.bz2'; archive(good, evil=True)
    spec_ = dm.PARAFORMER['paraformer-zh']
    fetch = lambda url, dest, progress=None: Path(dest).write_bytes(good.read_bytes())
    models = Path(tmp)/'.local/share/qingyin/models'
    with patch.object(dm, 'fetch', fetch):
        with patch.dict(spec_, sha256='0'*64):
            try: dm.download('paraformer-zh'); raise AssertionError('bad checksum accepted')
            except RuntimeError: pass
        assert not (models/'paraformer-zh').exists() and not list((models/'.downloads').iterdir())
        with patch.dict(spec_, sha256=hashlib.sha256(good.read_bytes()).hexdigest()):
            dm.download('paraformer-zh')
            target = models/'paraformer-zh'
            assert sorted(p.name for p in target.iterdir()) == ['model.int8.onnx', 'tokens.txt']
            assert not (Path(tmp)/'escape').exists() and not (models.parent/'escape').exists()
            assert model_catalog.installed(target) and paraformer_engine.is_model(target)
            with patch.object(dm, 'fetch', side_effect=AssertionError('duplicate download')):
                dm.download('paraformer-zh')
    # Network failure keeps the partial archive; the next attempt resumes and installs.
    import shutil; shutil.rmtree(models/'paraformer-zh')
    calls = []
    def flaky(url, dest, progress=None):
        calls.append(Path(dest).exists())
        if len(calls) == 1: Path(dest).write_bytes(good.read_bytes()[:10]); raise RuntimeError('下载多次中断')
        Path(dest).write_bytes(good.read_bytes())
    with patch.object(dm, 'fetch', flaky), patch.dict(spec_, sha256=hashlib.sha256(good.read_bytes()).hexdigest()):
        part = models/'.downloads/paraformer-zh.part'
        try: dm.download('paraformer-zh'); raise AssertionError('failure swallowed')
        except RuntimeError: pass
        assert (part/'model.tar.bz2').is_file() and not (models/'paraformer-zh').exists()
        dm.download('paraformer-zh')
        assert calls == [False, True] and not part.exists() and paraformer_engine.is_model(models/'paraformer-zh')
    whisper = Path(tmp)/'w'; whisper.mkdir(); (whisper/'model.bin').touch()
    assert model_catalog.installed(whisper) and not paraformer_engine.is_model(whisper)
    assert not model_catalog.installed(Path(tmp)/'empty')

    # Worker protocol: fake recognizer, ffmpeg and punctuation; hotwords/context must be ignored safely.
    class Result: text = '你好世界'
    class Stream:
        result = Result()
        def accept_waveform(self, rate, samples): assert rate == 16000 and len(samples) == 4
    class Recognizer:
        def create_stream(self): return Stream()
        def decode_stream(self, s): pass
    fake = types.ModuleType('sherpa_onnx')
    fake.OfflineRecognizer = types.SimpleNamespace(from_paraformer=lambda **kw: (kw['provider'] == 'cpu') and Recognizer())
    pcm = np.zeros(4, dtype=np.float32).tobytes()
    request = json.dumps(dict(path='x.wav', punctuation=True, learning=False, hotwords='甲乙', context='上文'))
    out = io.StringIO()
    with patch.dict(sys.modules, {'sherpa_onnx': fake}), patch.object(paraformer_engine.subprocess, 'run', return_value=types.SimpleNamespace(stdout=pcm)), \
         patch('punctuation.restore', side_effect=lambda t: t + '。'), patch.object(sys, 'stdin', io.StringIO(request+'\n')), patch.object(sys, 'stdout', out):
        paraformer_engine.serve(target)
    lines = [json.loads(l) for l in out.getvalue().splitlines()]
    assert lines[0] == {'ready': True, 'device': 'cpu'}, lines
    assert lines[1] == {'text': '你好世界'}, lines  # trailing period removed
print('PASS: Paraformer pinned checksum, safe extraction, model detection and CPU worker protocol')
