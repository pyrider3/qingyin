"""Live preview: growing-WAV tailing, partial-text protocol and pinned download; fake recognizer, no network."""
import hashlib, importlib.util, io, json, os, struct, sys, tempfile
from pathlib import Path
from unittest.mock import patch
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root/'python'))
import preview
spec = importlib.util.spec_from_file_location('download_model', root/'download_model.py')
dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)


def header(extra=b''):
    # pw-record style: sizes are placeholders while recording; an extra chunk must be skipped.
    return b'RIFF' + struct.pack('<I', 0xFFFFFFFF) + b'WAVE' + extra + b'data' + struct.pack('<I', 0xFFFFFFFF)


pcm = struct.pack('<5h', 1000, -1000, 2000, -2000, 3000)
with tempfile.TemporaryDirectory() as tmp:
    wav = Path(tmp)/'r.wav'
    odd = b'LIST' + struct.pack('<I', 3) + b'abc' + b'\0'  # odd-sized chunk plus pad byte
    assert preview.data_offset(header(odd)) == len(header(odd))
    assert preview.data_offset(b'RIFF\0\0\0\0WAVEfmt ') is None
    try: preview.data_offset(b'not a wav file'); raise AssertionError('bad header accepted')
    except ValueError: pass
    # Header first, data later, sample split across reads: no sample may be lost or duplicated.
    wav.write_bytes(header(odd)); tail = preview.Tail(wav)
    assert tail.read() == []
    with wav.open('ab') as f: f.write(pcm[:3])
    first = tail.read()
    with wav.open('ab') as f: f.write(pcm[3:])
    rest = tail.read()
    values = [round(v * 32768) for v in first + rest]
    assert values == [1000, -1000, 2000, -2000, 3000], values

    # serve(): partial text printed only on change; ends when the recording file is removed.
    class Result: pass
    class Rec:
        def __init__(self): self.texts = iter(['你好', '你好', '你好世界']); self.fed = 0; self.ready = False
        def create_stream(self): return self
        def accept_waveform(self, rate, samples): assert rate == 16000 and samples.dtype.name == 'float32'; self.ready = True
        def is_ready(self, stream): r, self.ready = self.ready, False; return r
        def decode_stream(self, stream): pass
        def get_result(self, stream): return next(self.texts)
    wav.write_bytes(header()); calls = {'n': 0}
    def clock(_):
        calls['n'] += 1
        with wav.open('ab') as f: f.write(pcm)
        if calls['n'] >= 4: wav.unlink()
    out = io.StringIO()
    preview.serve(wav, recognizer=Rec(), clock=clock, out=out)
    lines = [json.loads(l) for l in out.getvalue().splitlines()]
    assert lines[0] == {'ready': True} and [l['text'] for l in lines[1:]] == ['你好', '你好世界'], lines

    # Download: pinned revision, checksum per file, atomic install, nothing left on failure.
    data = {name: name.encode()*3 for name in dm.PREVIEW_FILES}
    sums = {name: hashlib.sha256(blob).hexdigest() for name, blob in data.items()}
    urls = []
    def fetch(url, dest, progress=None): urls.append(url); Path(dest).write_bytes(data[url.rsplit('/', 1)[1]])
    with patch.dict(os.environ, {'XDG_DATA_HOME': tmp}), patch.object(dm, 'fetch', fetch):
        target = Path(tmp)/'qingyin/preview/streaming-paraformer-zh-en'
        with patch.dict(dm.PREVIEW_FILES, {**sums, 'tokens.txt': '0'*64}):
            try: dm.download('streaming-preview'); raise AssertionError('bad checksum accepted')
            except RuntimeError: pass
        part = target.parent/'.downloads/streaming-preview.part'
        # A corrupt file is deleted, verified files are kept so the next click only fetches what is missing.
        assert not target.exists() and sorted(p.name for p in part.iterdir()) == ['decoder.int8.onnx', 'encoder.int8.onnx'], list(part.iterdir())
        urls.clear()
        with patch.dict(dm.PREVIEW_FILES, sums):
            dm.download('streaming-preview')
            assert urls == [dm.PREVIEW_BASE+'tokens.txt'], urls
            assert preview.installed(target) and not part.exists()
            assert dm.PREVIEW_REVISION in urls[0]
            with patch.object(dm, 'fetch', side_effect=AssertionError('duplicate download')):
                dm.download('streaming-preview')
        with patch.dict(os.environ, {'XDG_DATA_HOME': tmp}): assert preview.model_dir() == target
print('PASS: growing WAV tailing, change-only partial text, clean stop, pinned verified preview download')

# Resume: the server drops the connection mid-body once, then honours Range.
import http.server, threading, importlib.util as _u
blob = os.urandom(300_000); state = {'drops': 1, 'ranges': []}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        rng = self.headers.get('Range'); state['ranges'].append(rng)
        start = int(rng.split('=')[1].rstrip('-')) if rng else 0
        self.send_response(206 if rng else 200)
        self.send_header('Content-Length', str(len(blob) - start)); self.end_headers()
        if state['drops'] and not rng:
            state['drops'] -= 1; self.wfile.write(blob[:100_000]); self.wfile.flush(); self.connection.close(); return
        self.wfile.write(blob[start:])
server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H); threading.Thread(target=server.serve_forever, daemon=True).start()
with tempfile.TemporaryDirectory() as tmp:
    dest = Path(tmp)/'f.bin'
    seen = io.StringIO(); progress = dm.Progress()
    with patch('sys.stdout', seen), patch.object(dm.time, 'sleep'), patch.object(dm.time, 'monotonic', side_effect=iter(range(0, 10_000, 1))):
        dm.fetch(f'http://127.0.0.1:{server.server_port}/f.bin', dest, progress=progress)
    marks = [tuple(map(int, l.split()[1:])) for l in seen.getvalue().splitlines() if l.startswith('PROGRESS ')]
    assert marks and marks[-1] == (len(blob), len(blob)), marks[-3:]
    assert dest.read_bytes() == blob and state['ranges'][0] is None and state['ranges'][1] == 'bytes=100000-', state['ranges']
server.shutdown()

# HF progress bars: byte bars from several files add up; non-byte bars are ignored.
progress = dm.Progress(); out = io.StringIO()
with patch('sys.stdout', out), patch.object(dm.time, 'monotonic', side_effect=iter(range(0, 10_000, 1))):
    Bar = dm.hub_bar(progress)
    a = Bar(total=100, unit='B', disable=True); b = Bar(total=300, unit='B', disable=True); files = Bar(total=2, unit='it', disable=True)
    a.update(50); b.update(150); files.update(1); b.update(150); a.update(50)
lines = [l for l in out.getvalue().splitlines() if l.startswith('PROGRESS ')]
assert lines[-1] == 'PROGRESS 400 400', lines
assert not any(l.endswith(' 2') for l in lines)
print('PASS: interrupted download resumes, progress lines reach 100% and hub bars aggregate')
