"""Explicit online installation only; never loads CUDA or changes preferences."""
import os
import sys
from pathlib import Path
import tempfile
sys.path.insert(0, str(Path(__file__).parent/'python'))
from model_catalog import MODELS


def download(name):
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
        snapshot_download(repo_id=repo, revision=revision, local_dir=folder, max_workers=2,
                          allow_patterns=['model.bin','config.json','tokenizer.json','preprocessor_config.json','vocabulary.*'])
        for required in ('model.bin','config.json','tokenizer.json'):
            if not (folder/required).is_file(): raise RuntimeError('模型文件不完整：'+required)
        os.rename(folder, target)
    print('模型已安装：'+name, flush=True)


if __name__=='__main__':
    if len(sys.argv)!=2 or sys.argv[1] not in MODELS:
        raise SystemExit('请选择模型：'+', '.join(MODELS))
    try: download(sys.argv[1])
    except Exception as exc:
        print('下载失败：'+str(exc), file=sys.stderr); sys.exit(1)
