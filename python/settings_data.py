"""Discovery, live runtime telemetry and atomic preference persistence; no model imports."""
import csv
import json
import os
from pathlib import Path
import subprocess
import tempfile
from model_catalog import installed


def graphics():
    output = subprocess.run(['nvidia-smi', '--query-gpu=uuid,name,memory.total,memory.free',
                             '--format=csv,noheader,nounits'], capture_output=True,
                            text=True, check=True, timeout=3).stdout
    return [dict(uuid=row[0].strip(), name=row[1].strip(), total=int(row[2]), free=int(row[3]))
            for row in csv.reader(output.splitlines()) if len(row) == 4]


def models(config):
    current = Path(config['model'])
    parents = {current.parent, Path.home() / '.local/share/qingyin/models'}
    found = {str(p) for parent in parents if parent.is_dir()
             for p in parent.iterdir() if p.is_dir() and installed(p)}
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


def service_status():
    """Query resident model service state and RSS without waking it."""
    try:
        out = subprocess.check_output(
            ['systemctl', '--user', 'show', 'qingyin-model.service',
             '-p', 'ActiveState', '-p', 'MemoryCurrent'],
            text=True, timeout=2, stderr=subprocess.DEVNULL,
        )
        info = dict(line.split('=', 1) for line in out.splitlines() if '=' in line)
        active = info.get('ActiveState') == 'active'
        raw_mem = info.get('MemoryCurrent', '')
        mem_mb = None
        if active and raw_mem.isdigit():
            val = int(raw_mem)
            if val < (1 << 60):
                mem_mb = val / (1024 * 1024)
        return dict(active=active, memory_mb=mem_mb)
    except Exception:
        return dict(active=False, memory_mb=None)


def learning_stats():
    """Return (total_rules, active_rules) from local learning store."""
    path = Path.home() / '.local/share/qingyin/private/learning.json'
    try:
        raw = json.loads(path.read_text())
        rules = raw.get('rules', [])
        active = sum(1 for r in rules if r.get('count', 0) >= 3)
        return len(rules), active
    except Exception:
        return 0, 0


def rime_installed():
    base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    return (base / 'qingyin/dictionaries/rime-ice/words.sqlite3').is_file()


def save(path, changes):
    config = json.loads(path.read_text())
    config.update(changes)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
            name = f.name
            json.dump(config, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    return config
