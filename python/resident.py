"""Private resident model & preview broker with idle auto-unload. No recording or network."""
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
SOCKET = Path(os.environ['XDG_RUNTIME_DIR']) / 'qingyin/model.sock'
PREVIEW_SOCKET = Path(os.environ['XDG_RUNTIME_DIR']) / 'qingyin/preview.sock'
DEFAULT_IDLE_UNLOAD = 300


def line(connection):
    data = bytearray()
    while len(data) < 65536:
        part = connection.recv(1)
        if not part:
            raise ConnectionError('session disconnected')
        if part == b'\n':
            return bytes(data)
        data.extend(part)
    raise ValueError('request too large')


def kill(worker):
    if worker:
        try:
            worker.kill()
            worker.wait(timeout=5)
        except Exception:
            pass


def reply(worker, connection):
    data = bytearray()
    while len(data) < 65536:
        ready, _, _ = select.select([worker.stdout, connection], [], [], 1)
        if connection in ready and not connection.recv(1, socket.MSG_PEEK):
            raise ConnectionError('session canceled')
        if worker.stdout in ready:
            part = os.read(worker.stdout.fileno(), 1)
            if not part:
                raise RuntimeError('识别进程意外退出，模型已释放')
            if part == b'\n':
                return bytes(data)
            data.extend(part)
    raise RuntimeError('识别进程返回数据过长')


def _read_default_idle() -> float:
    env_val = os.environ.get('QINGYIN_IDLE_UNLOAD_SECONDS')
    if env_val is not None:
        try:
            return max(0.0, float(env_val))
        except ValueError:
            pass
    try:
        cfg = json.loads((Path.home() / '.config/qingyin/config.json').read_text())
        if 'idle_unload_seconds' in cfg:
            return max(0.0, float(cfg['idle_unload_seconds']))
    except (OSError, ValueError):
        pass
    return float(DEFAULT_IDLE_UNLOAD)


class PreviewBroker:
    """Keep the lightweight streaming preview recognizer warm across utterances."""

    def __init__(self, touch_activity):
        self._lock = threading.Lock()
        self._worker = None
        self._stop = threading.Event()
        self._touch = touch_activity
        self._thread = None

    def start(self, sock_path: Path):
        self._sock_path = sock_path
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def unload(self):
        with self._lock:
            kill(self._worker)
            self._worker = None

    def stop(self):
        self._stop.set()
        self.unload()
        if self._thread:
            self._thread.join(timeout=2)
        if hasattr(self, '_sock_path'):
            self._sock_path.unlink(missing_ok=True)

    def _ensure_worker(self):
        if self._worker is None or self._worker.poll() is not None:
            kill(self._worker)
            self._worker = subprocess.Popen(
                [sys.executable, str(ROOT / 'python/preview.py'), '--resident'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,
                bufsize=0,
            )
            ready = self._worker.stdout.readline()
            if not ready or not json.loads(ready).get('ready'):
                kill(self._worker)
                self._worker = None
                raise RuntimeError('实时预览服务启动失败')
        return self._worker

    def _loop(self):
        self._sock_path.parent.mkdir(parents=True, exist_ok=True)
        self._sock_path.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self._sock_path))
            os.chmod(self._sock_path, 0o600)
            server.listen(2)
            while not self._stop.is_set():
                ready, _, _ = select.select([server], [], [], 0.5)
                if not ready:
                    continue
                connection, _ = server.accept()
                with connection:
                    self._handle(connection)

    def _handle(self, connection):
        self._touch()
        try:
            req = line(connection)
            with self._lock:
                worker = self._ensure_worker()
                worker.stdin.write(req + b'\n')
                worker.stdin.flush()
                while not self._stop.is_set():
                    ready, _, _ = select.select([worker.stdout, connection], [], [], 0.5)
                    if connection in ready:
                        if not connection.recv(1, socket.MSG_PEEK):
                            # Client stopped recording or canceled; tell resident preview to end this stream.
                            worker.stdin.write(b'{"stop":true}\n')
                            worker.stdin.flush()
                            # Drain until {"done":true} so worker stays clean for next utterance.
                            deadline = time.monotonic() + 2.0
                            while time.monotonic() < deadline:
                                r, _, _ = select.select([worker.stdout], [], [], 0.2)
                                if not r:
                                    break
                                msg = worker.stdout.readline()
                                if not msg or json.loads(msg).get('done'):
                                    break
                            else:
                                kill(worker)
                                self._worker = None
                            return
                        connection.recv(4096)
                    if worker.stdout in ready:
                        msg = worker.stdout.readline()
                        if not msg:
                            kill(worker)
                            self._worker = None
                            return
                        parsed = json.loads(msg)
                        if parsed.get('done'):
                            return
                        if 'text' in parsed:
                            connection.sendall(msg)
                            self._touch()
        except Exception:
            with self._lock:
                kill(self._worker)
                self._worker = None


