"""Board-only dashboard. Fixed endpoints; no shell, credentials or arbitrary file access."""
import asyncio,base64,json,os,re,socketserver,subprocess,sys,threading,time
from pathlib import Path
from contextlib import asynccontextmanager
from collections import deque
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import HTMLResponse,FileResponse,JSONResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from transport import SimClient
from local_rpc import PATH
from goal_store import GoalStore,evaluate_goal

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

# Task 015 acceptance scenes: initial layout (bottom→top) and the preset goal image to stack from.
SCENARIOS={'G1':{'layout':{'towers':[],'loose':['red','green','blue','orange']},'goal':'blue-red-green','title':'4 块散放 → 蓝·红·绿'},
           'G2':{'layout':{'towers':[['blue','green']]},'goal':'blue-red-green','title':'绿压在蓝上 → 蓝·红·绿'},
           'G3':{'layout':{'towers':[['blue','red']]},'goal':'red-green-blue','title':'红压在蓝上 → 红·绿·蓝'},
           'G4':{'layout':{'towers':[['orange','red'],['blue','green']]},'goal':'two-red-orange-green-blue','title':'两座塔顺序都反 → 红·橙 / 绿·蓝'}}
def random_goal(seed):
    import random
    rng=random.Random(seed);colors=['red','green','blue','orange'];rng.shuffle(colors)
    sizes=rng.choice([(3,),(4,),(2,2),(3,1),(2,1)])
    towers=[];offset=0
    for size in sizes:towers.append(colors[offset:offset+size]);offset+=size
    return {'towers':[t for t in towers if len(t)>1]}

