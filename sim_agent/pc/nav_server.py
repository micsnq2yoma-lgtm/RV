"""Navigation demo simulator (PC side). Physics + rendering only; the RV board plans and drives.

Protocol nav-1: the PC connects to board TCP 15003 (no firewall change), one JSON object per line,
the board sends requests and the PC replies with the same id.
  hello                         -> cameras, wheel radius, track width (no object positions)
  render {camera,w,h}           -> jpeg_b64 + fovy/cam_pos/cam_xmat (for pixel -> floor projection)
  drive {wl,wr}                 -> wheel speed targets in rad/s; hold zero if no drive for 0.5 s
  odom                          -> wheel encoder angles (rad) and sim time; the board integrates odometry
  reset {seed,scenario}         -> robot back to start (seeded jitter); scenario N4 arms the obstacle event
  truth                         -> robot pose, zone visits, events: for evaluation only, never for planning
Video goes straight to the browser: --mjpeg 127.0.0.1:8091 (loopback only).
"""
import argparse,base64,io,json,math,socket,threading,time
from pathlib import Path
import mujoco,numpy as np
from PIL import Image

CAMERAS=('top','chase','front','side')
ZONES=('red','green','blue','yellow','start')
SCENE=Path(__file__).with_name('scene_nav.xml')

class NavSim:
    def __init__(self,board_ip):
        self.address=(board_ip,15003)
        self.model=mujoco.MjModel.from_xml_path(str(SCENE));self.data=mujoco.MjData(self.model)
        self.lock=threading.Lock();self.stop=threading.Event()
        m=self.model
        self.wheels=[m.jnt_qposadr[m.joint(n).id] for n in ('wheel_l','wheel_r')]
        self.wheel_v=[m.jnt_dofadr[m.joint(n).id] for n in ('wheel_l','wheel_r')]
        self.root=m.jnt_qposadr[m.joint('robot_root').id];self.mocap=m.body_mocapid[m.body('box_dyn').id]
        self.zone={z:(m.geom('zone_'+z).pos[:2].copy(),m.geom('zone_'+z).size[:2].copy()) for z in ZONES}
        self.cmd=(0.,0.);self.last_cmd=0.;self.watchdog_stops=0
        self.reset(None,None)

    # ---- physics thread ----
    def reset(self,seed,scenario):
        with self.lock:
            mujoco.mj_resetData(self.model,self.data)
            rng=np.random.default_rng(seed)
            x,y=self.zone['start'][0]+(rng.uniform(-.08,.08,2) if seed is not None else 0)
            yaw=float(rng.uniform(-.4,.4)) if seed is not None else 0.
            self.data.qpos[self.root:self.root+7]=[x,y,.08,math.cos(yaw/2),0,0,math.sin(yaw/2)]
            self.data.mocap_pos[self.mocap]=[0,0,-1]
            mujoco.mj_forward(self.model,self.data)
            self.cmd=(0.,0.);self.scenario=scenario;self.event=None;self.visits=[];self.inside=None;self.path_len=0.;self.prev_xy=np.array([x,y])
            self.armed=scenario=='N4'
        return {'ok':True}

    def pose(self):
        q=self.data.qpos[self.root:self.root+7];return float(q[0]),float(q[1]),2*math.atan2(q[6],q[3])

    def physics(self):
        dt=self.model.opt.timestep;t0=time.perf_counter();steps=0
        while not self.stop.is_set():
            target=t0+steps*dt
            delay=target-time.perf_counter()
            if delay>0:time.sleep(delay)
            with self.lock:
                for _ in range(10):
                    if time.monotonic()-self.last_cmd>.5:
                        if self.cmd!=(0.,0.):self.watchdog_stops+=1
                        self.cmd=(0.,0.)
                    self.data.ctrl[:]=self.cmd;mujoco.mj_step(self.model,self.data);steps+=1
                self.track()

    def track(self):
        x,y,yaw=self.pose();xy=np.array([x,y]);self.path_len+=float(np.linalg.norm(xy-self.prev_xy));self.prev_xy=xy
        here=next((z for z,(c,h) in self.zone.items() if np.all(np.abs(xy-c)<=h)),None)
        if here!=self.inside:
            self.inside=here
            if here:self.visits.append({'zone':here,'t':float(self.data.time)})
        if self.armed and x>-.9:
            # Scenario N4: once the robot is under way, a box drops onto the main corridor towards the red zone
            # (about 1.3 m ahead of the trigger point, so the board has time to see it and the detour stays wide).
            p=np.array([.2,.25]);self.data.mocap_pos[self.mocap]=[p[0],p[1],.2]
            self.event={'name':'obstacle_appeared','xy':p.round(3).tolist(),'t':float(self.data.time)};self.armed=False

    # ---- requests (render thread) ----
    def snapshot(self,data):
        with self.lock:
            data.qpos[:]=self.data.qpos;data.qvel[:]=self.data.qvel;data.mocap_pos[:]=self.data.mocap_pos;data.mocap_quat[:]=self.data.mocap_quat;data.time=self.data.time
        mujoco.mj_forward(self.model,data)

    def service(self,request,renderer,data):
        op=request.get('op')
        if op=='hello':return {'sim':'mujoco','protocol':'nav-1','robot':'diff-drive','cameras':list(CAMERAS),'wheel_radius':.06,'track_width':.34,'max_wheel_speed':12.}
        if op=='render':
            cam=request.get('camera');w,h=int(request.get('w',640)),int(request.get('h',480))
            if cam not in CAMERAS or (w,h) not in ((640,480),(320,240)):raise ValueError('bad render request')
            self.snapshot(data);r=renderer[(w,h)];r.update_scene(data,camera=cam);img=r.render()
            buf=io.BytesIO();Image.fromarray(img).save(buf,'JPEG',quality=85)
            c=self.model.camera(cam).id
            return {'jpeg_b64':base64.b64encode(buf.getvalue()).decode(),'w':w,'h':h,'fovy':float(self.model.cam_fovy[c]),'cam_pos':data.cam_xpos[c].tolist(),'cam_xmat':data.cam_xmat[c].tolist()}
        if op=='drive':
            wl,wr=float(request['wl']),float(request['wr'])
            if not (math.isfinite(wl) and math.isfinite(wr)):raise ValueError('non-finite speed')
            lim=12.;
            with self.lock:self.cmd=(max(-lim,min(lim,wl)),max(-lim,min(lim,wr)));self.last_cmd=time.monotonic();t=float(self.data.time)
            return {'ok':True,'t':t}
        if op=='odom':
            with self.lock:return {'t':float(self.data.time),'wl':float(self.data.qpos[self.wheels[0]]),'wr':float(self.data.qpos[self.wheels[1]])}
        if op=='reset':
            s=request.get('seed');sc=request.get('scenario')
            if s is not None and (type(s) is not int or s<0):raise ValueError('seed must be a nonnegative integer')
            if sc not in (None,'N1','N2','N3','N4'):raise ValueError('unknown scenario')
            return self.reset(s,sc)
        if op=='truth':
            with self.lock:
                x,y,yaw=self.pose()
                return {'robot':{'x':x,'y':y,'yaw':yaw},'visits':list(self.visits),'event':self.event,'path_len':self.path_len,'t':float(self.data.time),'watchdog_stops':self.watchdog_stops,
                        'zones':{z:{'center':c.tolist(),'half':h.tolist()} for z,(c,h) in self.zone.items()}}
        if op=='ping':return {'t':time.time()}
        raise ValueError('unknown op '+str(op))

    def worker(self,mjpeg):
        renderer={(640,480):mujoco.Renderer(self.model,480,640),(320,240):mujoco.Renderer(self.model,240,320)}
        data=mujoco.MjData(self.model);jobs=[]
        jl=threading.Lock()
        def network():
            while not self.stop.is_set():
                try:
                    with socket.create_connection(self.address,timeout=2) as conn:
                        conn.settimeout(1);buf=b'';print(json.dumps({'board_connected':self.address[0]}),flush=True)
                        while not self.stop.is_set():
                            try:chunk=conn.recv(65536)
                            except socket.timeout:continue
                            if not chunk:break
                            buf+=chunk
                            if len(buf)>65536:raise ValueError('request too large')
                            while b'\n' in buf:
                                line,buf=buf.split(b'\n',1);done=threading.Event();box={}
                                with jl:jobs.append((line,done,box))
                                if not done.wait(15):raise TimeoutError('render thread stalled')
                                conn.sendall((json.dumps(box['reply'])+'\n').encode())
                except (OSError,ValueError,TimeoutError) as e:print(json.dumps({'tcp_error':type(e).__name__}),flush=True)
                self.stop.wait(2)
        threading.Thread(target=network,daemon=True).start()
        streams=None
        if mjpeg:
            import mjpeg as mj
            streams=mj.Streams(mjpeg,CAMERAS)
        try:
            while not self.stop.is_set():
                with jl:batch=jobs[:];jobs.clear()
                for line,done,box in batch:
                    req=None
                    try:
                        req=json.loads(line);box['reply']={'id':req.get('id'),**self.service(req,renderer,data)}
                    except Exception as e:box['reply']={'id':req.get('id') if isinstance(req,dict) else None,'error':str(e)}
                    done.set()
                if streams:streams.pump(self,renderer,data)
                if not batch:time.sleep(.003)
        finally:
            if streams:streams.close()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--board-ip',default='192.168.50.2');ap.add_argument('--mjpeg',help='127.0.0.1:8091');ap.add_argument('--seconds',type=float,default=7200)
    ap.add_argument('--stop-file',help='exit when this file appears')
    a=ap.parse_args()
    if a.mjpeg and not a.mjpeg.startswith('127.0.0.1:'):ap.error('--mjpeg must bind 127.0.0.1')
    sim=NavSim(a.board_ip)
    threading.Thread(target=sim.physics,daemon=True).start();threading.Thread(target=sim.worker,args=(a.mjpeg,),daemon=True).start()
    print(json.dumps({'nav_server':'running','mjpeg':a.mjpeg}),flush=True);end=time.monotonic()+a.seconds
    try:
        while time.monotonic()<end and not (a.stop_file and Path(a.stop_file).exists()):
            time.sleep(5)
            with sim.lock:x,y,yaw=sim.pose();t=float(sim.data.time)
            print(json.dumps({'t':round(t,1),'robot':[round(x,3),round(y,3),round(math.degrees(yaw),1)],'watchdog_stops':sim.watchdog_stops}),flush=True)
    except KeyboardInterrupt:pass
    sim.stop.set()

if __name__=='__main__':main()
