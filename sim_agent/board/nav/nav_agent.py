"""Navigation agent loop on the board: perception -> DeepSeek (thinking) -> navigate_to -> re-observe.

The model sees text only (robot pose, zones, previous result). Planning, driving and perception are board-side.
Truth is never read here; the dashboard evaluates afterwards.
"""
import base64,json,math,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from agent import tool,atomic
import navigator as N

TARGETS=['red','green','blue','yellow','start']
CN={'red':'红色区域','green':'绿色区域','blue':'蓝色区域','yellow':'黄色区域','start':'起点'}
TOOLS=[tool('update_plan','记录或修改计划。第一轮必须先调用；之后计划变化时再调用。不算动作，同一轮可以再调用一个动作。',
            {'goal_summary':{'type':'string'},'steps':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':10},'reason':{'type':'string'}},['goal_summary','steps','reason']),
       tool('navigate_to','让机器人移动到某个区域的中心。板子负责规划路线、避开障碍物和 avoid 里的区域。遇到路被挡住会停下并返回原因。',
            {'target':{'type':'string','enum':TARGETS},'avoid':{'type':'array','items':{'type':'string','enum':TARGETS[:4]},'description':'路上不能经过的区域'},
             'plan_step':{'type':'integer','minimum':1,'maximum':10}},['target','avoid','plan_step']),
       tool('finish','结束任务。',{'success':{'type':'boolean'},'summary':{'type':'string'}},['success','summary'])]
EXPECTED_S={'navigate_to':15,'finish':1}

def validate(call):
    fn=call.get('function',{});name=fn.get('name')
    try:args=json.loads(fn.get('arguments') or '{}')
    except ValueError:raise ValueError('arguments are not JSON') from None
    schema=next((t['function']['parameters'] for t in TOOLS if t['function']['name']==name),None)
    if schema is None or not isinstance(args,dict) or not set(schema['required'])<=set(args)<=set(schema['properties']):raise ValueError('unknown tool or wrong arguments: '+str(name))
    if name=='navigate_to':
        if args['target'] not in TARGETS or not isinstance(args['avoid'],list) or any(a not in TARGETS[:4] for a in args['avoid']):raise ValueError('unknown zone name')
        if args['target'] in args['avoid']:raise ValueError('target cannot be in avoid')
        if type(args['plan_step']) is not int:raise ValueError('plan_step must be an integer')
    if name=='finish' and (type(args['success']) is not bool or not isinstance(args['summary'],str)):raise ValueError('bad finish arguments')
    if name=='update_plan' and (not isinstance(args['steps'],list) or any(not isinstance(s,str) or len(s)>160 for s in args['steps'])):raise ValueError('bad steps')
    return name,args

def in_zone(pose,zones,start):
    if pose is None:return None
    for z,v in zones.items():
        if abs(pose['x']-v['center'][0])<=v['half'][0] and abs(pose['y']-v['center'][1])<=v['half'][1]:return z
    if start and math.dist((pose['x'],pose['y']),start)<.28:return 'start'
    return None

def pack(grid):
    """Occupancy grid -> base64 bit string for the workbench map (rows bottom->top)."""
    import numpy as np
    return {'w':int(grid.shape[1]),'h':int(grid.shape[0]),'bits':base64.b64encode(np.packbits(grid.astype(np.uint8)).tobytes()).decode()}

def run(root,request,link,driver,model,emit):
    started=time.monotonic();started_utc=time.time();tokens=0;calls_n=0;plan_version=0;actions=0;status='limit';last=None;steps=0;visited=[]
    stop=lambda:(root/'stop').exists();driver.stop=stop;driver.emit=emit;start_xy=None
    model.emit=emit   # think_delta / think_end stream to the workbench
    def state(**f):atomic(root/'status.json',dict(status='running',kind='navigate',step=steps,seconds=time.monotonic()-started,started_utc=started_utc,tokens=tokens,calls=calls_n,plan_version=plan_version,**f))
    def record(row):
        row['images']={}
        try:
            for cam in ('top','chase','front','side'):
                img=link.call('render',camera=cam,w=320,h=240);name=f'{steps:02d}-{cam}.jpg';(root/name).write_bytes(base64.b64decode(img['jpeg_b64']));row['images'][cam]=name
        except Exception as exc:row['image_error']=type(exc).__name__
        with (root/'steps.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    def observe():
        scene=driver.observe();r=scene['robot'];here=in_zone(r,scene['zones'],start_xy)
        text=('机器人 (%.2f, %.2f) 朝向 %.0f°'%(r['x'],r['y'],math.degrees(r['yaw'])) if r else '俯视相机没有看到机器人')+(' · 在'+CN[here] if here else '')
        emit({'type':'observe','summary':text+' · %.2f s'%scene['seconds'],'scene':{'robot':r,'zones':scene['zones'],'in_zone':here},'detections':scene['detections'],'map':pack(scene['grid']),'seconds':scene['seconds']})
        return scene,here
    try:
        state(action='观察场景');scene,here=observe()
        if scene['robot'] is None:raise RuntimeError('robot not visible')
        start_xy=(scene['robot']['x'],scene['robot']['y']);here='start';visited.append('start')
        navigate=make_navigate(driver,emit,lambda:start_xy,stop)
        zones_text={CN[z]:{'center':v['center'],'size':[round(2*v['half'][0],2),round(2*v['half'][1],2)]} for z,v in scene['zones'].items()}
        system=Path(__file__).with_name('nav_system.txt').read_text(encoding='utf-8')
        messages=[{'role':'system','content':system},{'role':'user','content':'任务：'+request['task']+'\n场地里的区域（板子从俯视图识别，单位 m）：'+json.dumps(zones_text,ensure_ascii=False)+'\n起点：机器人现在的位置。'}]
        for steps in range(1,13):
            if stop():status='stopped';break
            r=scene['robot']
            messages.append({'role':'user','content':'第%d轮观察（请用中文思考和回答）：'%steps+json.dumps({'round':steps,'robot':{'x':round(r['x'],2),'y':round(r['y'],2),'heading_deg':round(math.degrees(r['yaw']))} if r else None,
                'in_zone':here,'visited_in_order':visited,'previous_result':last},ensure_ascii=False)})
            chosen=None
            for _ in range(3):
                state(action='调用 DeepSeek');began=time.monotonic()
                response,body,retries=model.call(messages,tools=TOOLS,tool_choice='auto',thinking=True)
                calls_n+=1;msg=response['choices'][0]['message'];usage=response.get('usage',{});tokens+=usage.get('total_tokens',0)
                messages.append({k:v for k,v in msg.items() if k in ('role','content','reasoning_content','tool_calls')})
                calls=msg.get('tool_calls') or [];row={'step':steps,'response':msg,'usage':usage,'api_seconds':time.monotonic()-began,'retries':retries}
                if not calls:messages.append({'role':'user','content':'请调用工具：需要的话先 update_plan，然后调用一个动作工具。'});continue
                results={};acts=[]
                for call in calls:
                    try:name,args=validate(call)
                    except ValueError as exc:results[call['id']]={'ok':False,'error':str(exc)};continue
                    if name=='update_plan':
                        plan_version+=1;emit({'type':'plan','version':plan_version,'steps':args['steps'],'reason':args['reason'],'goal_summary':args['goal_summary']})
                        results[call['id']]={'ok':True,'plan_version':plan_version}
                    else:acts.append((call,name,args))
                if acts and plan_version==0:
                    for c,_,_ in acts:results[c['id']]={'ok':False,'error':'第一轮必须先调用 update_plan'}
                    acts=[]
                if len(acts)>1:
                    for c,_,_ in acts:results[c['id']]={'ok':False,'error':'每轮只能调用一个动作工具'}
                    acts=[]
                if acts:
                    call,name,args=acts[0];chosen=name;began=time.monotonic();idx=args.get('plan_step',actions+1)
                    emit({'type':'step_start','index':idx,'tool':name,'args':{k:v for k,v in args.items() if k!='plan_step'},'expected_s':EXPECTED_S[name]})
                    state(action=name+' '+json.dumps(args,ensure_ascii=False))
                    if name=='navigate_to':last=navigate(args)
                    else:last={'ok':True,**args};status='finished' if args['success'] else 'model_failed'
                    actions+=1;results[call['id']]=last
                    emit({'type':'step_result','ok':last['ok'],'index':idx,'tool':name,'detail':last})
                    row.update(tool=name,arguments=args,result=last,seconds=time.monotonic()-began)
                for call in calls:messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(results.get(call['id'],{'ok':False,'error':'not executed'}),ensure_ascii=False)})
                record(row)
                if acts:break
            if status in ('finished','model_failed','stopped'):break
            if chosen=='navigate_to':scene,here=observe()
            if here and (not visited or visited[-1]!=here):visited.append(here)
    except Exception as exc:status='api_error' if 'api_error' in str(exc) else 'error';last={'ok':False,'error':str(exc)}
    finally:
        try:driver.drive(0,0)
        except Exception:pass
        atomic(root/'status.json',{'status':status,'kind':'navigate','step':steps,'actions':actions,'plan_version':plan_version,'replans':max(0,plan_version-1),'calls':calls_n,
                                   'seconds':time.monotonic()-started,'started_utc':started_utc,'finished_utc':time.time(),'tokens':tokens,'result':last,'visited':visited})


def make_navigate(driver,emit,get_start,stop):
    def navigate(args):
        scene=driver.observe();r=scene['robot']
        if r is None:return {'ok':False,'error':'俯视相机没有看到机器人'}
        target=args['target']
        if target=='start':goal=get_start()
        elif target in scene['zones']:goal=tuple(scene['zones'][target]['center'])
        else:return {'ok':False,'error':CN[target]+'不在视野里'}
        try:path,length=N.plan(scene['grid'],(r['x'],r['y']),goal,scene['zones'],args['avoid'])
        except ValueError as exc:return {'ok':False,'error':'规划失败：'+str(exc)}
        emit({'type':'nav_plan','path':[[round(a,3),round(b,3)] for a,b in path],'length':round(length,2),'target':target,'avoid':args['avoid']})
        t=time.monotonic();res=driver.follow(path,scene['grid'])
        out={'ok':res['ok'],'target':target,'planned_m':round(length,2),'travelled_m':round(res['travelled'],2),'seconds':round(time.monotonic()-t,1)}
        if not res['ok']:out['error']=res['reason'];out.update({k:v for k,v in res.items() if k=='blocked_at'})
        return out
    return navigate
