"""DexJoCo bimanual simulator server for the agent demo. Runs in the DexJoCo conda env (Python 3.11, MuJoCo 3.4).

Protocol dexjoco-1: this process connects OUT to the agent host (127.0.0.1 for local tests, 192.168.50.2 for the
RV board) on TCP 15005; one JSON object per line; the agent sends requests, this server replies with the same id.
  hello                     -> tasks, cameras, action layout
  reset {task,seed,password}-> new randomised episode (official DexJoCo reset); returns the instruction
  observe                   -> per perception camera: depth in mm (16-bit PNG), instance mask (PNG), intrinsics,
                               camera pose (OpenCV convention); instance->name map; both arms' commanded pose and hand
  step {cmds:[...]}         -> up to 90 control steps at 30 Hz. Each cmd is {"right":[23],"left":[23]}; an arm left
                               out keeps its last command. 23 = target flange pose [x,y,z,qw,qx,qy,qz] + 16 Allegro joints.
  overlay {text,tokens,...} -> caption shown on the video (task, token count); display only
  truth                     -> DexJoCo's own success check. Evaluation only, never used for planning.
  video {path}              -> write the wide-view frames of this episode to an MP4 on the PC
The simulator state never goes to the agent: it sees depth + instance masks and computes positions itself.
Video for the browser: --mjpeg 127.0.0.1:8094 (/wide, /ego), loopback only.
"""
import argparse,base64,importlib,io,json,os,random,socket,subprocess,tempfile,textwrap,threading,time
import numpy as np,mujoco
from PIL import Image,ImageDraw,ImageFont

TASKS={
 'bimanual_hanoi':{'text':'Move all disks onto the right peg (peg C), largest at the bottom.',
   'inst':{'body:hanoi_disk_large':'disk_large','body:hanoi_disk_medium':'disk_medium','body:hanoi_disk_small':'disk_small',
           'geom:hanoi_post_a_visual':'peg_A','geom:hanoi_post_b_visual':'peg_B','geom:hanoi_post_c_visual':'peg_C',
           'geom:hanoi_base_upper_visual':'base'}},
 'bimanual_microwave_cook':{'text':'Put the hot dog in the microwave, close the door and press start.',
   'inst':{'body:hot_dog':'hot_dog','geom:door_handle':'door_handle','body:door':'door','geom:start_button':'start_button',
           'body:microwave_object':'microwave'}},
 'bimanual_assembly':{'text':'Insert the round peg into the socket.',
   'inst':{'body:industreal_round_peg_8mm':'peg','body:industreal_tray_insert_round_peg_8mm':'socket'}},
 'bimanual_photograph':{'text':'Pick up the camera, aim it at the logo on the wall and take a photo.',
   'inst':{'body:link_19':'camera','geom:camera_body_top_cap':'shutter','geom:photograph_logo_disk':'logo'}},
 'bimanual_unlock_ipad':{'text':'Pick up the iPad and unlock it with passcode {pw}.',
   'inst':{'body:ipad_body':'ipad','body:ipad_stand':'stand','body:ff_tip_right':'right_index_tip',**{f'body:btn_{d}':f'button_{d}' for d in range(10)}}},
}
# Perception cameras, the same for every task: fixed viewpoints high above the table (front, left, right), looking at
# the work area. (lookat xyz, distance, azimuth, elevation) in MuJoCo free-camera terms.
PERCEPT_CAMS={'cam_front':([-0.25,0,1.0],1.5,180,-50),'cam_left':([-0.25,0,1.0],1.4,-90,-55),'cam_right':([-0.25,0,1.0],1.4,90,-55),'cam_low':([-0.25,0,1.1],1.6,180,-12)}
W,H=960,540
FONT='C:/Windows/Fonts/consola.ttf'

# MuJoCo's Renderer maps segmentation colours through a table sized by the scene's geom count; some scenes (the iPad's
# fading button labels) produce colours past it and the lookup raises IndexError. Pad the table: unknown ids -> background.
import mujoco.renderer as _MR
class _PaddedNP:
    def __getattr__(self,k):return getattr(np,k)
    def full(self,shape,*a,**k):
        if isinstance(shape,tuple) and len(shape)==2 and shape[1]==2:shape=(shape[0]+4096,2)
        return np.full(shape,*a,**k)
_MR.np=_PaddedNP()

