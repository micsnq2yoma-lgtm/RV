"""LIBERO (robosuite/MuJoCo) simulator server for the agent demo. Runs in the LIBERO conda env (Python 3.8).

Protocol libero-1: this process connects OUT to the agent host (default 127.0.0.1 for local tests,
192.168.50.2 for the RV board) on TCP 15004; one JSON object per line; the agent sends requests,
this server replies with the same id.
  hello                          -> suites/tasks available, cameras, action layout
  reset {suite,task,init}        -> loads the official BDDL task and init state; returns instruction + object names
  observe {size}                 -> per camera: RGB (JPEG), depth in mm (16-bit PNG), instance mask (PNG),
                                    intrinsics, camera pose; plus eef pos/quat, gripper width, instance->name map
  step {actions:[[7]...]}        -> official 7-D OSC action rows [dx,dy,dz,drx,dry,drz,grip] in [-1,1]
  truth                          -> LIBERO's own BDDL success predicate. Evaluation only, never for planning.
Video for the browser: --mjpeg 127.0.0.1:8092 (agentview and wrist), loopback only.
"""
import argparse,base64,io,json,os,socket,threading,time
import numpy as np
from PIL import Image
from libero.libero import benchmark,get_libero_path
from libero.libero.envs import OffScreenRenderEnv
from robosuite.utils import camera_utils as CU

CAMS=('agentview','robot0_eye_in_hand')

def png_b64(arr):
    b=io.BytesIO();Image.fromarray(arr).save(b,'PNG');return base64.b64encode(b.getvalue()).decode()
def jpg_b64(arr,q=85):
    b=io.BytesIO();Image.fromarray(arr).save(b,'JPEG',quality=q);return base64.b64encode(b.getvalue()).decode()

class LiberoSim:
    def __init__(self,size=256):
        self.size=size;self.env=None;self.lock=threading.Lock();self.frames={};self.steps=0;self.task=None
    def reset(self,suite='libero_spatial',task=0,init=0):
        s=benchmark.get_benchmark_dict()[suite]();t=s.get_task(int(task))
        bddl=os.path.join(get_libero_path('bddl_files'),t.problem_folder,t.bddl_file)
        with self.lock:
            if self.env is not None:self.env.close()
            self.env=OffScreenRenderEnv(bddl_file_name=bddl,camera_heights=self.size,camera_widths=self.size,camera_depths=True,camera_segmentations='instance')
            self.env.seed(0);self.env.reset();self.obs=self.env.set_init_state(s.get_task_init_states(int(task))[int(init)])
            for _ in range(10):self.obs,_,_,_=self.env.step([0,0,0,0,0,0,-1])   # let objects settle, gripper open
            self.steps=0;self.done=False;self.task={'suite':suite,'task':int(task),'init':int(init),'language':t.language}
            self._frames()
            inner=self.env.env;names=list(inner.objects_dict.keys())+list(getattr(inner,'fixtures_dict',{}).keys())
            return {'ok':True,'instruction':t.language,'objects':names}
    def _frames(self):
        for c in CAMS:self.frames[c]=self.obs[c+'_image'][::-1].copy()
    def instance_names(self):
        """Instance id (as in the segmentation image) -> object name."""
        # robosuite numbers instances in the order of model.instances_to_ids, plus 1; 0 is background (robot_env.py).
        m=getattr(self.env.env.model,'instances_to_ids',{}) or {}
        return {str(i+1):n for i,n in enumerate(m.keys())}
    def observe(self,size=None):
        with self.lock:
            inner=self.env.env;sim=inner.sim;out={'cameras':{},'step':self.steps}
            for c in CAMS:
                rgb=self.obs[c+'_image'][::-1];d=CU.get_real_depth_map(sim,self.obs[c+'_depth'])[::-1,:,0]
                seg=self.obs[c+'_segmentation_instance'][::-1,:,0].astype(np.uint8)
                K=CU.get_camera_intrinsic_matrix(sim,c,self.size,self.size);E=CU.get_camera_extrinsic_matrix(sim,c)
                out['cameras'][c]={'rgb_jpg':jpg_b64(rgb),'depth_mm_png':png_b64(np.clip(d*1000,0,65535).astype(np.uint16)),'seg_png':png_b64(seg),
                                   'K':K.tolist(),'cam_to_world':E.tolist(),'w':self.size,'h':self.size}
            out['eef_pos']=self.obs['robot0_eef_pos'].tolist();out['eef_quat']=self.obs['robot0_eef_quat'].tolist()
            out['gripper_qpos']=self.obs['robot0_gripper_qpos'].tolist();out['instances']=self.instance_names()
            return out
    def step(self,actions):
        if not isinstance(actions,list) or not 1<=len(actions)<=40:raise ValueError('1..40 action rows')
        with self.lock:
            for row in actions:
                a=np.clip(np.asarray(row,float),-1,1)
                if a.shape!=(7,) or not np.all(np.isfinite(a)):raise ValueError('bad action row')
                self.obs,_,done,_=self.env.step(a.tolist());self.steps+=1;self.done=self.done or bool(done)
            self._frames()
            return {'eef_pos':self.obs['robot0_eef_pos'].tolist(),'gripper_qpos':self.obs['robot0_gripper_qpos'].tolist(),'steps':self.steps,'done':self.done}
    def truth(self):
        with self.lock:
            inner=self.env.env
            return {'success':bool(inner._check_success()),'steps':self.steps,'task':self.task}
    def service(self,req):
        op=req.get('op')
        if op=='hello':return {'sim':'libero','protocol':'libero-1','cameras':list(CAMS),'action':'[dx,dy,dz,drx,dry,drz,grip] in [-1,1]; OSC scale 0.05 m / 0.5 rad; grip -1 open +1 close','control_hz':20,
                                'suites':['libero_spatial','libero_object','libero_goal','libero_10']}
        if op=='reset':return self.reset(req.get('suite','libero_spatial'),req.get('task',0),req.get('init',0))
        if op=='observe':return self.observe()
        if op=='step':return self.step(req['actions'])
        if op=='truth':return self.truth()
        if op=='ping':return {'t':time.time()}
        raise ValueError('unknown op '+str(op))

def serve_mjpeg(sim,address):
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    host,port=address.rsplit(':',1)
    class H(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            cam=self.path.split('/')[-1].split('.')[0].split('?')[0]
            if cam not in CAMS:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type','multipart/x-mixed-replace; boundary=f');self.end_headers()
            try:
                while True:
                    f=sim.frames.get(cam)
                    if f is not None:
                        b=io.BytesIO();Image.fromarray(f).resize((512,512)).save(b,'JPEG',quality=80);data=b.getvalue()
                        self.wfile.write(b'--f\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+b'\r\n\r\n'+data+b'\r\n')
                    time.sleep(.1)
            except OSError:pass
    s=ThreadingHTTPServer((host,int(port)),H);s.daemon_threads=True;threading.Thread(target=s.serve_forever,daemon=True).start()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--agent-ip',default='127.0.0.1');ap.add_argument('--port',type=int,default=15004)
    ap.add_argument('--size',type=int,default=256);ap.add_argument('--mjpeg',default='127.0.0.1:8092');a=ap.parse_args()
    if not a.mjpeg.startswith('127.0.0.1:'):ap.error('--mjpeg must bind 127.0.0.1')
    sim=LiberoSim(a.size);sim.reset();serve_mjpeg(sim,a.mjpeg);print(json.dumps({'libero_server':'ready','instruction':sim.task['language']}),flush=True)
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
