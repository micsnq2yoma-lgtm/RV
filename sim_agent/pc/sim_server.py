"""PC initiates UDP and TCP; no inbound Windows listening ports."""
import argparse
from contextlib import ExitStack
import base64
import io
import json
from pathlib import Path
import queue
import multiprocessing as mp
import socket
import threading
import time

import mujoco
import numpy as np
from PIL import Image
from protocol import STATE, command_values

OBJECTS = ['red_cube', 'green_cube', 'blue_cube', 'left_tray', 'right_tray']
HOME = [0, 0, 0, -1.57079, 0, 1.57079, -0.7853]


def timing(activity, start, **detail):
    elapsed = time.perf_counter()-start
    if elapsed > .020:
        print(json.dumps(dict(event='slow', activity=activity, milliseconds=elapsed*1000, **detail)), flush=True)
    return elapsed


def load_scene():
    spec = mujoco.MjSpec.from_file(str(Path(__file__).with_name('scene_tabletop.xml')))
    spec.body('hand').add_camera(name='wrist', pos=[0, -.15, .1], quat=[0, 1, 0, 0], fovy=90)
    # Use compiled fingertip pad extents: tip minus 1 cm, centered between fingers.
    reference = spec.compile()
    finger = reference.body('left_finger').id
    pads = [g for g in range(reference.ngeom) if reference.geom_bodyid[g] == finger
            and reference.geom_type[g] == mujoco.mjtGeom.mjGEOM_BOX]
    tip = reference.body_pos[finger, 2] + max(reference.geom_pos[g, 2]+reference.geom_size[g, 2] for g in pads)
    spec.body('hand').add_site(name='tcp', pos=[0, 0, float(tip)-.01], size=[.005]*3, rgba=[1, 0, 1, 1])
    return spec.compile()