def png_b64(arr):
    b=io.BytesIO();Image.fromarray(arr).save(b,'PNG');return base64.b64encode(b.getvalue()).decode()

class DexSim:
    def __init__(self,size=320,realtime=True,views=True):
        self.size=size;self.realtime=realtime;self.views=views;self.lock=threading.Lock();self.env=None;self.task=None
        self.frames={};self.overlay={'tokens':0,'note':''};self.video=[];self.steps=0
    # ---------- episode ----------
    def reset(self,task='bimanual_hanoi',seed=0,password=None):
        if task not in TASKS:raise ValueError('unknown task '+task)
        with self.lock:
            self.close()
            cfg=importlib.import_module(f'dexjoco.tasks.{task}.config').TaskConfig()
            kw={'password':list(password)} if (task=='bimanual_unlock_ipad' and password) else {}
            np.random.seed(int(seed));random.seed(int(seed))
            self.env=cfg.get_environment(policy_mode=True,render_mode='rgb_array',randomize=False,randomize_dynamics=False,seed=int(seed),**kw)
            self.env.reset(seed=int(seed));self.raw=self.env.unwrapped;m=self.m=self.raw.model;self.d=self.raw.data
            if not self.realtime:self.raw.hz=1e6
            # A dropped or misplaced disk would freeze the hanoi env and auto-reset it; here it stays where it fell, as on a
            # real table, and the agent may recover. Success is still DexJoCo's own check on the final state.
            if hasattr(self.raw,'_illegal_trigger_target'):self.raw._illegal_trigger_target=10**9
            m.vis.global_.offwidth=max(W,self.size);m.vis.global_.offheight=max(H,self.size)
            self.rp=mujoco.Renderer(m,self.size,self.size);self.rw=mujoco.Renderer(m,H,W);self.re=mujoco.Renderer(m,360,360)
            self.cam=mujoco.MjvCamera();self.cam.type=mujoco.mjtCamera.mjCAMERA_FREE
            self.cam.lookat[:]=[-0.3,0,1.0];self.cam.distance=1.85;self.cam.azimuth=0;self.cam.elevation=-45
            self._instances(TASKS[task]['inst'])
            # Last command per arm: start from the current flange pose and hand joints (holds the arm still).
            self.cmd={a:np.r_[self.d.sensor(f'franka/flange_pos_{a}').data,self.d.sensor(f'franka/flange_quat_{a}').data,self._hand(a)] for a in ('right','left')}
            self.steps=0;self.succeeded=False;self.video=[]
            pw=''.join(str(x) for x in (password or [1,2,3]))
            text=TASKS[task]['text'].format(pw='-'.join(pw))
            self.task={'task':task,'seed':int(seed),'instruction':text,'password':pw if task=='bimanual_unlock_ipad' else None}
            self.overlay={'tokens':0,'note':''};self._render_views(force=True)
            return {'ok':True,'instruction':text,'objects':sorted(set(self.names.values()))}
    def close(self):
        """Free the OpenGL renderers and the env; a leftover context breaks the next one's rendering."""
        for k in ('rp','rw','re'):
            r=getattr(self,k,None)
            if r is not None:
                try:r.close()
                except Exception:pass
                setattr(self,k,None)
        if self.env is not None:
            try:self.env.close()
            except Exception:pass
            self.env=None
    def _hand(self,arm):
        """Current Allegro targets; the raw env writes ctrl[_allegro_ctrl_ids] as [right 16, left 16]."""
        ids=np.asarray(self.raw._allegro_ctrl_ids).ravel()
        return np.asarray(self.d.ctrl[ids[:16] if arm=='right' else ids[16:32]],float)
    def _instances(self,spec):
        """geom id -> instance index (1..N) for the segmentation image; index -> name for the agent."""
        m=self.m;names=sorted(set(spec.values()));self.names={i+1:n for i,n in enumerate(names)};idx={n:i for i,n in self.names.items()}
        self.geom2inst=np.zeros(m.ngeom+1,np.uint8)
        for g in range(m.ngeom):   # body rules first, then geom rules override (a handle inside the door body)
            b=m.body(m.geom_bodyid[g]).name
            if f'body:{b}' in spec:self.geom2inst[g]=idx[spec[f'body:{b}']]
        for g in range(m.ngeom):
            n=m.geom(g).name
            if n and f'geom:{n}' in spec:self.geom2inst[g]=idx[spec[f'geom:{n}']]
    # ---------- sensing ----------
    def observe(self):
        with self.lock:
            out={'cameras':{},'step':self.steps,'instances':{str(k):v for k,v in self.names.items()}}
            for c,(look,dist,az,el) in PERCEPT_CAMS.items():
                cam=mujoco.MjvCamera();cam.type=mujoco.mjtCamera.mjCAMERA_FREE;cam.lookat[:]=look;cam.distance=dist;cam.azimuth=az;cam.elevation=el
                r=self.rp;r.update_scene(self.d,camera=cam)
                gl=r.scene.camera[0];fwd=np.asarray(gl.forward,float);up=np.asarray(gl.up,float)
                pos=(np.asarray(r.scene.camera[0].pos)+np.asarray(r.scene.camera[1].pos))/2   # camera[0/1] are stereo eyes, ipd apart
                f=0.5*self.size*gl.frustum_near/gl.frustum_top
                R=np.stack([np.cross(fwd,up),-up,fwd],1);E=np.eye(4);E[:3,:3]=R;E[:3,3]=pos
                r.enable_depth_rendering();depth=r.render();r.disable_depth_rendering()
                r.enable_segmentation_rendering();seg=r.render();r.disable_segmentation_rendering()
                gid=np.where(seg[...,1]==int(mujoco.mjtObj.mjOBJ_GEOM),seg[...,0],-1)
                inst=np.where(gid>=0,self.geom2inst[np.clip(gid,0,self.m.ngeom-1)],0).astype(np.uint8)
                K=[[f,0,self.size/2],[0,f,self.size/2],[0,0,1]]
                out['cameras'][c]={'depth_mm_png':png_b64(np.clip(depth*1000,0,65535).astype(np.uint16)),'seg_png':png_b64(inst),
                                   'K':K,'cam_to_world':E.tolist(),'w':self.size,'h':self.size}
            out['arms']=self._arms()
            return out
    def _arms(self):
        return {a:{'cmd':[round(float(v),5) for v in self.cmd[a]],
                   'flange':[round(float(v),5) for v in np.r_[self.d.sensor(f'franka/flange_pos_{a}').data,self.d.sensor(f'franka/flange_quat_{a}').data]]} for a in ('right','left')}
    # ---------- acting ----------
    def step(self,cmds):
        if not isinstance(cmds,list) or not 1<=len(cmds)<=90:raise ValueError('1..90 cmds')
        with self.lock:
            for c in cmds:
                for a in ('right','left'):
                    if c.get(a) is not None:
                        v=np.asarray(c[a],float)
                        if v.shape!=(23,) or not np.all(np.isfinite(v)):raise ValueError('bad cmd for '+a)
                        q=v[3:7];n=np.linalg.norm(q)
                        if n<1e-6:raise ValueError('bad quaternion')
                        v[3:7]=q/n;self.cmd[a]=v
                _,_,_,_,info=self.raw.step({'right':self.cmd['right'].copy(),'left':self.cmd['left'].copy()})
                self.steps+=1;self.succeeded=self.succeeded or bool(info.get('succeed',False))
                if self.views and self.steps%3==0:self._render_views()
            return {'steps':self.steps,'arms':self._arms()}
    def truth(self):
        with self.lock:
            now=False
            try:now=bool(self.raw._compute_success())
            except Exception:pass
            return {'success':bool(self.succeeded or now),'steps':self.steps,'task':self.task}
    # ---------- video ----------
    def _render_views(self,force=False):
        self.rw.update_scene(self.d,camera=self.cam);img=Image.fromarray(self.rw.render()).convert('RGBA')
        ov=Image.new('RGBA',img.size,(0,0,0,0));dr=ImageDraw.Draw(ov)
        def box(xy,txt,size,anchor='la',pad=12):
            f=ImageFont.truetype(FONT,size);b=dr.multiline_textbbox(xy,txt,font=f,anchor=anchor,spacing=6)
            dr.rounded_rectangle((b[0]-pad,b[1]-pad,b[2]+pad,b[3]+pad),8,fill=(40,40,40,165));dr.multiline_text(xy,txt,font=f,fill='white',anchor=anchor,spacing=6)
        box((36,28),'\n'.join(textwrap.wrap('Task: '+self.task['instruction'],44)),19)
        box((W-36,28),'%d tokens'%self.overlay.get('tokens',0),19,anchor='ra')
        if self.overlay.get('note'):box((36,H-26),self.overlay['note'][:70],15,anchor='ls',pad=8)
        box((W-28,H-24),self.overlay.get('speed','1x, DeepSeek agent'),13,anchor='rs',pad=7)
        wide=np.asarray(Image.alpha_composite(img,ov).convert('RGB'))
        cam=mujoco.MjvCamera();cam.type=mujoco.mjtCamera.mjCAMERA_FREE;look,dist,az,el=PERCEPT_CAMS['cam_front']
        cam.lookat[:]=look;cam.distance=dist;cam.azimuth=az;cam.elevation=el;self.re.update_scene(self.d,camera=cam);ego=self.re.render()
        self.frames={'wide':wide,'ego':ego}
        if len(self.video)<20000:self.video.append(wide)
    def save_video(self,path,every=2,fps=15):
        frames=self.video[::every]
        if not frames:return {'ok':False,'error':'no frames'}
        import imageio_ffmpeg
        tmp=tempfile.mkdtemp()
        for k,f in enumerate(frames+[frames[-1]]*fps):Image.fromarray(f).save(f'{tmp}/{k:05d}.png')
        os.makedirs(os.path.dirname(os.path.abspath(path)),exist_ok=True)
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-loglevel','error','-framerate',str(fps),'-i',f'{tmp}/%05d.png','-c:v','libx264','-pix_fmt','yuv420p','-crf','20',path],check=True)
        return {'ok':True,'path':path,'frames':len(frames)}
    def service(self,req):
        op=req.get('op')
        if op=='hello':return {'sim':'dexjoco','protocol':'dexjoco-1','tasks':list(TASKS),'cameras':list(PERCEPT_CAMS),'control_hz':30,
                                'action':'per arm [x,y,z,qw,qx,qy,qz] flange target + 16 Allegro joint targets'}
        if op=='reset':return self.reset(req.get('task','bimanual_hanoi'),req.get('seed',0),req.get('password'))
        if op=='observe':return self.observe()
        if op=='step':return self.step(req['cmds'])
        if op=='truth':return self.truth()
        if op=='overlay':
            self.overlay.update({k:req[k] for k in ('tokens','note','speed') if k in req});return {'ok':True}
        if op=='video':
            with self.lock:return self.save_video(req['path'])
        if op=='ping':return {'t':time.time()}
        raise ValueError('unknown op '+str(op))

