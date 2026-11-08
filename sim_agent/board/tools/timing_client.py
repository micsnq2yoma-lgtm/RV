"""Board timing workload: render/ping, optionally exercising local interpolation."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import time


def main(mode, count):
    os.sched_setaffinity(0, {0})
    rt = None
    if mode == 'trajectory':
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'agent'))
        from transport import RTClient
        rt = RTClient()
    try:
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('0.0.0.0', 15002))
            listener.listen(1)
            listener.settimeout(60)
            print(json.dumps({'tcp_listening': 15002, 'workload': mode, 'count': count}), flush=True)
            conn, _ = listener.accept()
            with conn, conn.makefile('rb') as stream:
                conn.settimeout(30)
                if rt:
                    for attempt in range(50):
                        try:
                            rt.call()
                            break
                        except RuntimeError as e:
                            if 'status=2' not in str(e):
                                raise
                            time.sleep(.1)
                    else:
                        raise RuntimeError('no simulation state')
                for i in range(count):
                    if rt:
                        offset = .15 if i % 2 else -.15
                        goal = [offset, 0, 0, -1.57079+offset, 0, 1.57079, -.7853]
                        state = rt.segment(goal, .08 if i % 2 else 0., 4.)
                        print(json.dumps({'trajectory_generation': state['generation'], 'duration_s': 4.}), flush=True)
                    request = dict(id=i, op='ping' if mode == 'ping' else 'render', camera='top', w=640, h=480)
                    start = time.monotonic()
                    conn.sendall((json.dumps(request)+'\n').encode())
                    line = stream.readline(4*1024*1024)
                    if not line.endswith(b'\n'):
                        raise RuntimeError('truncated or oversized response')
                    reply = json.loads(line)
                    if reply.get('id') != i or 'error' in reply:
                        raise RuntimeError('response id mismatch or error')
                    encoded = reply.pop('jpeg_b64', None)
                    print(json.dumps({'id': i, 'elapsed_s': time.monotonic()-start,
                                      'jpeg_chars': len(encoded) if encoded else 0}), flush=True)
                    time.sleep(5)
    finally:
        if rt:
            rt.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['render', 'ping', 'trajectory'])
    parser.add_argument('count', type=int, nargs='?', default=118)
    args = parser.parse_args()
    if args.count < 1:
        parser.error('count must be positive')
    main(args.mode, args.count)
