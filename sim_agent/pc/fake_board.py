"""Local protocol fixture, never claims real-board timing validation."""
import argparse
import math
from pathlib import Path
import socket
import sys
import threading
import time
from protocol import STATE, COMMAND

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'board/tools'))
from proto_client import serve


def main(seconds, out, pause=True):
    worker = threading.Thread(target=serve, args=('127.0.0.1', out), daemon=True)
    worker.start()
    start = time.perf_counter()
    center = None
    first = None
    seq = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.bind(('127.0.0.1', 15001))
        udp.settimeout(.5)
        while time.perf_counter()-start < seconds:
            try:
                packet, peer = udp.recvfrom(4096)
            except (socket.timeout, ConnectionResetError):
                continue
            if len(packet) != STATE.size:
                continue
            magic, ack, sim_time, *fields = STATE.unpack(packet)
            if magic != b'RVS1':
                continue
            if center is None:
                center, first = fields[:7], time.perf_counter()
            t = time.perf_counter()-first
            q = center.copy()
            q[0] += .3*math.sin(2*math.pi*t/4)
            q[3] += .3*math.sin(2*math.pi*t/4)
            # Deliberate pause exercises the 100ms watchdog, then recovery.
            if pause and 6 <= t < 6.5:
                continue
            udp.sendto(COMMAND.pack(b'RVC1', seq, ack, int(t >= 2), *q, .08 if int(t/4)%2 == 0 else 0), peer)
            seq = (seq+1)&0xffffffff
    worker.join(timeout=2)
    print('FAKE_BOARD_COMPLETE replies=%d (local fixture only)' % seq, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--seconds', type=float, default=20)
    p.add_argument('--out', default='sim_agent/runs/local-images')
    p.add_argument('--no-pause', action='store_true')
    a = p.parse_args()
    main(a.seconds, a.out, not a.no_pause)
