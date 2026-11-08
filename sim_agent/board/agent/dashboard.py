"""Board-only dashboard. Fixed endpoints; no shell, credentials or arbitrary file access."""
import asyncio,base64,json,os,re,socketserver,subprocess,sys,threading,time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException,Request,WebSocket,WebSocketDisconnect
from fastapi.responses import HTMLResponse,FileResponse,JSONResponse
from pydantic import BaseModel,Field
from transport import SimClient
from local_rpc import PATH

ROOT=Path('/tmp/runs');WORK=Path('/tmp/rv014');CAMERAS=['top','front','side','wrist']
def readjson(path,default=None):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return {} if default is None else default
def atomic(path,value):
    tmp=path.with_suffix('.new');tmp.write_text(json.dumps(value,ensure_ascii=False));tmp.replace(path)
def runpath(name):
    if not re.fullmatch(r'[0-9T-]+',name):raise HTTPException(404)
    p=ROOT/name
    if not p.is_dir() or p.is_symlink():raise HTTPException(404)
    return p
def evaluate(task,objects):
    """Truth-only assessment kept outside all model/perception inputs."""
    poses={o['name']:o['pos'] for o in objects['objects']}
    def inside(cube,tray):
        p,t=poses[cube],poses[tray];return abs(p[0]-t[0])<.08 and abs(p[1]-t[1])<.06 and .02<p[2]<.05
    if task.strip()=='把红色方块放进左边的托盘':ok=inside('red_cube','left_tray')
    elif task.strip()=='把蓝色方块叠到绿色方块上面':
        b,g=poses['blue_cube'],poses['green_cube'];ok=((b[0]-g[0])**2+(b[1]-g[1])**2)**.5<.02 and abs(b[2]-g[2]-.04)<.01
    elif task.strip()=='把三个方块都放进右边的托盘':ok=all(inside(c,'right_tray') for c in ['red_cube','green_cube','blue_cube'])
    else:return {'evaluated':False,'reason':'No predefined truth criterion for this task','objects':objects}
    return {'evaluated':True,'success':bool(ok),'objects':objects}

