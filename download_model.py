"""Explicit online installation only; never loads CUDA or changes preferences."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).parent / 'python'))
from model_catalog import MODELS, installed


class Progress:
    """Aggregate byte progress over several files, printed as 'PROGRESS <done> <total>' (throttled)."""
    def __init__(self):
        self.files = {}
        self.last = 0.0

    def update(self, key, done, total):
        self.files[key] = (done, total)
        now = time.monotonic()
        if now - self.last >= 0.25 or done >= total:
            self.last = now
            self.emit()

    def emit(self):
        done = sum(d for d, _ in self.files.values())
        total = sum(t for _, t in self.files.values())
        if total:
            print(f'PROGRESS {done} {total}', flush=True)


def hub_bar(progress):
    """tqdm class for huggingface_hub that reports byte bars to Progress instead of drawing."""
    from tqdm.auto import tqdm

    class Bar(tqdm):
        def __init__(self, *args, **kwargs):
            self._bytes = kwargs.get('unit') == 'B'
            self._seen = kwargs.get('initial', 0) or 0
            super().__init__(*args, **kwargs)
            if self._bytes and kwargs.get('total'):
                progress.update(id(self), self._seen, kwargs['total'])

        def update(self, n=1):
            result = super().update(n)
            if self._bytes and n:
                self._seen += n
                progress.update(id(self), self._seen, self.total or 0)
            return result
    return Bar


def sha256_of(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def fetch(url, dest, attempts=20, progress=None):
    """Download with HTTP Range resume; a dropped connection continues instead of restarting."""
    dest = Path(dest)
    last = None
    for attempt in range(attempts):
        done = dest.stat().st_size if dest.exists() else 0
        request = urllib.request.Request(url, headers={'Range': f'bytes={done}-'} if done else {})
        try:
            with urllib.request.urlopen(request, timeout=30) as reply:
                if done and reply.status != 206:
                    done = 0  # server ignored Range: start over
                total = int(reply.headers.get('Content-Length', 0)) + done
                if progress and total:
                    progress.update(dest.name, done, total)
                with dest.open('ab' if done else 'wb') as out:
                    while block := reply.read(1 << 20):
                        out.write(block)
                        done += len(block)
                        if progress and total:
                            progress.update(dest.name, done, total)
            if not total or dest.stat().st_size == total:
                return
            last = OSError('下载不完整')
        except (OSError, ValueError, http.client.HTTPException) as exc:
            last = exc  # IncompleteRead is not an OSError; bytes already written are kept for resume
        # HTTP 416 means the file is already complete.
        if isinstance(last, urllib.error.HTTPError) and last.code == 416:
            return
        time.sleep(min(2 * (attempt + 1), 15))
    raise RuntimeError(f'下载多次中断：{last}')


_GH_ASR = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/'

SHERPA_MODELS = {
    'x-asr-zh-en': dict(
        size_mb=136,
        sha256='5d02c36d7b44e886b7c8f0d8e051f8713acab96c264bb6ef9e718be39a6a2224',
        url=_GH_ASR + 'sherpa-onnx-x-asr-zipformer-transducer-zh-en-punct-int8-2026-06-03.tar.bz2',
        files=('encoder-epoch-99-avg-1.int8.onnx', 'decoder-epoch-99-avg-1.onnx', 'joiner-epoch-99-avg-1.int8.onnx', 'tokens.txt', 'bpe.model'),
        required=('encoder-epoch-99-avg-1.int8.onnx', 'decoder-epoch-99-avg-1.onnx', 'joiner-epoch-99-avg-1.int8.onnx', 'tokens.txt'),
    ),
    'funasr-nano': dict(
        size_mb=842,
        sha256='eb43d7ccc2e86b243f6a03b7df361033dda66db9523d1a92bf6aca2b50c9476b',
        url=_GH_ASR + 'sherpa-onnx-funasr-nano-int8-2025-12-30.tar.bz2',
        files=('encoder_adaptor.int8.onnx', 'llm.int8.onnx', 'embedding.int8.onnx'),
        subdirs=('Qwen3-0.6B', 'tokenizer'),
        required=('encoder_adaptor.int8.onnx', 'llm.int8.onnx', 'embedding.int8.onnx'),
    ),
    'qwen3-asr-0.6b': dict(
        size_mb=879,
        sha256='393f8a14e2f5fb96746aaab342997a40641001fbd5bf9592a080a8329178ee96',
        url=_GH_ASR + 'sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25.tar.bz2',
        files=('conv_frontend.onnx', 'encoder.int8.onnx', 'decoder.int8.onnx'),
        subdirs=('tokenizer',),
        required=('conv_frontend.onnx', 'encoder.int8.onnx', 'decoder.int8.onnx'),
    ),
    'fire-red-asr2-ctc': dict(
        size_mb=521,
        sha256='1da8b737ecc5e29f36759a4460c754863e7c919a4ba325aea187331fbfc83274',
        url=_GH_ASR + 'sherpa-onnx-fire-red-asr2-ctc-zh_en-int8-2026-02-25.tar.bz2',
        files=('model.int8.onnx', 'tokens.txt'),
        required=('model.int8.onnx', 'tokens.txt'),
        engine='fire-red-asr-ctc',
    ),
    'sense-voice': dict(
        size_mb=163,
        sha256='7d1efa2138a65b0b488df37f8b89e3d91a60676e416f515b952358d83dfd347e',
        url=_GH_ASR + 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2',
        files=('model.int8.onnx', 'tokens.txt'),
        required=('model.int8.onnx', 'tokens.txt'),
        engine='sense-voice',
    ),
    'paraformer-zh': dict(
        size_mb=228,
        archive='sherpa-onnx-paraformer-zh-int8-2025-10-07',
        sha256='a071ee5419e14adb34d7f970ab98105a45e6608018b168f023ca2e4810744abe',
        url=_GH_ASR + 'sherpa-onnx-paraformer-zh-int8-2025-10-07.tar.bz2',
        files=('model.int8.onnx', 'tokens.txt'),
        required=('model.int8.onnx', 'tokens.txt'),
    ),
}
# Keep backward-compatible alias used by tests/paraformer.py.
PARAFORMER = SHERPA_MODELS
PARAFORMER_FILES = ('model.int8.onnx', 'tokens.txt')


def _safe_relpath(member_name: str):
    """Strip the single top-level archive folder and reject traversal / absolute paths."""
    parts = [p for p in Path(member_name).parts if p not in ('', '.')]
    if len(parts) < 2 or any(p in ('..', '/') for p in parts) or member_name.startswith('/'):
        return None
    return Path(*parts[1:])


def _extract_sherpa(archive: Path, folder: Path, spec: dict):
    allowed_files = set(spec.get('files', ()))
    allowed_dirs = set(spec.get('subdirs', ()))
    extracted = set()
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            if not member.isfile():
                continue
            rel = _safe_relpath(member.name)
            if rel is None:
                continue
            if len(rel.parts) == 1 and rel.name in allowed_files:
                dest_rel = rel
            elif len(rel.parts) >= 2 and rel.parts[0] in allowed_dirs:
                dest_rel = rel
            else:
                continue
            if dest_rel in extracted:
                continue
            dest = folder / dest_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(member) as source, dest.open('wb') as out:
                shutil.copyfileobj(source, out, 1 << 20)
            extracted.add(dest_rel)
    if spec.get('engine'):
        (folder / 'engine.json').write_text(json.dumps({'engine': spec['engine']}) + '\n')


def download_sherpa(name):
    spec = SHERPA_MODELS[name]
    root = Path.home() / '.local/share/qingyin/models'
    target = root / name
    if installed(target):
        print('模型已安装：' + name, flush=True)
        return
    if target.exists():
        raise RuntimeError('目标目录不完整，请先移走该目录后重试')
    # A fixed partial directory survives failures, so the next attempt resumes instead of restarting.
    part = root / '.downloads' / (name + '.part')
    part.mkdir(parents=True, exist_ok=True)
    archive = part / 'model.tar.bz2'
    print(f"正在下载 {name}（约 {spec.get('size_mb', 200)} MB），完成前不会出现在已安装模型列表", flush=True)
    fetch(spec['url'], archive, progress=Progress())
    if sha256_of(archive) != spec['sha256']:
        shutil.rmtree(part, ignore_errors=True)
        raise RuntimeError('模型校验失败，已删除不完整文件，请重新下载')
    folder = part / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    _extract_sherpa(archive, folder, spec)
    for required in spec['required']:
        if not (folder / required).is_file():
            raise RuntimeError('模型文件不完整：' + required)
    if not installed(folder):
        raise RuntimeError('模型结构校验失败：' + name)
    os.rename(folder, target)
    shutil.rmtree(part, ignore_errors=True)
    print('模型已安装：' + name, flush=True)


download_paraformer = download_sherpa

PREVIEW = 'streaming-preview'
XASR_PREVIEW = 'x-asr-preview'
PREVIEW_REVISION = '8e40c43232a1c5c66c82111efc5820d3accca11b'
PREVIEW_BASE = 'https://huggingface.co/csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en/resolve/' + PREVIEW_REVISION + '/'
PREVIEW_SIZES = {'encoder.int8.onnx': 165462184, 'decoder.int8.onnx': 71664561, 'tokens.txt': 75756}
PREVIEW_FILES = {
    'encoder.int8.onnx': '81a70226a8934e6ed92aa1d4fc486b428b5398e2f2619ed4897b7294cab90e9a',
    'decoder.int8.onnx': 'f3cca9f77bb9d93c8fcbfb63ae617b6b1ee96818df3aa3b151c40658fe38594f',
    'tokens.txt': '59aba8873a2ed1e122c25fee421e25f283b63290efbde85c1f01a853d83cb6e6',
}
XASR_PREVIEW_SPEC = dict(
    size_mb=134,
    sha256='fa5f63d618e5a01526e275a358bb7772e403f84808a4769fba52cffd8160bf74',
    url=_GH_ASR + 'sherpa-onnx-x-asr-480ms-streaming-zipformer-transducer-zh-en-punct-int8-2026-06-05.tar.bz2',
    files=('encoder.int8.onnx', 'decoder.onnx', 'joiner.int8.onnx', 'tokens.txt', 'bpe.model'),
    required=('encoder.int8.onnx', 'decoder.onnx', 'joiner.int8.onnx', 'tokens.txt'),
)


def download_preview():
    base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'qingyin'
    target = base / 'preview/streaming-paraformer-zh-en'
    if all((target / f).is_file() for f in PREVIEW_FILES):
        print('实时预览模型已安装', flush=True)
        return
    if target.exists():
        raise RuntimeError('目标目录不完整，请先移走该目录后重试')
    part = base / 'preview/.downloads/streaming-preview.part'
    part.mkdir(parents=True, exist_ok=True)
    print('正在下载实时预览模型（约 237 MB），完成前不会启用', flush=True)
    progress = Progress()
    for name, size in PREVIEW_SIZES.items():
        progress.files[name] = (0, size)  # total known up front
    for name, expected in PREVIEW_FILES.items():
        if not ((part / name).is_file() and sha256_of(part / name) == expected):  # finished files are kept
            fetch(PREVIEW_BASE + name, part / name, progress=progress)
        if sha256_of(part / name) != expected:
            (part / name).unlink(missing_ok=True)
            raise RuntimeError('预览模型校验失败，已删除不完整文件，请重新下载：' + name)
        progress.update(name, PREVIEW_SIZES[name], PREVIEW_SIZES[name])
    os.rename(part, target)
    print('实时预览模型已安装', flush=True)


def download_xasr_preview():
    base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'qingyin'
    target = base / 'preview/x-asr-streaming-zh-en'
    if all((target / f).is_file() for f in XASR_PREVIEW_SPEC['required']):
        print('X-ASR 实时预览模型已安装', flush=True)
        return
    if target.exists():
        raise RuntimeError('目标目录不完整，请先移走该目录后重试')
    part = base / 'preview/.downloads/x-asr-preview.part'
    part.mkdir(parents=True, exist_ok=True)
    archive = part / 'model.tar.bz2'
    print('正在下载 X-ASR 实时预览模型（约 134 MB），完成前不会启用', flush=True)
    fetch(XASR_PREVIEW_SPEC['url'], archive, progress=Progress())
    if sha256_of(archive) != XASR_PREVIEW_SPEC['sha256']:
        shutil.rmtree(part, ignore_errors=True)
        raise RuntimeError('预览模型校验失败，已删除不完整文件，请重新下载')
    folder = part / 'x-asr-streaming-zh-en'
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    _extract_sherpa(archive, folder, XASR_PREVIEW_SPEC)
    for required in XASR_PREVIEW_SPEC['required']:
        if not (folder / required).is_file():
            raise RuntimeError('预览模型文件不完整：' + required)
    os.rename(folder, target)
    shutil.rmtree(part, ignore_errors=True)
    print('X-ASR 实时预览模型已安装', flush=True)


def download(name):
    if name == PREVIEW:
        return download_preview()
    if name == XASR_PREVIEW:
        return download_xasr_preview()
    if name in SHERPA_MODELS:
        return download_sherpa(name)
    # The normal launcher is offline; explicit model downloads may go online.
    for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'):
        os.environ.pop(key, None)
    from huggingface_hub import HfApi, snapshot_download
    root = Path.home() / '.local/share/qingyin/models'
    target = root / name
    if (target / 'model.bin').is_file() and (target / 'config.json').is_file():
        print('模型已安装：' + name, flush=True)
        return
    if target.exists():
        raise RuntimeError('目标目录不完整，请先移走该目录后重试')
    repo = MODELS[name][0]
    revision = HfApi().model_info(repo).sha
    staging = root / '.downloads'
    staging.mkdir(parents=True, exist_ok=True)
    print('正在下载 ' + name + '，完成前不会出现在已安装模型列表', flush=True)
    with tempfile.TemporaryDirectory(dir=staging) as tmp:
        folder = Path(tmp) / name
        snapshot_download(
            repo_id=repo,
            revision=revision,
            local_dir=folder,
            max_workers=2,
            tqdm_class=hub_bar(Progress()),
            allow_patterns=['model.bin', 'config.json', 'tokenizer.json', 'preprocessor_config.json', 'vocabulary.*'],
        )
        for required in ('model.bin', 'config.json', 'tokenizer.json'):
            if not (folder / required).is_file():
                raise RuntimeError('模型文件不完整：' + required)
        os.rename(folder, target)
    print('模型已安装：' + name, flush=True)


if __name__ == '__main__':
    valid = (*MODELS, PREVIEW, XASR_PREVIEW)
    if len(sys.argv) != 2 or sys.argv[1] not in valid:
        raise SystemExit('请选择模型：' + ', '.join(valid))
    try:
        download(sys.argv[1])
    except Exception as exc:
        print('下载失败：' + str(exc), file=sys.stderr)
        sys.exit(1)
