"""One-time download of verified model weights. Dictation never calls this."""
import hashlib
import os
from pathlib import Path
import tarfile
import tempfile
import urllib.request

NAME = 'sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8'
SHA256 = 'c0d5aa5f8eeb686032345e180bedf39319dc2e0556781c6264bcadba8328a6e1'
URL = f'https://github.com/k2-fsa/sherpa-onnx/releases/download/punctuation-models/{NAME}.tar.bz2'
root = Path.home() / '.local/share/qingyin/punctuation' / NAME
root.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    archive = Path(tmp) / 'model.tar.bz2'
    print('正在下载本地标点模型（约 62 MB）……', flush=True)
    urllib.request.urlretrieve(URL, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit('标点模型校验失败，未安装，请重新下载。')
    with tarfile.open(archive) as bundle:
        member = bundle.getmember(f'{NAME}/model.int8.onnx')
        with bundle.extractfile(member) as source:
            temporary = root / 'model.int8.onnx.tmp'
            temporary.write_bytes(source.read())
        os.replace(temporary, root / 'model.int8.onnx')
print('标点模型已安装，后续使用完全离线。')
