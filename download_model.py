"""Explicit online installation only; never loads CUDA or changes preferences."""
import hashlib
import http.client
import shutil
import time
import os
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path
import tempfile
sys.path.insert(0, str(Path(__file__).parent/'python'))
from model_catalog import MODELS


class Progress:
    """Aggregate byte progress over several files, printed as 'PROGRESS <done> <total>' (throttled)."""
    def __init__(self):
        self.files = {}; self.last = 0.0

    def update(self, key, done, total):
        self.files[key] = (done, total); now = time.monotonic()
        if now - self.last >= 0.25 or done >= total:
            self.last = now; self.emit()

    def emit(self):
        done = sum(d for d, _ in self.files.values()); total = sum(t for _, t in self.files.values())
        if total: print(f'PROGRESS {done} {total}', flush=True)


def hub_bar(progress):
    """tqdm class for huggingface_hub that reports byte bars to Progress instead of drawing."""
    from tqdm.auto import tqdm

    class Bar(tqdm):
        def __init__(self, *args, **kwargs):
            self._bytes = kwargs.get('unit') == 'B'; self._seen = kwargs.get('initial', 0) or 0
            super().__init__(*args, **kwargs)
            if self._bytes and kwargs.get('total'): progress.update(id(self), self._seen, kwargs['total'])

        def update(self, n=1):
            result = super().update(n)
            if self._bytes and n: self._seen += n; progress.update(id(self), self._seen, self.total or 0)
            return result
    return Bar


def sha256_of(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''): digest.update(block)
    return digest.hexdigest()


def fetch(url, dest, attempts=20, progress=None):
    """Download with HTTP Range resume; a dropped connection continues instead of restarting."""
    dest = Path(dest); last = None
    for attempt in range(attempts):
        done = dest.stat().st_size if dest.exists() else 0
        request = urllib.request.Request(url, headers={'Range': f'bytes={done}-'} if done else {})
        try:
            with urllib.request.urlopen(request, timeout=30) as reply:
                if done and reply.status != 206: done = 0  # server ignored Range: start over
                total = int(reply.headers.get('Content-Length', 0)) + done
                if progress and total: progress.update(dest.name, done, total)
                with dest.open('ab' if done else 'wb') as out:
                    while block := reply.read(1 << 20):
                        out.write(block); done += len(block)
                        if progress and total: progress.update(dest.name, done, total)
            if not total or dest.stat().st_size == total: return
            last = OSError('下载不完整')
        except (OSError, ValueError, http.client.HTTPException) as exc:
            last = exc  # IncompleteRead is not an OSError; bytes already written are kept for resume
        # HTTP 416 means the file is already complete.
        if isinstance(last, urllib.error.HTTPError) and last.code == 416: return
        time.sleep(min(2*(attempt+1), 15))
    raise RuntimeError(f'下载多次中断：{last}')


PARAFORMER = {
    'paraformer-zh': dict(
        archive='sherpa-onnx-paraformer-zh-int8-2025-10-07',
        sha256='a071ee5419e14adb34d7f970ab98105a45e6608018b168f023ca2e4810744abe',
        url='https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-zh-int8-2025-10-07.tar.bz2'),
}
PARAFORMER_FILES = ('model.int8.onnx', 'tokens.txt')


def download_paraformer(name):
    spec = PARAFORMER[name]
    root = Path.home()/'.local/share/qingyin/models'
    target = root/name
    if all((target/f).is_file() for f in PARAFORMER_FILES):
        print('模型已安装：'+name, flush=True); return
    if target.exists(): raise RuntimeError('目标目录不完整，请先移走该目录后重试')
    # A fixed partial directory survives failures, so the next attempt resumes instead of restarting.
    part = root/'.downloads'/(name+'.part'); part.mkdir(parents=True, exist_ok=True)
    archive = part/'model.tar.bz2'
    print('正在下载 '+name+'（约 228 MB），完成前不会出现在已安装模型列表', flush=True)
    fetch(spec['url'], archive, progress=Progress())
    if sha256_of(archive) != spec['sha256']:
        shutil.rmtree(part, ignore_errors=True); raise RuntimeError('模型校验失败，已删除不完整文件，请重新下载')
    folder = part/name; shutil.rmtree(folder, ignore_errors=True); folder.mkdir()
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            # Take only the two known files by basename; never trust archive paths.
            base = Path(member.name).name
            if member.isfile() and base in PARAFORMER_FILES and base not in {p.name for p in folder.iterdir()}:
                with bundle.extractfile(member) as source, (folder/base).open('wb') as out:
                    out.write(source.read())
    for required in PARAFORMER_FILES:
        if not (folder/required).is_file(): raise RuntimeError('模型文件不完整：'+required)
    os.rename(folder, target); shutil.rmtree(part, ignore_errors=True)
    print('模型已安装：'+name, flush=True)