class Runtime:
    def __init__(self):
        self.lock=threading.RLock();self.sim=None;self.error=None
        self.process=None;self.run=None;self.monitor=None;self.stop=threading.Event()
        self.ready=False;self.busy=False;self.events=deque(maxlen=4096);self.sequence=0;self.goals=None
    def publish(self,event):
        event={'ts':time.time(),'run':self.run,**event}
        with self.lock:
            self.sequence+=1;self.events.append((self.sequence,event))
        if event.get('run') and event['type']!='sysmon':
            with (ROOT/event['run']/'events.jsonl').open('a') as f:f.write(json.dumps(event,ensure_ascii=False)+'\n')
    def call(self,op,**args):
        with self.lock:
            if self.sim is None:raise RuntimeError('simulation not connected')
            return self.sim.call(op,**args)
    def connect(self):
        try:self.sim=SimClient(timeout=3600);self.error=None
        except Exception as exc:self.error=type(exc).__name__
    def worker_events(self):
        for line in self.process.stdout:
            try:event=json.loads(line)
            except ValueError:continue
            if event['type']=='worker_ready':self.ready=True
            elif event['type']=='worker_done':self.busy=False
            else:self.publish(event)
        self.ready=False;self.busy=False;self.error='worker exited'
    def tick(self):
        while not self.stop.wait(1):
            status=readjson(ROOT/self.run/'status.json') if self.run else {}
            pids={'dashboard':os.getpid()}
            try:pids['rt_ctl']=int((WORK/'rt.pid').read_text())
            except (OSError,ValueError):pass
            if self.monitor:pids['sysmon']=self.monitor.pid
            if self.process and self.process.poll() is None:pids['agent']=self.process.pid
            atomic(WORK/'current.json',{'run':self.run if self.busy else None,'pids':pids,'action':status.get('action',status.get('status','idle'))})
            resources=readjson(WORK/'sysmon.json')
            if resources:self.publish({'type':'sysmon',**resources})
            if self.run and not self.busy:
                directory=ROOT/self.run
                if not (directory/'evaluation.json').exists():
                    try:
                        request=readjson(directory/'request.json');objects=self.call('objects')
                        if request.get('kind') in ('goal_stack','baseline'):
                            truth=readjson(directory/'truth_goal.json')
                            result={'evaluated':True,'success':evaluate_goal(truth,objects),'goal':truth,'objects':objects}
                        else:result=evaluate(request['task'],objects)
                        atomic(directory/'evaluation.json',result)
                    except Exception as exc:result={'evaluated':False,'error':str(exc)};atomic(directory/'evaluation.json',result)
                    if status.get('status','running')=='running':
                        status={'status':'error','reason':'worker exited unexpectedly'};atomic(directory/'status.json',status)
                    self.publish({'type':'finish','run':directory.name,'success_self':status.get('result',{}).get('success'), 'success_truth':result.get('success'),'summary':status.get('result'),'stats':status})
    def start(self,task,seed,kind='instruction',goal_id=None,scenario=None,confirmed=False):
        with self.lock:
            if self.busy:raise HTTPException(409,'A task is already running')
            if not self.ready:raise HTTPException(503,'Agent is warming up')
            if self.sim is None:raise HTTPException(503,'Simulation not connected')
            # Ensure the preceding task has received its independent assessment.
            if self.run and not (ROOT/self.run/'evaluation.json').exists():raise HTTPException(409,'Previous assessment pending')
            goal=layout=None;goal_event=None
            if kind in ('goal_stack','baseline'):
                if scenario:
                    if scenario not in SCENARIOS:raise HTTPException(400,'unknown scenario')
                    layout=SCENARIOS[scenario]['layout']
                    if not goal_id:goal_id=self.goals.recognize(preset=SCENARIOS[scenario]['goal'])['id']
                if not goal_id:raise HTTPException(400,'goal image required')
                try:item=self.goals.get(goal_id)
                except ValueError as exc:raise HTTPException(409,str(exc))
                recognition=item['recognition']
                if not recognition['towers']:raise HTTPException(422,'no tower recognized in goal image')
                if recognition['confidence']<.8 and not confirmed:raise HTTPException(409,'goal recognition uncertain; confirm first')
                goal={'towers':recognition['towers']}
                goal_event={**goal,'loose':recognition['loose'],'image_url':item['image_url'],'confidence':recognition['confidence']}
            if seed is not None or layout is not None:self.call('reset',seed=seed,layout=layout);time.sleep(.5)
            name=time.strftime('%Y%m%dT%H%M%S')+'-'+str(time.time_ns()%1000000000);directory=ROOT/name;directory.mkdir()
            request={'task':task,'kind':kind,'seed':seed,'created_utc':time.time()}
            if goal:
                request.update(goal=goal,goal_image=item['image_url'],confidence=recognition['confidence'],scenario=scenario,layout=layout)
                # Truth goal is for the evaluator only; the worker reads request.json and never this file.
                atomic(directory/'truth_goal.json',item['truth_goal'])
                (directory/'goal.jpg').write_bytes((self.goals.cache/(item['id']+'.jpg')).read_bytes())
            atomic(directory/'request.json',request);atomic(directory/'status.json',{'status':'running','step':0,'action':'启动'})
            self.run=name;self.busy=True
            self.publish({'type':'task_start','kind':kind,'text':task,'goal':goal_event,'seed':seed,'scenario':scenario})
            try:self.process.stdin.write(json.dumps({'run':name})+'\n');self.process.stdin.flush()
            except OSError:self.busy=False;raise HTTPException(503,'Worker unavailable')
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
    os.sched_setaffinity(0,{0});ROOT.mkdir(exist_ok=True);WORK.mkdir(exist_ok=True);runtime.goals=GoalStore(WORK)
    if Path(PATH).exists():raise RuntimeError('Broker socket already exists; inspect previous process before starting')
    broker=Broker(PATH,Handler);os.chmod(PATH,0o600)
    evaluator=Broker('/tmp/rv014/evaluation.sock',EvaluationHandler);os.chmod('/tmp/rv014/evaluation.sock',0o600)
    for fn in (broker.serve_forever,evaluator.serve_forever,runtime.connect,runtime.tick):threading.Thread(target=fn,daemon=True).start()
    runtime.monitor=subprocess.Popen([sys.executable,'-u',str(Path(__file__).with_name('sysmon.py'))])
    runtime.process=subprocess.Popen([sys.executable,'-u',str(Path(__file__).with_name('worker.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=None,text=True,env={**os.environ,'OPENBLAS_NUM_THREADS':'1','PYTHONDONTWRITEBYTECODE':'1'})
    threading.Thread(target=runtime.worker_events,daemon=True).start()
    try:yield
    finally:
        if runtime.process and runtime.process.poll() is None:
            if runtime.run:(ROOT/runtime.run/'stop').touch()
            runtime.process.stdin.write('null\n');runtime.process.stdin.flush()
            try:await asyncio.to_thread(runtime.process.wait,120)
            except subprocess.TimeoutExpired:runtime.process.terminate();await asyncio.to_thread(runtime.process.wait,10)
        runtime.stop.set();runtime.monitor.terminate();runtime.monitor.wait(5);broker.shutdown();broker.server_close();Path(PATH).unlink(missing_ok=True)
        evaluator.shutdown();evaluator.server_close();Path('/tmp/rv014/evaluation.sock').unlink(missing_ok=True)
        if runtime.sim:runtime.sim.close()

app=FastAPI(lifespan=lifecycle,docs_url=None,redoc_url=None)
app.mount('/static',StaticFiles(directory=Path(__file__).with_name('static')),name='static')
class Task(BaseModel):
    task:str=Field(min_length=1,max_length=500)
    seed:int|None=Field(default=None,ge=0)
    kind:str=Field(default='instruction',pattern='^(instruction|goal_stack|baseline)$')
    goal_id:str|None=Field(default=None,pattern='^[0-9a-f]{32}$')
    scenario:str|None=Field(default=None,pattern='^G[1-4]$')
    confirmed:bool=False
class GoalRequest(BaseModel):
    preset:str|None=Field(default=None,pattern='^[a-z0-9-]{1,64}$')
    image_b64:str|None=Field(default=None,max_length=6*1024*1024)
    random_seed:int|None=Field(default=None,ge=0)
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
def start_task(request:Task):return runtime.start(request.task,request.seed,request.kind,request.goal_id,request.scenario,request.confirmed)
@app.get('/goals')
def goals():return JSONResponse({'presets':runtime.goals.catalog(),'scenarios':{k:{'title':v['title'],'goal':v['goal']} for k,v in SCENARIOS.items()}})
@app.post('/goals/recognize')
def recognize_goal(request:GoalRequest):
    try:
        if request.random_seed is not None:
            # Random goal: the simulator renders it with an independent MjData; the board then reads the image like any other.
            goal=random_goal(request.random_seed);image=runtime.call('goal_image',goal=goal,style='front')
            return JSONResponse(runtime.goals.recognize(image_b64=image['jpeg_b64'],truth=goal))
        return JSONResponse(runtime.goals.recognize(preset=request.preset,image_b64=request.image_b64))
    except (ValueError,OSError) as exc:raise HTTPException(422,str(exc))
@app.get('/goal-images/{name}')
def goal_image(name:str):
    if not re.fullmatch(r'[0-9a-f]{32}\.jpg',name):raise HTTPException(404)
    p=runtime.goals.cache/name
    if not p.is_file():raise HTTPException(404)
    return FileResponse(p)
@app.post('/stop')
def stop_task():
    if runtime.run:(ROOT/runtime.run/'stop').touch()
    return {'stopping':True,'message':'当前技能结束后回到 home'}
@app.get('/state')
def state():
    directory=ROOT/runtime.run if runtime.run else None
    return JSONResponse({'connected':runtime.sim is not None,'error':runtime.error,'run':runtime.run,'status':readjson(directory/'status.json') if directory else {},
            'evaluation':readjson(directory/'evaluation.json') if directory else {},'resources':readjson(WORK/'sysmon.json'),'worker_ready':runtime.ready,'busy':runtime.busy})
@app.get('/runs')
def runs():return JSONResponse([{'run':p.name,**readjson(p/'request.json'),**readjson(p/'status.json'),'evaluation':readjson(p/'evaluation.json')} for p in sorted(ROOT.iterdir(),reverse=True) if p.is_dir()])
@app.get('/runs/{name}')
def detail(name:str):
    p=runpath(name);steps=[]
    if (p/'steps.jsonl').exists():
        for line in (p/'steps.jsonl').read_text().splitlines():
            try:steps.append(json.loads(line))
            except ValueError:pass
    events=[]
    if (p/'events.jsonl').exists():
        for line in (p/'events.jsonl').read_text().splitlines():
            try:events.append(json.loads(line))
            except ValueError:pass
    return JSONResponse({'steps':steps,'events':events,'request':readjson(p/'request.json'),'evaluation':{k:v for k,v in readjson(p/'evaluation.json').items() if k!='objects'},'status':readjson(p/'status.json'),'files':{f.name:f.stat().st_size for f in p.iterdir() if f.is_file() and not f.is_symlink() and f.suffix in ('.json','.jsonl','.jpg','.csv','.log')}})
@app.get('/runs/{name}/manifest')
def manifest(name:str):
    p=runpath(name);files={};versions={}
    for f in p.iterdir():
        if f.is_file() and not f.is_symlink() and f.suffix in ('.json','.jsonl','.jpg','.csv','.log'):
            info=f.stat();files[f.name]=info.st_size;versions[f.name]=info.st_mtime_ns
    return JSONResponse({'files':files,'versions':versions})
@app.get('/runs/{name}/file/{filename}')
def file(name:str,filename:str):
    p=runpath(name)/filename
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',filename) or p.suffix not in ('.json','.jsonl','.jpg','.csv','.log') or p.is_symlink() or not p.is_file():raise HTTPException(404)
    return FileResponse(p)
@app.get('/events')
async def events(request:Request):
    if request.client.host!='192.168.50.1':raise HTTPException(403)
    try:cursor=int(request.headers.get('last-event-id','0'))
    except ValueError:raise HTTPException(400)
    async def generate():
        nonlocal cursor
        while not await request.is_disconnected():
            with runtime.lock:batch=[(n,e) for n,e in runtime.events if n>cursor]
            for n,event in batch:
                cursor=n
                yield 'id: '+str(n)+'\ndata: '+json.dumps(event,ensure_ascii=False)+'\n\n'
            if not batch:yield ': heartbeat\n\n'
            await asyncio.sleep(.1 if batch else 1)
    return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-cache'})

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='192.168.50.2',port=8080,access_log=False,ws_per_message_deflate=False,timeout_graceful_shutdown=3)