def serve_mjpeg(sim,address):
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    host,port=address.rsplit(':',1)
    class Hd(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            cam=self.path.split('/')[-1].split('.')[0].split('?')[0]
            if cam not in ('wide','ego'):self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type','multipart/x-mixed-replace; boundary=f');self.end_headers()
            try:
                while True:
                    f=sim.frames.get(cam)
                    if f is not None:
                        b=io.BytesIO();Image.fromarray(f).save(b,'JPEG',quality=80);data=b.getvalue()
                        self.wfile.write(b'--f\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+b'\r\n\r\n'+data+b'\r\n')
                    time.sleep(.1)
            except OSError:pass
    s=ThreadingHTTPServer((host,int(port)),Hd);s.daemon_threads=True;threading.Thread(target=s.serve_forever,daemon=True).start()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--agent-ip',default='127.0.0.1');ap.add_argument('--port',type=int,default=15005)
    ap.add_argument('--mjpeg',default='127.0.0.1:8094');ap.add_argument('--fast',action='store_true',help='no 30 Hz real-time pacing');a=ap.parse_args()
    if not a.mjpeg.startswith('127.0.0.1:'):ap.error('--mjpeg must bind 127.0.0.1')
    sim=DexSim(realtime=not a.fast);sim.reset();serve_mjpeg(sim,a.mjpeg);print(json.dumps({'dexjoco_server':'ready'}),flush=True)
    while True:
        try:
            with socket.create_connection((a.agent_ip,a.port),timeout=3) as c:
                c.settimeout(None);f=c.makefile('rb');print(json.dumps({'agent_connected':a.agent_ip}),flush=True)
                for line in f:
                    req=None
                    try:req=json.loads(line);reply={'id':req.get('id'),**sim.service(req)}
                    except Exception as e:reply={'id':req.get('id') if isinstance(req,dict) else None,'error':type(e).__name__+': '+str(e)}
                    c.sendall((json.dumps(reply)+'\n').encode())
        except OSError:time.sleep(2)

if __name__=='__main__':main()