def export_kinematics(model):
    bodies = []
    body = model.body('hand').id
    while body:
        bodies.append(body); body = int(model.body_parentid[body])
    chain = []
    for b in reversed(bodies):
        joints = []
        for j in range(int(model.body_jntadr[b]), int(model.body_jntadr[b]+model.body_jntnum[b])):
            if model.jnt_type[j] != mujoco.mjtJoint.mjJNT_HINGE:
                raise ValueError('only hinge joints supported in arm chain')
            joints.append(dict(name=model.joint(j).name, pos=model.jnt_pos[j].tolist(),
                               axis=model.jnt_axis[j].tolist(), range=model.jnt_range[j].tolist(),
                               qpos0=float(model.qpos0[model.jnt_qposadr[j]])))
        chain.append(dict(name=model.body(b).name, pos=model.body_pos[b].tolist(),
                          quat=model.body_quat[b].tolist(), joints=joints))
    site = model.site('tcp').id
    return dict(chain=chain, tcp=dict(body='hand', pos=model.site_pos[site].tolist(),
                                     quat=model.site_quat[site].tolist()))


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
        self.simulation_stalls = self.board_silence = self.snapshot_skips = 0
        self.send_gap_max = self.physics_gap_max = 0.
        self.shared = self.remote_jobs = self.render_ready = None
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
        self.seq=self.sent=self.received=self.invalid=self.expired_count=self.reset_discarded=0
        self.last_cmd_seq=0;self.rtts.clear()
        self.target = np.array(HOME, dtype=float)

    def service(self, request, renderer, snapshot):
        if not isinstance(request,dict):raise ValueError('request must be a JSON object')
        op = request.get('op')
        if op=='reset' and request.get('seed') is not None and (type(request['seed']) is not int or request['seed']<0):
            raise ValueError('seed must be a nonnegative integer or null')
        if op == 'hello':
            return dict(sim='mujoco', version=mujoco.__version__, protocol='1.2', robot='panda', cameras=['top', 'front', 'side', 'wrist'], table_z=0.0)
        if op == 'ping':
            return {'t': time.time()}
        if op == 'kinematics':
            return export_kinematics(self.model)
        if op == 'reset' and self.remote_jobs is not None:
            commands,replies=self.remote_jobs
            commands.put(request.get('seed'))
            return replies.get(timeout=10)
        if op == 'reset':
            done = queue.Queue(maxsize=1)
            self.jobs.put((request.get('seed'), done), timeout=1)
            return done.get(timeout=5)
        if self.shared is not None:
            from graphics_process import read_snapshot
            q,v,t=read_snapshot(*self.shared,self.model)
            snapshot.qpos[:]=q;snapshot.qvel[:]=v;snapshot.time=t
        else:
            with self.lock:
                snapshot.qpos[:]=self.data.qpos
                snapshot.qvel[:]=self.data.qvel
                snapshot.time=self.data.time
        # Brief state copy only; OpenGL and JPEG encoding never hold physics lock.
        mujoco.mj_forward(self.model, snapshot)
        if op == 'ee_pose':
            site = self.model.site('tcp').id
            quat = np.empty(4)
            mujoco.mju_mat2Quat(quat, snapshot.site_xmat[site])
            return dict(pos=snapshot.site_xpos[site].tolist(), quat=quat.tolist(),
                        q=snapshot.qpos[self.qadr].tolist(), gripper=float(sum(snapshot.qpos[self.fingers])))
        if op == 'objects':
            return {'objects': [dict(name=n, pos=snapshot.body(n).xpos.tolist(),
                                    quat=snapshot.body(n).xquat.tolist()) for n in OBJECTS]}
        if op in ('render', 'render_multi'):
            w,h=request.get('w',640),request.get('h',480)
            cameras=request.get('cameras') if op=='render_multi' else [request.get('camera','top')]
            if (w,h) not in ((320,240),(640,480)) or not isinstance(cameras,list) or not 1<=len(cameras)<=4:
                raise ValueError('requires 1..4 cameras and 320x240 or 640x480')
            if any(c not in ('top','front','side','wrist') for c in cameras) or len(set(cameras))!=len(cameras):
                raise ValueError('unknown or duplicate camera')
            active=renderer[(w,h)] if isinstance(renderer,dict) else renderer
            images={}
            for camera in cameras:
                active.update_scene(snapshot,camera=camera)
                pixels=active.render();encoded=io.BytesIO()
                Image.fromarray(pixels).save(encoded,format='JPEG',quality=80)
                cam=self.model.camera(camera)
                images[camera]=dict(jpeg_b64=base64.b64encode(encoded.getvalue()).decode(),w=w,h=h,
                    fovy=float(cam.fovy[0]),cam_pos=snapshot.cam_xpos[cam.id].tolist(),cam_xmat=snapshot.cam_xmat[cam.id].tolist())
            return {'images':images} if op=='render_multi' else images[cameras[0]]
        raise ValueError('unknown op')

    def request_reply(self, line, renderer, snapshot):
        """Malformed JSON must not terminate the rendering/TCP worker."""
        request = None
        ident = None
        began = time.perf_counter()
        try:
            request = json.loads(line)
            if isinstance(request, dict):
                ident = request.get('id')
            reply = self.service(request, renderer, snapshot)
        except (ValueError, UnicodeDecodeError, queue.Empty, queue.Full) as exc:
            reply = {'error': str(exc) or type(exc).__name__}
        finally:
            timing('tcp_request', began,
                   op=request.get('op') if isinstance(request, dict) else None)
        return {'id': ident, **reply}

    def tcp_worker(self):
        # Context is created and destroyed on this rendering thread.
        try:
            with ExitStack() as contexts:
                renderer={size:contexts.enter_context(mujoco.Renderer(self.model,height=size[1],width=size[0])) for size in ((320,240),(640,480))}
                snapshot = mujoco.MjData(self.model)
                if self.render_ready is not None:
                    print(json.dumps({'graphics_stage':'renderer_ready'}),flush=True)
                    self.render_ready.set()
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
                                    reply = self.request_reply(line, renderer, snapshot)
                                    conn.sendall((json.dumps(reply)+'\n').encode())
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
                    watchdog_simulation_stalls=self.simulation_stalls,watchdog_board_silence=self.board_silence,
                    send_gap_max_ms=self.send_gap_max*1000,physics_gap_max_ms=self.physics_gap_max*1000,
                    snapshot_skips=self.snapshot_skips,
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

    def run(self, seconds, headless, isolated=True):
        worker = threading.Thread(target=self.tcp_worker, daemon=True)
        viewer = None
        graphics = None
        timer_active = False
        if __import__('os').name == 'nt':
            import ctypes
            timer_active = ctypes.windll.winmm.timeBeginPeriod(1) == 0
        try:
            if not headless and not isolated:
                from mujoco import viewer as mj_viewer
                viewer = mj_viewer.launch_passive(self.model, self.data)
            # GLFW initialization is process-global: initialize the viewer first,
            # then create the offscreen context on its own rendering thread.
            if isolated:
                from graphics_process import graphics_main
                context=mp.get_context('spawn')
                shared=context.RawArray('d',self.model.nq+self.model.nv+1)
                snapshot_lock=context.Lock();commands=context.Queue();replies=context.Queue()
                ready=context.Event();graphics_stop=context.Event()
                def publish():
                    if not snapshot_lock.acquire(False):
                        self.snapshot_skips+=1;return
                    try:
                        values=np.frombuffer(shared,dtype=np.float64)
                        values[:self.model.nq]=self.data.qpos
                        values[self.model.nq:-1]=self.data.qvel;values[-1]=self.data.time
                    finally:snapshot_lock.release()
                publish()
                graphics=context.Process(target=graphics_main,args=(self.address[0],headless,shared,snapshot_lock,commands,replies,ready,graphics_stop))
                graphics.start()
                if not ready.wait(60) or not graphics.is_alive():raise RuntimeError('graphics initialization failed')
                if __import__('os').name=='nt':
                    from graphics_process import set_windows_priority
                    set_windows_priority(0x80)
                print(json.dumps({'graphics_isolated':True,'physics_priority':'HIGH','graphics_pid':graphics.pid}),flush=True)
            else:
                worker.start()
            if getattr(self,'stop_on_stdin',False):
                def supervisor():
                    import sys
                    sys.stdin.readline();self.stop.set()
                threading.Thread(target=supervisor,daemon=True).start()
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.connect(self.address)  # Only replies from the board endpoint are accepted.
                udp.settimeout(.05)
                incoming = queue.Queue(maxsize=2048)
                def receive():
                    previous = None
                    while not self.stop.is_set():
                        try:
                            packet = udp.recv(65536)
                            arrived = time.perf_counter()
                            if previous is not None:
                                timing('udp_receive_gap', previous)
                            previous = arrived
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
                previous_step = previous_send = None
                while not self.stop.is_set() and time.perf_counter()-start < seconds and (viewer is None or viewer.is_running()) and (graphics is None or not graphics_stop.is_set()):
                    now = time.perf_counter()
                    if now < due:
                        time.sleep(due-now)
                    now = time.perf_counter()
                    loop_gap=0 if previous_step is None else now-previous_step
                    self.physics_gap_max=max(self.physics_gap_max,loop_gap)
                    if previous_step is not None:
                        timing('physics_start_gap', previous_step)
                    previous_step = now
                    if now-due > .002:
                        self.late += 1
                    # Schedule from actual start: no catch-up stepping.
                    due = now + .002 if now-due > .002 else due + .002
                    with self.lock:
                        if isolated:
                            try:
                                seed=commands.get_nowait();self.reset(seed);publish();replies.put({'ok':True})
                            except queue.Empty:pass
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
                            if sent_at is not None and seq<self.last_cmd_seq:
                                # v1.1: smaller peer sequence starts a new statistics epoch.
                                self.sent=len(self.pending);self.received=self.invalid=self.expired_count=self.reset_discarded=0
                                self.rtts.clear();self.last_ack=None
                                print(json.dumps({'peer_sequence_restart':True,'seq':seq}),flush=True)
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
                            first_command=self.last_rx is None
                            self.last_rx = arrival
                            self.last_cmd_seq = seq
                            if mode == 0:
                                if not self.holding or first_command:self.hold()
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
                                source='simulation_stall' if loop_gap>=.098 else 'board_silence'
                                if source=='simulation_stall':self.simulation_stalls+=1
                                else:self.board_silence+=1
                                print(json.dumps({'watchdog': 'hold', 'age_ms': (time.perf_counter()-self.last_rx)*1000,
                                                  'already_holding': self.holding,'source':source}), flush=True)
                            if not self.holding:
                                self.hold()
                            self.holding = True
                            self.watchdog_active = True
                        self.data.ctrl[:7] += np.clip(self.target-self.data.ctrl[:7], -.004, .004)
                        began = time.perf_counter()
                        mujoco.mj_step(self.model, self.data)
                        timing('mj_step', began)
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
                                if previous_send is not None:
                                    self.send_gap_max=max(self.send_gap_max,sent_at-previous_send)
                                    timing('udp_send_gap', previous_send)
                                previous_send = sent_at
                                udp.send(packet)
                            except ConnectionResetError:
                                continue
                            self.pending[self.seq] = sent_at
                            self.seq = (self.seq+1)&0xffffffff
                            self.sent += 1
                            self.reset_flag = False
                            if isolated:publish()
                            if len(self.pending) > 1024:
                                kept = {s: t for s, t in self.pending.items() if now-t < 1}
                                self.expired_count += len(self.pending)-len(kept)
                                self.pending = kept
                    if viewer and now-last_view >= 1/30:
                        began = time.perf_counter()
                        viewer.sync()
                        timing('viewer_sync', began)
                        last_view = now
                    if now-last_print >= 5:
                        began = time.perf_counter()
                        print(json.dumps(self.stats()), flush=True)
                        timing('stats_and_output', began)
                        last_print = now
        except KeyboardInterrupt:
            pass
        finally:
            self.wall_end = time.perf_counter()
            self.stop.set()
            if worker.is_alive():
                worker.join(timeout=5)
            if graphics is not None:
                graphics_stop.set();graphics.join(8)
                if graphics.is_alive():graphics.terminate();graphics.join(3)
            if viewer:
                viewer.close()
            if timer_active:
                ctypes.windll.winmm.timeEndPeriod(1)
            print(json.dumps(self.stats(final=True)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--board-ip', default='192.168.50.2')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--stop-on-stdin',action='store_true',help='supervisor EOF or STOP requests a clean shutdown')
    parser.add_argument('--in-process',action='store_true',help='diagnostic comparison only')
    parser.add_argument('--seconds', type=float, default=600)
    args = parser.parse_args()
    sim=Simulator(args.board_ip)
    sim.stop_on_stdin=args.stop_on_stdin
    sim.run(args.seconds,args.headless,not args.in_process)
