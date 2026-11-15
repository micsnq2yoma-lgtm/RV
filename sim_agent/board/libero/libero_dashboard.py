"""LIBERO demo workbench on the board (port 8080). Same event contract as the Panda and nav workbenches.

The PC runs libero_server.py --agent-ip 192.168.50.2 (simulation, rendering, MJPEG on 127.0.0.1:8093 for the
browser); this process runs perception, skills and the DeepSeek agent. Simulation only.
"""
import asyncio,base64,json,os,re,subprocess,sys,threading,time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import HTMLResponse,FileResponse,JSONResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
HERE=Path(__file__).resolve().parent;AGENT=HERE.parent/'agent'
sys.path.insert(0,str(HERE));sys.path.insert(0,str(AGENT));sys.path.insert(0,str(HERE.parent/'nav'))
from link import NavLink
import libero_agent as A

ROOT=Path(os.environ.get('RV_LIBERO_ROOT','/tmp/runs'));WORK=Path(os.environ.get('RV_LIBERO_WORK','/tmp/rv014'))
OPERATOR=os.environ.get('RV_OPERATOR_HOST','192.168.50.1');BIND=os.environ.get('RV_BIND','192.168.50.2')
# Tasks the current tool set (pick / place_on / place_in) can attempt; language is LIBERO's own instruction.
TASKS={'libero_spatial':range(10),'libero_object':range(10),'libero_goal':(1,2,4,6,8,9),'libero_10':(0,1,4,7,8)}

def readjson(p,default=None):
    try:return json.loads(Path(p).read_text())
    except (OSError,ValueError):return {} if default is None else default
def atomic(p,v):t=p.with_suffix('.new');t.write_text(json.dumps(v,ensure_ascii=False));t.replace(p)

class RecordingLink:
    """Wraps the simulator link: after every observe, saves both camera frames for replay."""
    def __init__(self,link):self.link=link;self.dir=None;self.n=0
    def call(self,op,**a):
        r=self.link.call(op,**a)
        if op=='observe' and self.dir is not None:
            self.n+=1;imgs={}
            for cam,c in r['cameras'].items():
                name=f'{self.n:02d}-{cam}.jpg';(self.dir/name).write_bytes(base64.b64decode(c['rgb_jpg']));imgs[cam]=name
            with (self.dir/'steps.jsonl').open('a') as f:f.write(json.dumps({'step':self.n,'images':imgs,'eef_pos':r['eef_pos']})+'\n')
        return r

class Runtime:
    def __init__(self):
        self.lock=threading.RLock();self.events=deque(maxlen=6000);self.sequence=0;self.link=None;self.model=None;self.error=None
        self.run=None;self.busy=False;self.stop=threading.Event();self.monitor=None;self.tasks={}
    def publish(self,event):
        event={'ts':time.time(),'run':self.run,**event}
        with self.lock:self.sequence+=1;self.events.append((self.sequence,event))
        if event.get('run') and event['type']!='sysmon':
            with (ROOT/event['run']/'events.jsonl').open('a') as f:f.write(json.dumps(event,ensure_ascii=False)+'\n')
    def connect(self):
        try:
            self.link=RecordingLink(NavLink(port=15004));self.link.call('hello')
            self.model=A.Model() if os.environ.get('DEEPSEEK_API_KEY') is None else A.local_model();self.error=None
        except Exception as exc:self.error=type(exc).__name__+': '+str(exc)
    def tick(self):
        while not self.stop.wait(1):
            atomic(WORK/'current.json',{'run':self.run if self.busy else None,'pids':{'dashboard':os.getpid()},'action':'running' if self.busy else 'idle'})
            res=readjson(WORK/'sysmon.json')
            if res:self.publish({'type':'sysmon',**res})
    def worker(self,name,task):
        d=ROOT/name;self.link.dir=d;self.link.n=0
        try:r=A.run(self.link,self.model,self.publish,task,stop=lambda:(d/'stop').exists())
        except Exception as exc:r={'status':'error','error':str(exc)}
        self.link.dir=None
        atomic(d/'status.json',r);atomic(d/'evaluation.json',{'evaluated':'truth' in r,'success':r.get('truth')})
        self.busy=False
    def start(self,spec):
        with self.lock:
            if self.busy:raise HTTPException(409,'A task is already running')
            if self.model is None:raise HTTPException(503,'Simulator or model not ready: '+str(self.error))
            suite,_,idx=spec.partition(':')
            if suite not in TASKS or not idx.isdigit() or int(idx) not in TASKS[suite]:raise HTTPException(400,'unknown task')
            name=time.strftime('%Y%m%dT%H%M%S')+'-'+str(time.time_ns()%1000000000);(ROOT/name).mkdir()
            req={'task':spec,'kind':'libero','scenario':spec,'created_utc':time.time()};atomic(ROOT/name/'request.json',req)
            atomic(ROOT/name/'status.json',{'status':'running'});self.run=name;self.busy=True
            threading.Thread(target=self.worker,args=(name,{'suite':suite,'task':int(idx),'init':0}),daemon=True).start()
            return {'run':name}