def serve(idle_unload_seconds=None, exit_on_idle=None):
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    SOCKET.parent.mkdir(parents=True, exist_ok=True)
    SOCKET.unlink(missing_ok=True)
    worker = None
    signature = None
    idle_timeout = _read_default_idle() if idle_unload_seconds is None else max(0.0, float(idle_unload_seconds))
    should_exit = (os.environ.get('QINGYIN_EXIT_ON_IDLE') == '1') if exit_on_idle is None else bool(exit_on_idle)
    last_used = [time.monotonic()]

    def touch():
        last_used[0] = time.monotonic()

    preview_broker = PreviewBroker(touch)
    preview_sock = SOCKET.with_name('preview.sock')
    if (ROOT / 'python/preview.py').is_file():
        preview_broker.start(preview_sock)

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(SOCKET))
        os.chmod(SOCKET, 0o600)
        server.listen(2)
        try:
            while True:
                ready, _, _ = select.select([server], [], [], 1.0)
                if not ready:
                    if idle_timeout > 0 and (time.monotonic() - last_used[0]) >= idle_timeout:
                        has_any = worker is not None or preview_broker._worker is not None
                        if has_any:
                            kill(worker)
                            worker = None
                            signature = None
                            preview_broker.unload()
                            print('常驻模型空闲超时，已自动释放内存', file=sys.stderr, flush=True)
                        if should_exit:
                            return
                    continue

                connection, _ = server.accept()
                touch()
                with connection:
                    try:
                        hello = json.loads(line(connection))
                        if 'idle_unload_seconds' in hello and idle_unload_seconds is None:
                            idle_timeout = max(0.0, float(hello['idle_unload_seconds']))
                        key = (
                            hello['model'],
                            hello['device'],
                            hello['compute'],
                            hello.get('gpu_uuid', ''),
                            hello.get('gpu_min_free_mib', 6144),
                        )
                        if key != signature or worker is None or worker.poll() is not None:
                            kill(worker)
                            worker = None
                            worker = subprocess.Popen(
                                [sys.executable, str(ROOT / 'python/asr.py'), *key[:3]],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=sys.stderr,
                                bufsize=0,
                            )
                            ready_msg = reply(worker, connection)
                            if not json.loads(ready_msg).get('ready'):
                                connection.sendall(ready_msg + b'\n')
                                kill(worker)
                                worker = None
                                continue
                            signature = key
                        connection.sendall(b'{"ready":true,"resident":true}\n')
                        job = line(connection)
                        touch()
                        worker.stdin.write(job + b'\n')
                        worker.stdin.flush()
                        result = reply(worker, connection)
                        touch()
                        connection.sendall(result + b'\n')
                        if 'error' in json.loads(result):
                            kill(worker)
                            worker = None
                    except Exception as exc:
                        kill(worker)
                        worker = None
                        signature = None
                        try:
                            connection.sendall(
                                json.dumps({'error': '常驻识别连接中断，模型已释放；请重试'}, ensure_ascii=False).encode()
                                + b'\n'
                            )
                        except OSError:
                            pass
                        print('常驻模型会话已结束：' + type(exc).__name__, file=sys.stderr, flush=True)
        finally:
            preview_broker.stop()
            kill(worker)
            SOCKET.unlink(missing_ok=True)


def bridge():
    config = json.loads((Path.home() / '.config/qingyin/config.json').read_text())
    sock_path = Path(os.environ['XDG_RUNTIME_DIR']) / 'qingyin/model.sock'
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        try:
            connection.connect(str(sock_path))
        except (FileNotFoundError, ConnectionRefusedError):
            subprocess.run(['systemctl', '--user', 'start', 'qingyin-model.service'], check=True, capture_output=True, timeout=5)
            for _ in range(100):
                try:
                    connection.connect(str(sock_path))
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    time.sleep(0.02)
            else:
                raise RuntimeError('常驻模型服务无法连接')
        hello = dict(
            model=sys.argv[1],
            device=sys.argv[2],
            compute=sys.argv[3],
            gpu_uuid=config.get('gpu_uuid', ''),
            gpu_min_free_mib=config.get('gpu_min_free_mib', 6144),
            idle_unload_seconds=config.get('idle_unload_seconds', DEFAULT_IDLE_UNLOAD),
        )
        connection.sendall(json.dumps(hello).encode() + b'\n')
        ready = line(connection)
        print(ready.decode(), flush=True)
        if not json.loads(ready).get('ready'):
            return
        job = sys.stdin.readline()
        if not job:
            return
        connection.sendall(job.encode())
        print(line(connection).decode(), flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['serve']:
        serve()
    else:
        try:
            bridge()
        except Exception as exc:
            print(json.dumps({'error': '常驻模型连接失败，请关闭常驻模式后重试：' + str(exc)}, ensure_ascii=False), flush=True)
            sys.exit(1)
