"""Select and check a physical GPU before importing any CUDA inference library."""
import csv
import json
import os
from pathlib import Path
import subprocess


def prepare_cuda(config=None):
    if config is None:
        path = Path.home() / '.config/qingyin/config.json'
        config = json.loads(path.read_text()) if path.exists() else {}
    try:
        output = subprocess.run(
            ['nvidia-smi', '--query-gpu=uuid,name,memory.total,memory.free',
             '--format=csv,noheader,nounits'],
            check=True, capture_output=True, text=True, timeout=3).stdout
        cards = []
        for row in csv.reader(output.splitlines()):
            uuid, name, total, free = [item.strip() for item in row]
            cards.append(dict(uuid=uuid, name=name, total=int(total), free=int(free)))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise RuntimeError('无法确认显卡状态，已阻止 CUDA 模型加载；可在设置中改用 CPU') from exc
    preferred = config.get('gpu_uuid', '')
    # Respect an existing visibility restriction; a pinned UUID must also be allowed.
    visible = os.environ.get('CUDA_VISIBLE_DEVICES')
    if visible is not None:
        allowed = visible.split(',')
        cards = [card for index, card in enumerate(cards)
                 if card['uuid'] in allowed or str(index) in allowed]
    if preferred:
        cards = [card for card in cards if card['uuid'] == preferred]
    if not cards:
        raise RuntimeError('指定的识别显卡不可用，已阻止 CUDA 模型加载；不会自动切换到其他显卡')
    card = max(cards, key=lambda item: (item['total'], item['free']))
    required = max(6144, int(config.get('gpu_min_free_mib', 6144)))
    if card['free'] < required:
        raise RuntimeError(f"识别显卡剩余显存不足（{card['free']} MiB，需要至少 {required} MiB），已停止加载；请关闭占用显存的软件或改用 CPU")
    os.environ['CUDA_VISIBLE_DEVICES'] = card['uuid']
    return card
