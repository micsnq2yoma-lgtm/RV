"""PC initiates UDP and TCP; no inbound Windows listening ports."""
import argparse
import base64
import io
import json
from pathlib import Path
import queue
import socket
import threading
import time

import mujoco
import numpy as np
from PIL import Image
from protocol import STATE, command_values

OBJECTS = ['red_cube', 'green_cube', 'blue_cube', 'left_tray', 'right_tray']
HOME = [0, 0, 0, -1.57079, 0, 1.57079, -0.7853]


def load_scene():
    spec = mujoco.MjSpec.from_file(str(Path(__file__).with_name('scene_tabletop.xml')))
    spec.body('hand').add_camera(name='wrist', pos=[0, -.15, .1], quat=[0, 1, 0, 0], fovy=90)
    return spec.compile()


class Simulator:
    def __init__(self, board_ip):
        self.model = load_scene()
        self.data = mujoco.MjData(self.model)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.jobs = queue.Queue(maxsize=8)
        self.address = (board_ip, 15001)
        self.qadr = [self.model.joint('joint%d' % i).qposadr[0] for i in range(1, 8)]
        self.vadr = [self.model.joint('joint%d' % i).dofadr[0] for i in range(1, 8)]
        self.fingers = [self.model.joint('finger_joint%d' % i).qposadr[0] for i in (1, 2)]
        self.ranges = np.array([self.model.joint('joint%d' % i).range for i in range(1, 8)])
        self.steps = 0
        self.wall_start = self.wall_end = None
        self.seq = 0
        self.last_cmd_seq = 0
        self.sent = self.received = self.invalid = self.timeouts = self.late = 0
        self.rtts = []
        self.expired_count = self.reset_discarded = 0
        self.pending = {}
        self.last_ack = None
        self.last_rx = None
        self.holding = True
        self.reset_flag = True
        self.reset(None)
        self.q_min = self.q_max = self.data.qpos[self.qadr].copy()
        self.gripper_min = self.gripper_max = float(sum(self.data.qpos[self.fingers]))

    def reset(self, seed):
        # Called only in the physics thread (initial reset precedes worker startup).
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[self.qadr] = HOME
        self.data.qpos[self.fingers] = .04
        self.data.ctrl[:] = HOME + [255]
        rng = np.random.default_rng(seed)
        for i, name in enumerate(OBJECTS[:3]):
            joint = self.model.body(name).jntadr[0]
            adr = self.model.jnt_qposadr[joint]
            xy = [(.68, -.12), (.72, .23), (.68, .12)][i]
            jitter = rng.uniform(-.015, .015, 2) if seed is not None else np.zeros(2)
            self.data.qpos[adr:adr+7] = [*(np.array(xy)+jitter), .025, 1, 0, 0, 0]
        mujoco.mj_forward(self.model, self.data)
        self.last_rx = None
        self.holding = True
        self.reset_flag = True
        self.watchdog_active = True
        self.last_ack = None
        self.reset_discarded += len(self.pending)
        self.pending.clear()
        self.target = np.array(HOME, dtype=float)

    def service(self, request, renderer, snapshot):
        op = request.get('op')
        if op == 'hello':
            return dict(sim='mujoco', version=mujoco.__version__, robot='panda', cameras=['top', 'wrist'], table_z=0.0)
        if op == 'ping':
            return {'t': time.time()}
        if op == 'reset':
            done = queue.Queue(maxsize=1)
            self.jobs.put((request.get('seed'), done), timeout=1)
            return done.get(timeout=5)
        with self.lock:
            # Brief state copy only; OpenGL and JPEG encoding never hold physics lock.
            snapshot.qpos[:] = self.data.qpos
            snapshot.qvel[:] = self.data.qvel
            snapshot.time = self.data.time
        mujoco.mj_forward(self.model, snapshot)
        if op == 'objects':
            return {'objects': [dict(name=n, pos=snapshot.body(n).xpos.tolist(),
                                    quat=snapshot.body(n).xquat.tolist()) for n in OBJECTS]}
        if op == 'render':
            camera = request.get('camera', 'top')
            if camera not in ('top', 'wrist') or request.get('w', 640) != 640 or request.get('h', 480) != 480:
                raise ValueError('render requires top/wrist and 640x480')
            renderer.update_scene(snapshot, camera=camera)
            pixels = renderer.render()
            encoded = io.BytesIO()
            Image.fromarray(pixels).save(encoded, format='JPEG', quality=80)
            cam = self.model.camera(camera)
            return dict(jpeg_b64=base64.b64encode(encoded.getvalue()).decode(), w=640, h=480,
                        fovy=float(cam.fovy[0]), cam_pos=snapshot.cam_xpos[cam.id].tolist(),
                        cam_xmat=snapshot.cam_xmat[cam.id].tolist())
        raise ValueError('unknown op')

    def tcp_worker(self):
        # Context is created and destroyed on this rendering thread.
        try:
            with mujoco.Renderer(self.model, height=480, width=640) as renderer:
                snapshot = mujoco.MjData(self.model)
                while not self.stop.is_set():
                    try:
                        with socket.create_connection((self.address[0], 15002), timeout=2) as conn:
                            conn.settimeout(1)
                            buffer = b''
                            while not self.stop.is_set():
                                try:
                                    data = conn.recv(65536)
                                except socket.timeout:
                                    continue
                                if not data:
                                    break
                                buffer += data
                                if len(buffer) > 65536:
                                    raise ValueError('request too large')
                                while b'\n' in buffer:
                                    line, buffer = buffer.split(b'\n', 1)
                                    request = json.loads(line)
                                    try:
                                        reply = self.service(request, renderer, snapshot)
                                    except (ValueError, queue.Empty, queue.Full) as e:
                                        reply = {'error': str(e)}
                                    conn.sendall((json.dumps({'id': request.get('id'), **reply})+'\n').encode())
                    except (OSError, ValueError) as e:
                        print(json.dumps({'tcp_error': type(e).__name__}), flush=True)
                    self.stop.wait(2)
        except Exception as e:
            print(json.dumps({'render_worker_failed': str(e)}), flush=True)

    def hold(self):
        self.target = self.data.qpos[self.qadr].copy()
        self.data.ctrl[:7] = self.target
        self.data.ctrl[7] = np.clip(sum(self.data.qpos[self.fingers])/.08*255, 0, 255)

    def stats(self, final=False):
        values = np.array(self.rtts)*1000
        sample_time = self.wall_end or time.perf_counter()
        expired = sum(sample_time-t > .1 for t in self.pending.values())
        inflight = len(self.pending)-expired
        lost = self.expired_count+expired
        return dict(final=final, physics_steps=self.steps,
                    q_min=self.q_min.tolist(), q_max=self.q_max.tolist(),
                    gripper_min=self.gripper_min, gripper_max=self.gripper_max,
                    wall_seconds=(self.wall_end or time.perf_counter())-self.wall_start if self.wall_start else 0,
                    sent=self.sent, received=self.received, invalid=self.invalid,
                    no_reply=self.sent-self.received, pending_expired=expired,
                    loss_percent=100*lost/max(1, self.sent-inflight-self.reset_discarded),
                    lost=lost, inflight=inflight, reset_discarded=self.reset_discarded,
                    timeout_transitions=self.timeouts, late_steps=self.late,
                    sim_time=self.data.time, rtt_samples=len(values),
                    rtt_ms_p50=float(np.percentile(values, 50)) if len(values) else None,
                    rtt_ms_p99=float(np.percentile(values, 99)) if len(values) else None,
                    rtt_ms_max=float(max(values)) if len(values) else None)

    def run(self, seconds, headless):
        worker = threading.Thread(target=self.tcp_worker, daemon=True)
        viewer = None
        timer_active = False
        if __import__('os').name == 'nt':
            import ctypes
            timer_active = ctypes.windll.winmm.timeBeginPeriod(1) == 0
        try:
            if not headless:
                from mujoco import viewer as mj_viewer
                viewer = mj_viewer.launch_passive(self.model, self.data)
            # GLFW initialization is process-global: initialize the viewer first,
            # then create the offscreen context on its own rendering thread.
            worker.start()
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.connect(self.address)  # Only replies from the board endpoint are accepted.
                udp.settimeout(.05)
                incoming = queue.Queue(maxsize=2048)
                def receive():
                    while not self.stop.is_set():
                        try:
                            packet = udp.recv(65536)
                            arrived = time.perf_counter()
                            incoming.put_nowait((packet, arrived))
                        except (socket.timeout, ConnectionResetError, queue.Full):
                            continue
                        except OSError:
                            break
                receiver = threading.Thread(target=receive, daemon=True)
                receiver.start()
                start = due = last_print = last_view = time.perf_counter()
                self.wall_start = start
                step = 0
                while time.perf_counter()-start < seconds and (viewer is None or viewer.is_running()):
                    now = time.perf_counter()
                    if now < due:
                        time.sleep(due-now)
                    now = time.perf_counter()
                    if now-due > .002:
                        self.late += 1
                    # Schedule from actual start: no catch-up stepping.
                    due = now + .002 if now-due > .002 else due + .002
                    with self.lock:
                        while not self.jobs.empty():
                            seed, done = self.jobs.get_nowait()
                            self.reset(seed)
                            done.put({'ok': True})
                        for _ in range(256):
                            try:
                                packet, arrival = incoming.get_nowait()
                            except queue.Empty:
                                break
                            try:
                                seq, ack, mode, values = command_values(packet)
                            except ValueError:
                                self.invalid += 1
                                continue
                            sent_at = self.pending.get(ack)
                            if sent_at is None or arrival-sent_at > .1 or (self.last_ack is not None and not 0 < ((ack-self.last_ack)&0xffffffff) < 0x80000000):
                                self.invalid += 1
                                continue
                            del self.pending[ack]
                            self.last_ack = ack
                            self.received += 1
                            self.rtts.append(arrival-sent_at)
                            if self.watchdog_active:
                                print(json.dumps({'command_recovered': True, 'mode': mode}), flush=True)
                            self.watchdog_active = False
                            self.last_rx = arrival
                            self.last_cmd_seq = seq
                            if mode == 0:
                                self.hold()
                            else:
                                # Position clamp + conservative target slew cap, 2 rad/s.
                                target = np.clip(values[:7], self.ranges[:, 0], self.ranges[:, 1])
                                self.target = target
                                self.data.ctrl[7] = np.clip(values[7]/.08*255, 0, 255)
                            self.holding = mode == 0
                        # One physics-step guard margin to target <=100ms watchdog activation.
                        if self.last_rx is None or time.perf_counter()-self.last_rx >= .098:
                            if not self.watchdog_active and self.last_rx is not None:
                                self.timeouts += 1
                                print(json.dumps({'watchdog': 'hold', 'age_ms': (time.perf_counter()-self.last_rx)*1000,
                                                  'already_holding': self.holding}), flush=True)
                            if not self.holding:
                                self.hold()
                            self.holding = True
                            self.watchdog_active = True
                        self.data.ctrl[:7] += np.clip(self.target-self.data.ctrl[:7], -.004, .004)
                        mujoco.mj_step(self.model, self.data)
                        step += 1
                        self.steps += 1
                        if step % 2 == 0:
                            self.q_min = np.minimum(self.q_min, self.data.qpos[self.qadr])
                            self.q_max = np.maximum(self.q_max, self.data.qpos[self.qadr])
                            width = float(sum(self.data.qpos[self.fingers]))
                            self.gripper_min = min(self.gripper_min, width)
                            self.gripper_max = max(self.gripper_max, width)
                            timed_out = self.last_rx is None or time.perf_counter()-self.last_rx >= .098
                            flags = int(timed_out) | (2 if self.reset_flag else 0)
                            packet = STATE.pack(b'RVS1', self.seq, self.data.time,
                                *self.data.qpos[self.qadr], *self.data.qvel[self.vadr],
                                sum(self.data.qpos[self.fingers]), flags, self.last_cmd_seq)
                            try:
                                sent_at = time.perf_counter()
                                udp.send(packet)
                            except ConnectionResetError:
                                continue
                            self.pending[self.seq] = sent_at
                            self.seq = (self.seq+1)&0xffffffff
                            self.sent += 1
                            self.reset_flag = False
                            if len(self.pending) > 1024:
                                kept = {s: t for s, t in self.pending.items() if now-t < 1}
                                self.expired_count += len(self.pending)-len(kept)
                                self.pending = kept
                    if viewer and now-last_view >= 1/30:
                        viewer.sync()
                        last_view = now
                    if now-last_print >= 5:
                        print(json.dumps(self.stats()), flush=True)
                        last_print = now
        except KeyboardInterrupt:
            pass
        finally:
            self.wall_end = time.perf_counter()
            self.stop.set()
            if worker.is_alive():
                worker.join(timeout=5)
            if viewer:
                viewer.close()
            if timer_active:
                ctypes.windll.winmm.timeEndPeriod(1)
            print(json.dumps(self.stats(final=True)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--board-ip', default='192.168.50.2')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--seconds', type=float, default=600)
    args = parser.parse_args()
    Simulator(args.board_ip).run(args.seconds, args.headless)
