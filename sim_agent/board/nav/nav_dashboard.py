"""Navigation demo workbench on the board (port 8080). Same event contract as the Panda workbench (task 015).

Simulation-only. Fixed endpoints; no shell, credentials or arbitrary file access.
"""
import asyncio,json,os,re,subprocess,sys,threading,time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import HTMLResponse,FileResponse,JSONResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
HERE=Path(__file__).resolve().parent;AGENT=HERE.parent/'agent'
sys.path.insert(0,str(AGENT))
from link import NavLink
from nav_perception import NavPerception
import navigator as N
import nav_agent

# Defaults are the board setup; the env overrides exist only for a local PC rehearsal.
ROOT=Path(os.environ.get('RV_NAV_ROOT','/tmp/runs'));WORK=Path(os.environ.get('RV_NAV_WORK','/tmp/rv014'))
OPERATOR=os.environ.get('RV_OPERATOR_HOST','192.168.50.1');BIND=os.environ.get('RV_BIND','192.168.50.2')
SCENARIOS={'N1':{'title':'单目标：去蓝色区域','task':'去蓝色区域'},
           'N2':{'title':'多目标：绿 → 蓝 → 回起点','task':'先去绿色区域，再去蓝色区域，最后回到起点'},
           'N3':{'title':'避让：去红色区域，不经过黄色区域','task':'去红色区域，路上不要经过黄色区域'},
           'N4':{'title':'突发障碍：去红色区域（途中会落下箱子）','task':'去红色区域'}}

def readjson(p,default=None):
    try:return json.loads(Path(p).read_text())
    except (OSError,ValueError):return {} if default is None else default
def atomic(p,v):t=p.with_suffix('.new');t.write_text(json.dumps(v,ensure_ascii=False));t.replace(p)

def evaluate(scenario,truth):
    """Truth-only judgement after the run; never visible to the agent."""
    v=[x['zone'] for x in truth['visits']];final=v[-1] if v else None
    r=truth['robot'];z=truth['zones']
    inside=lambda name:abs(r['x']-z[name]['center'][0])<=z[name]['half'][0] and abs(r['y']-z[name]['center'][1])<=z[name]['half'][1]
    if scenario=='N1':ok=inside('blue')
    elif scenario=='N2':
        it=iter(v[1:]);ok=all(any(x==want for x in it) for want in ('green','blue','start')) and inside('start')
    elif scenario=='N3':ok=inside('red') and 'yellow' not in v
    elif scenario=='N4':ok=inside('red') and truth['event'] is not None
    else:return {'evaluated':False,'reason':'free-form task: no truth criterion','truth':truth}
    return {'evaluated':True,'success':bool(ok),'visits':v,'final_xy':[round(r['x'],3),round(r['y'],3)],'event':truth['event'],'path_len':round(truth['path_len'],2),'truth':truth}

class Runtime:
    def __init__(self):
        self.lock=threading.RLock();self.events=deque(maxlen=6000);self.sequence=0;self.link=None;self.driver=None;self.model=None
        self.error=None;self.run=None;self.busy=False;self.monitor=None;self.stop=threading.Event()
    def publish(self,event):
        event={'ts':time.time(),'run':self.run,**event}
        with self.lock:self.sequence+=1;self.events.append((self.sequence,event))
        if event.get('run') and event['type']!='sysmon':
            with (ROOT/event['run']/'events.jsonl').open('a') as f:f.write(json.dumps(event,ensure_ascii=False)+'\n')
    def connect(self):
        try:
            self.link=NavLink();hello=self.link.call('hello')
            self.driver=N.Driver(self.link,NavPerception(),hello)
            from agent import Model
            self.model=Model();self.error=None
        except Exception as exc:self.error=type(exc).__name__+': '+str(exc)
    def tick(self):
        while not self.stop.wait(1):
            atomic(WORK/'current.json',{'run':self.run if self.busy else None,'pids':{'dashboard':os.getpid()},'action':readjson(ROOT/self.run/'status.json').get('action','idle') if self.run else 'idle'})
            res=readjson(WORK/'sysmon.json')
            if res:self.publish({'type':'sysmon',**res})
    def worker(self,name,request):
        directory=ROOT/name
        try:nav_agent.run(directory,request,self.link,self.driver,self.model,self.publish)
        except Exception as exc:atomic(directory/'status.json',{'status':'error','error':str(exc)})
        status=readjson(directory/'status.json')
        try:result=evaluate(request.get('scenario'),self.link.call('truth'))
        except Exception as exc:result={'evaluated':False,'error':str(exc)}
        atomic(directory/'evaluation.json',result)
        self.publish({'type':'finish','success_self':(status.get('result') or {}).get('success'),'success_truth':result.get('success'),'summary':status.get('result'),'stats':status})
        self.busy=False
    def start(self,task,seed,scenario):
        with self.lock:
            if self.busy:raise HTTPException(409,'A task is already running')
            if self.model is None:raise HTTPException(503,'Simulation or model not ready: '+str(self.error))
            self.link.call('reset',seed=seed,scenario=scenario);time.sleep(.4)
            self.driver.p=NavPerception();self.driver.odom=N.Odometry(self.driver.r,self.driver.track)
            name=time.strftime('%Y%m%dT%H%M%S')+'-'+str(time.time_ns()%1000000000);(ROOT/name).mkdir()
            request={'task':task,'kind':'navigate','seed':seed,'scenario':scenario,'created_utc':time.time()}
            atomic(ROOT/name/'request.json',request);atomic(ROOT/name/'status.json',{'status':'running','step':0,'action':'启动'})
            self.run=name;self.busy=True
            self.publish({'type':'task_start','kind':'navigate','text':task,'seed':seed,'scenario':scenario})
            threading.Thread(target=self.worker,args=(name,request),daemon=True).start()
            return {'run':name}