runtime=Runtime()

@asynccontextmanager
async def lifecycle(app):
    if hasattr(os,'sched_setaffinity'):os.sched_setaffinity(0,{0})
    ROOT.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True)
    for fn in (runtime.connect,runtime.tick):threading.Thread(target=fn,daemon=True).start()
    runtime.monitor=subprocess.Popen([sys.executable,'-u',str(AGENT/'sysmon.py')]) if sys.platform.startswith('linux') else None
    try:yield
    finally:
        if runtime.run and runtime.busy:(ROOT/runtime.run/'stop').touch()
        runtime.stop.set()
        if runtime.monitor:runtime.monitor.terminate();runtime.monitor.wait(5)

app=FastAPI(lifespan=lifecycle,docs_url=None,redoc_url=None)
app.mount('/static',StaticFiles(directory=AGENT/'static'),name='static')
class Task(BaseModel):
    task:str=Field(default='',max_length=300)
    scenario:str|None=Field(default=None,pattern=r'^libero_[a-z0-9]+:\d{1,2}$')
    seed:int|None=None
    kind:str|None=None
@app.middleware('http')
async def guard(request:Request,call_next):
    if request.method=='POST' and request.client.host!=OPERATOR:return JSONResponse({'error':'local board operator only'},status_code=403)
    return await call_next(request)
def runpath(name):
    if not re.fullmatch(r'[0-9T-]+',name):raise HTTPException(404)
    p=ROOT/name
    if not p.is_dir() or p.is_symlink():raise HTTPException(404)
    return p
@app.get('/')
def index():return HTMLResponse((HERE/'libero.html').read_text(encoding='utf-8'))
@app.get('/goals')
def goals():
    lang=readjson(HERE/'libero_tasks.json')
    return JSONResponse({'presets':[],'scenarios':{f'{s}:{i}':{'title':lang.get(f'{s}:{i}',f'{s} {i}'),'task':lang.get(f'{s}:{i}',f'{s}:{i}')} for s,ids in TASKS.items() for i in ids}})
@app.post('/task')
def task(t:Task):return runtime.start(t.scenario or t.task)
@app.post('/stop')
def stop():
    if runtime.run:(ROOT/runtime.run/'stop').touch()
    return {'stopping':True}
@app.get('/state')
def state():
    d=ROOT/runtime.run if runtime.run else None
    return JSONResponse({'connected':runtime.link is not None,'worker_ready':runtime.model is not None,'busy':runtime.busy,'error':runtime.error,'run':runtime.run,
                         'status':readjson(d/'status.json') if d else {},'evaluation':readjson(d/'evaluation.json') if d else {}})
@app.get('/runs')
def runs():return JSONResponse([{'run':p.name,**readjson(p/'request.json'),**readjson(p/'status.json'),'evaluation':readjson(p/'evaluation.json')} for p in sorted(ROOT.iterdir(),reverse=True) if p.is_dir() and (p/'request.json').exists()])
@app.get('/runs/{name}')
def detail(name:str):
    p=runpath(name);rows=lambda f:[json.loads(l) for l in (p/f).read_text().splitlines() if l.strip()] if (p/f).exists() else []
    return JSONResponse({'steps':rows('steps.jsonl'),'events':rows('events.jsonl'),'request':readjson(p/'request.json'),'status':readjson(p/'status.json'),'evaluation':readjson(p/'evaluation.json')})
@app.get('/runs/{name}/manifest')
def manifest(name:str):
    p=runpath(name);fs=[f for f in p.iterdir() if f.is_file() and f.suffix in ('.json','.jsonl','.jpg')]
    return JSONResponse({'files':{f.name:f.stat().st_size for f in fs},'versions':{f.name:f.stat().st_mtime_ns for f in fs}})
@app.get('/runs/{name}/file/{filename}')
def file(name:str,filename:str):
    p=runpath(name)/filename
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',filename) or p.suffix not in ('.json','.jsonl','.jpg') or not p.is_file():raise HTTPException(404)
    return FileResponse(p)
@app.get('/events')
async def events(request:Request):
    if request.client.host!=OPERATOR:raise HTTPException(403)
    try:cursor=int(request.headers.get('last-event-id','0'))
    except ValueError:raise HTTPException(400)
    async def gen():
        nonlocal cursor
        while not await request.is_disconnected():
            with runtime.lock:batch=[(n,e) for n,e in runtime.events if n>cursor]
            for n,e in batch:cursor=n;yield 'id: '+str(n)+'\ndata: '+json.dumps(e,ensure_ascii=False)+'\n\n'
            if not batch:yield ': heartbeat\n\n'
            await asyncio.sleep(.1 if batch else 1)
    return StreamingResponse(gen(),media_type='text/event-stream',headers={'Cache-Control':'no-cache'})

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host=BIND,port=8080,access_log=False,timeout_graceful_shutdown=3)
