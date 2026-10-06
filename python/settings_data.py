"""Discovery and atomic preference persistence; no model imports."""
import csv
import json
import os
from pathlib import Path
import subprocess
import tempfile


def graphics():
    output = subprocess.run(['nvidia-smi', '--query-gpu=uuid,name,memory.total,memory.free',
                             '--format=csv,noheader,nounits'], capture_output=True,
                            text=True, check=True, timeout=3).stdout
    return [dict(uuid=row[0].strip(), name=row[1].strip(), total=int(row[2]), free=int(row[3]))
            for row in csv.reader(output.splitlines()) if len(row) == 4]


def models(config):
    current = Path(config['model'])
    parents = {current.parent, Path.home()/'.local/share/qingyin/models'}
    found = {str(p) for parent in parents if parent.is_dir()
             for p in parent.iterdir() if p.is_dir() and (p/'model.bin').is_file()}
    found.add(str(current))
    return [Path(p) for p in sorted(found)]


def microphones():
    nodes = json.loads(subprocess.check_output(['pw-dump'], timeout=3))
    result = [(None, '系统默认麦克风')]
    for node in nodes:
        props = node.get('info', {}).get('props', {})
        if props.get('media.class') == 'Audio/Source' and props.get('node.name'):
            result.append((props['node.name'], props.get('node.description', props['node.name'])))
    return result


def save(path, changes):
    config = json.loads(path.read_text())
    config.update(changes)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
            name = f.name
            json.dump(config, f, ensure_ascii=False, indent=2)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name): os.unlink(name)
    return config