runtime=Runtime()

@asynccontextmanager
async def lifecycle(app):
    if hasattr(os,'sched_setaffinity'):os.sched_setaffinity(0,{0})
    ROOT.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True)
    for fn in (runtime.connect,runtime.tick):threading.Thread(target=fn,daemon=True).start()
    runtime.monitor=subprocess.Popen([sys.executable,'-u',str(AGENT/'sysmon.py')])
    try:yield
    finally:
        if runtime.run and runtime.busy:(ROOT/runtime.run/'stop').touch()
        runtime.stop.set();runtime.monitor.terminate();runtime.monitor.wait(5)
        if runtime.link:runtime.link.close()

app=FastAPI(lifespan=lifecycle,docs_url=None,redoc_url=None)
app.mount('/static',StaticFiles(directory=AGENT/'static'),name='static')
class Task(BaseModel):
    task:str=Field(min_length=1,max_length=300)
    seed:int|None=Field(default=None,ge=0)
    scenario:str|None=Field(default=None,pattern='^N[1-4]$')
    kind:str|None=None
@app.middleware('http')
async def guard(request:Request,call_next):
    if request.method=='POST' and (request.client.host!=OPERATOR or request.headers.get('origin','http://%s:8080'%BIND)!='http://%s:8080'%BIND):
        return JSONResponse({'error':'local board operator only'},status_code=403)
    return await call_next(request)
def runpath(name):
    if not re.fullmatch(r'[0-9T-]+',name):raise HTTPException(404)
    p=ROOT/name
    if not p.is_dir() or p.is_symlink():raise HTTPException(404)
    return p
@app.get('/')
def index():return HTMLResponse((HERE/'nav.html').read_text(encoding='utf-8'))
@app.get('/goals')
def goals():return JSONResponse({'presets':[],'scenarios':SCENARIOS})
@app.post('/task')
def task(t:Task):return runtime.start(t.task,t.seed,t.scenario)
@app.post('/stop')
def stop():
    if runtime.run:(ROOT/runtime.run/'stop').touch()
    return {'stopping':True}
@app.get('/state')
def state():
    d=ROOT/runtime.run if runtime.run else None
    return JSONResponse({'connected':runtime.link is not None,'worker_ready':runtime.model is not None,'busy':runtime.busy,'error':runtime.error,'run':runtime.run,
                         'status':readjson(d/'status.json') if d else {},'evaluation':{k:v for k,v in readjson(d/'evaluation.json').items() if k!='truth'} if d else {}})
@app.get('/runs')
def runs():return JSONResponse([{'run':p.name,**readjson(p/'request.json'),**readjson(p/'status.json'),'evaluation':{k:v for k,v in readjson(p/'evaluation.json').items() if k!='truth'}} for p in sorted(ROOT.iterdir(),reverse=True) if p.is_dir()])
@app.get('/runs/{name}')
def detail(name:str):
    p=runpath(name);rows=lambda f:[json.loads(l) for l in (p/f).read_text().splitlines() if l.strip()] if (p/f).exists() else []
    return JSONResponse({'steps':rows('steps.jsonl'),'events':rows('events.jsonl'),'request':readjson(p/'request.json'),'status':readjson(p/'status.json'),
                         'evaluation':{k:v for k,v in readjson(p/'evaluation.json').items() if k!='truth'},'files':{f.name:f.stat().st_size for f in p.iterdir() if f.is_file()}})
@app.get('/runs/{name}/manifest')
def manifest(name:str):
    p=runpath(name);fs=[f for f in p.iterdir() if f.is_file() and not f.is_symlink() and f.suffix in ('.json','.jsonl','.jpg','.csv','.log')]
    return JSONResponse({'files':{f.name:f.stat().st_size for f in fs},'versions':{f.name:f.stat().st_mtime_ns for f in fs}})
@app.get('/runs/{name}/file/{filename}')
def file(name:str,filename:str):
    p=runpath(name)/filename
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',filename) or p.suffix not in ('.json','.jsonl','.jpg','.csv','.log') or not p.is_file():raise HTTPException(404)
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