PREVIEW = 'streaming-preview'
PREVIEW_REVISION = '8e40c43232a1c5c66c82111efc5820d3accca11b'
PREVIEW_BASE = 'https://huggingface.co/csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en/resolve/'+PREVIEW_REVISION+'/'
PREVIEW_SIZES = {'encoder.int8.onnx': 165462184, 'decoder.int8.onnx': 71664561, 'tokens.txt': 75756}
PREVIEW_FILES = {
    'encoder.int8.onnx': '81a70226a8934e6ed92aa1d4fc486b428b5398e2f2619ed4897b7294cab90e9a',
    'decoder.int8.onnx': 'f3cca9f77bb9d93c8fcbfb63ae617b6b1ee96818df3aa3b151c40658fe38594f',
    'tokens.txt': '59aba8873a2ed1e122c25fee421e25f283b63290efbde85c1f01a853d83cb6e6',
}


def download_preview():
    base = Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'qingyin'
    target = base/'preview/streaming-paraformer-zh-en'
    if all((target/f).is_file() for f in PREVIEW_FILES):
        print('实时预览模型已安装', flush=True); return
    if target.exists(): raise RuntimeError('目标目录不完整，请先移走该目录后重试')
    part = base/'preview/.downloads/streaming-preview.part'; part.mkdir(parents=True, exist_ok=True)
    print('正在下载实时预览模型（约 237 MB），完成前不会启用', flush=True)
    progress = Progress()
    for name, size in PREVIEW_SIZES.items(): progress.files[name] = (0, size)  # total known up front
    for name, expected in PREVIEW_FILES.items():
        if not ((part/name).is_file() and sha256_of(part/name) == expected):  # finished files are kept
            fetch(PREVIEW_BASE+name, part/name, progress=progress)
        if sha256_of(part/name) != expected:
            (part/name).unlink(missing_ok=True); raise RuntimeError('预览模型校验失败，已删除不完整文件，请重新下载：'+name)
        progress.update(name, PREVIEW_SIZES[name], PREVIEW_SIZES[name])
    os.rename(part, target)
    print('实时预览模型已安装', flush=True)


def download(name):
    if name == PREVIEW: return download_preview()
    if name in PARAFORMER: return download_paraformer(name)
    # The normal launcher is offline; explicit model downloads may go online.
    for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'): os.environ.pop(key, None)
    from huggingface_hub import HfApi, snapshot_download
    root = Path.home()/'.local/share/qingyin/models'
    target = root/name
    if (target/'model.bin').is_file() and (target/'config.json').is_file():
        print('模型已安装：'+name, flush=True); return
    if target.exists(): raise RuntimeError('目标目录不完整，请先移走该目录后重试')
    repo = MODELS[name][0]
    revision = HfApi().model_info(repo).sha
    staging = root/'.downloads'; staging.mkdir(parents=True, exist_ok=True)
    print('正在下载 '+name+'，完成前不会出现在已安装模型列表', flush=True)
    with tempfile.TemporaryDirectory(dir=staging) as tmp:
        folder = Path(tmp)/name
        snapshot_download(repo_id=repo, revision=revision, local_dir=folder, max_workers=2, tqdm_class=hub_bar(Progress()),
                          allow_patterns=['model.bin','config.json','tokenizer.json','preprocessor_config.json','vocabulary.*'])
        for required in ('model.bin','config.json','tokenizer.json'):
            if not (folder/required).is_file(): raise RuntimeError('模型文件不完整：'+required)
        os.rename(folder, target)
    print('模型已安装：'+name, flush=True)


if __name__=='__main__':
    if len(sys.argv)!=2 or sys.argv[1] not in (*MODELS, PREVIEW):
        raise SystemExit('请选择模型：'+', '.join((*MODELS, PREVIEW)))
    try: download(sys.argv[1])
    except Exception as exc:
        print('下载失败：'+str(exc), file=sys.stderr); sys.exit(1)
