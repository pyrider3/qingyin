"""Private resident model broker and session bridge. No recording or network."""
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SOCKET = Path(os.environ['XDG_RUNTIME_DIR'])/'qingyin/model.sock'


def line(connection):
    data = bytearray()
    while len(data) < 65536:
        part = connection.recv(1)
        if not part: raise ConnectionError('session disconnected')
        if part == b'\n': return bytes(data)
        data.extend(part)
    raise ValueError('request too large')


def kill(worker):
    if worker:
        worker.kill(); worker.wait(timeout=5)


def reply(worker, connection):
    data = bytearray()
    while len(data) < 65536:
        ready, _, _ = select.select([worker.stdout, connection], [], [], 1)
        if connection in ready and not connection.recv(1, socket.MSG_PEEK):
            raise ConnectionError('session canceled')
        if worker.stdout in ready:
            part = os.read(worker.stdout.fileno(), 1)
            if not part: raise RuntimeError('识别进程意外退出，模型已释放')
            if part == b'\n': return bytes(data)
            data.extend(part)
    raise RuntimeError('识别进程返回数据过长')


def serve():
    SOCKET.parent.mkdir(parents=True, exist_ok=True)
    SOCKET.unlink(missing_ok=True)
    worker = None; signature = None
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(SOCKET)); os.chmod(SOCKET, 0o600); server.listen(2)
        try:
            while True:
                connection, _ = server.accept()
                with connection:
                    try:
                        hello = json.loads(line(connection))
                        key = (hello['model'], hello['device'], hello['compute'], hello.get('gpu_uuid',''), hello.get('gpu_min_free_mib',6144))
                        if key != signature or worker is None or worker.poll() is not None:
                            kill(worker); worker = None
                            worker = subprocess.Popen([sys.executable, str(ROOT/'python/asr.py'), *key[:3]],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr, bufsize=0)
                            ready = reply(worker, connection)
                            if not json.loads(ready).get('ready'):
                                connection.sendall(ready+b'\n');kill(worker);worker=None;continue
                            signature = key
                        connection.sendall(b'{"ready":true,"resident":true}\n')
                        job = line(connection)
                        worker.stdin.write(job+b'\n'); worker.stdin.flush()
                        result = reply(worker, connection)
                        connection.sendall(result+b'\n')
                        if 'error' in json.loads(result): kill(worker);worker=None
                    except Exception as exc:
                        kill(worker); worker=None; signature=None
                        try: connection.sendall(json.dumps({'error':'常驻识别连接中断，模型已释放；请重试'},ensure_ascii=False).encode()+b'\n')
                        except OSError: pass
                        print('常驻模型会话已结束：'+type(exc).__name__, file=sys.stderr, flush=True)
        finally:
            kill(worker); SOCKET.unlink(missing_ok=True)


def bridge():
    config = json.loads((Path.home()/'.config/qingyin/config.json').read_text())
    subprocess.run(['systemctl','--user','start','qingyin-model.service'],check=True, capture_output=True, timeout=5)
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
        for _ in range(100):
            try: connection.connect(str(SOCKET));break
            except (FileNotFoundError,ConnectionRefusedError):time.sleep(.05)
        else:raise RuntimeError('常驻模型服务无法连接')
        hello=dict(model=sys.argv[1],device=sys.argv[2],compute=sys.argv[3],gpu_uuid=config.get('gpu_uuid',''),gpu_min_free_mib=config.get('gpu_min_free_mib',6144))
        connection.sendall(json.dumps(hello).encode()+b'\n')
        ready=line(connection);print(ready.decode(),flush=True)
        if not json.loads(ready).get('ready'):return
        job=sys.stdin.readline()
        if not job:return
        connection.sendall(job.encode());print(line(connection).decode(),flush=True)


if __name__=='__main__':
    if sys.argv[1:]==['serve']:serve()
    else:
        try:bridge()
        except Exception as exc:
            print(json.dumps({'error':'常驻模型连接失败，请关闭常驻模式后重试：'+str(exc)},ensure_ascii=False),flush=True)
            sys.exit(1)
