"""Board TCP service requester. Raw images stay out of JSON logs."""
import argparse
import base64
import json
from pathlib import Path
import socket
import time


def serve(bind, out, timeout=120):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((bind, 15002))
        listener.listen(1)
        listener.settimeout(timeout)
        print(json.dumps({'tcp_listening': 15002}), flush=True)
        conn, _ = listener.accept()
        with conn, conn.makefile('rb') as stream:
            conn.settimeout(30)
            requests = [{'op': 'hello'}, {'op': 'objects'},
                        {'op': 'render', 'camera': 'top', 'w': 640, 'h': 480},
                        {'op': 'render', 'camera': 'wrist', 'w': 640, 'h': 480},
                        {'op': 'reset', 'seed': 1}, {'op': 'objects'}]
            for i, request in enumerate(requests):
                start = time.perf_counter()
                conn.sendall((json.dumps({'id': i, **request})+'\n').encode())
                line = stream.readline(4*1024*1024)
                if not line.endswith(b'\n'):
                    raise RuntimeError('truncated/oversized response')
                reply = json.loads(line)
                if reply.get('id') != i or 'error' in reply:
                    raise RuntimeError('response ID mismatch or service error: '+str(reply))
                elapsed = time.perf_counter()-start
                if request['op'] == 'render':
                    image = base64.b64decode(reply.pop('jpeg_b64'), validate=True)
                    if not image.startswith(b'\xff\xd8') or not image.endswith(b'\xff\xd9'):
                        raise RuntimeError('not a complete JPEG')
                    (out/(request['camera']+'.jpg')).write_bytes(image)
                    reply['jpeg_bytes'] = len(image)
                print(json.dumps({'request': request, 'elapsed_s': elapsed, 'reply': reply}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bind', default='0.0.0.0')
    p.add_argument('--out', default='images')
    a = p.parse_args()
    serve(a.bind, a.out)