class Runtime:
    def __init__(self):
        self.lock=threading.RLock();self.sim=None;self.frames={};self.frame_seq=0;self.frame_seconds=None;self.error=None
        self.process=None;self.run=None;self.monitor=None;self.stop=threading.Event();self.fps=4.;self.enabled=True
    def call(self,op,**args):
        with self.lock:
            if self.sim is None:raise RuntimeError('simulation not connected')
            return self.sim.call(op,**args)
    def connect(self):
        try:self.sim=SimClient(timeout=3600);self.error=None
        except Exception as exc:self.error=type(exc).__name__
    def video(self):
        while not self.stop.is_set():
            start=time.monotonic()
            try:
                if self.enabled and self.sim:
                    images=self.call('render_multi',cameras=CAMERAS,w=320,h=240)['images'];self.frames=images;self.frame_seq+=1;self.frame_seconds=time.monotonic()-start;self.error=None
            except Exception as exc:self.error=str(exc)
            self.stop.wait(max(.01,1/self.fps-(time.monotonic()-start)))
    def tick(self):
        while not self.stop.wait(1):
            status=readjson(ROOT/self.run/'status.json') if self.run else {}
            pids={'dashboard':os.getpid()}
            try:pids['rt_ctl']=int((WORK/'rt.pid').read_text())
            except (OSError,ValueError):pass
            if self.monitor:pids['sysmon']=self.monitor.pid
            if self.process and self.process.poll() is None:pids['agent']=self.process.pid
            atomic(WORK/'current.json',{'run':self.run if self.process and self.process.poll() is None else None,'pids':pids,'action':status.get('action',status.get('status','idle'))})
            if self.process and self.process.poll() is not None and self.run:
                directory=ROOT/self.run
                if not (directory/'evaluation.json').exists():
                    try:result=evaluate(readjson(directory/'request.json')['task'],self.call('objects'));result['agent_exit']=self.process.returncode;atomic(directory/'evaluation.json',result)
                    except Exception as exc:atomic(directory/'evaluation.json',{'evaluated':False,'error':str(exc)})
                    if status.get('status','running')=='running':atomic(directory/'status.json',{'status':'error','reason':'agent exited unexpectedly','exit':self.process.returncode})
    def start(self,task,seed):
        if self.process and self.process.poll() is None:raise HTTPException(409,'A task is already running')
        if self.sim is None:raise HTTPException(503,'Simulation not connected')
        if seed is not None:self.call('reset',seed=seed);time.sleep(.5)
        name=time.strftime('%Y%m%dT%H%M%S')+'-'+str(time.time_ns()%1000000000);directory=ROOT/name;directory.mkdir()
        atomic(directory/'request.json',{'task':task,'seed':seed,'created_utc':time.time()});atomic(directory/'status.json',{'status':'running','step':0,'action':'启动'})
        self.run=name
        with (directory/'agent.log').open('w') as log:self.process=subprocess.Popen([sys.executable,'-u',str(Path(__file__).with_name('agent.py')),str(directory)],stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1'})
        return {'run':name}
runtime=Runtime()

class Broker(socketserver.ThreadingUnixStreamServer):daemon_threads=True
class Handler(socketserver.StreamRequestHandler):
    allowed=('hello','kinematics','render','render_multi','ping','ee_pose')
    def handle(self):
        try:
            request=json.loads(self.rfile.readline(65536));op=request.pop('op')
            if op not in self.allowed:raise ValueError('operation not available to agent')
            result=runtime.call(op,**request)
        except Exception as exc:result={'error':str(exc)}
        self.wfile.write((json.dumps(result)+'\n').encode())
class EvaluationHandler(Handler):
    # Separate local evaluator endpoint; never used by the planning process.
    allowed=Handler.allowed+('reset','objects')

@asynccontextmanager
async def lifecycle(app):
    os.sched_setaffinity(0,{0});ROOT.mkdir(exist_ok=True);WORK.mkdir(exist_ok=True)
    if Path(PATH).exists():raise RuntimeError('Broker socket already exists; inspect previous process before starting')
    broker=Broker(PATH,Handler);os.chmod(PATH,0o600)
    evaluator=Broker('/tmp/rv014/evaluation.sock',EvaluationHandler);os.chmod('/tmp/rv014/evaluation.sock',0o600)
    for fn in (broker.serve_forever,evaluator.serve_forever,runtime.connect,runtime.video,runtime.tick):threading.Thread(target=fn,daemon=True).start()
    runtime.monitor=subprocess.Popen([sys.executable,'-u',str(Path(__file__).with_name('sysmon.py'))])
    try:yield
    finally:
        if runtime.process and runtime.process.poll() is None:
            (ROOT/runtime.run/'stop').touch()
            try:await asyncio.to_thread(runtime.process.wait,120)
            except subprocess.TimeoutExpired:runtime.process.terminate();await asyncio.to_thread(runtime.process.wait,10)
        runtime.stop.set();runtime.monitor.terminate();runtime.monitor.wait(5);broker.shutdown();broker.server_close();Path(PATH).unlink(missing_ok=True)
        evaluator.shutdown();evaluator.server_close();Path('/tmp/rv014/evaluation.sock').unlink(missing_ok=True)
        if runtime.sim:runtime.sim.close()

app=FastAPI(lifespan=lifecycle,docs_url=None,redoc_url=None)
class Task(BaseModel):
    task:str=Field(min_length=1,max_length=500)
    seed:int|None=Field(default=None,ge=0)
class Refresh(BaseModel):
    fps:float=Field(ge=.5,le=4)
    enabled:bool=True
@app.middleware('http')
async def guard(request:Request,call_next):
    if request.method=='POST':
        if request.client.host!='192.168.50.1' or request.headers.get('origin','http://192.168.50.2:8080')!='http://192.168.50.2:8080':
            from fastapi.responses import JSONResponse
            return JSONResponse({'error':'local board operator only'},status_code=403)
    return await call_next(request)
@app.get('/')
def index():return HTMLResponse(Path(__file__).with_name('dashboard.html').read_text())
@app.post('/task')
def start_task(request:Task):return runtime.start(request.task,request.seed)
@app.post('/stop')
def stop_task():
    if runtime.run:(ROOT/runtime.run/'stop').touch()
    return {'stopping':True,'message':'当前技能结束后回到 home'}
@app.post('/refresh')
def refresh(request:Refresh):runtime.fps=request.fps;runtime.enabled=request.enabled;return request.dict()
@app.get('/state')
def state():
    directory=ROOT/runtime.run if runtime.run else None
    return JSONResponse({'connected':runtime.sim is not None,'error':runtime.error,'run':runtime.run,'status':readjson(directory/'status.json') if directory else {},
            'evaluation':readjson(directory/'evaluation.json') if directory else {},'resources':readjson(WORK/'sysmon.json'),'frame_seconds':runtime.frame_seconds,'frame_seq':runtime.frame_seq,'fps':runtime.fps})
@app.get('/runs')
def runs():return JSONResponse([{'run':p.name,**readjson(p/'request.json'),**readjson(p/'status.json'),'evaluation':readjson(p/'evaluation.json')} for p in sorted(ROOT.iterdir(),reverse=True) if p.is_dir()])
@app.get('/runs/{name}')
def detail(name:str):
    p=runpath(name);steps=[]
    if (p/'steps.jsonl').exists():
        for line in (p/'steps.jsonl').read_text().splitlines():
            try:steps.append(json.loads(line))
            except ValueError:pass
    return JSONResponse({'steps':steps,'status':readjson(p/'status.json'),'files':{f.name:f.stat().st_size for f in p.iterdir() if f.is_file() and not f.is_symlink() and f.suffix in ('.json','.jsonl','.jpg','.csv','.log')}})
@app.get('/runs/{name}/file/{filename}')
def file(name:str,filename:str):
    p=runpath(name)/filename
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',filename) or p.suffix not in ('.json','.jsonl','.jpg','.csv','.log') or p.is_symlink() or not p.is_file():raise HTTPException(404)
    return FileResponse(p)
@app.websocket('/video')
async def video(ws:WebSocket):
    if ws.client.host!='192.168.50.1' or ws.headers.get('origin')!='http://192.168.50.2:8080':await ws.close(code=1008);return
    await ws.accept();previous=-1
    try:
        while True:
            if runtime.frame_seq!=previous:
                previous=runtime.frame_seq;await ws.send_json({'seq':previous,'images':runtime.frames})
            await asyncio.sleep(.05)
    except (WebSocketDisconnect,RuntimeError):pass

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='192.168.50.2',port=8080,access_log=False,ws_per_message_deflate=False)
