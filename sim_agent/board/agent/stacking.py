"""Goal-image stacking (task 015). Board-side multi-view perception and DeepSeek planning.

The goal arrives as text that the board recognized from the goal image; the image itself is
never sent to the model. Truth (`objects`) is never read here; the dashboard evaluates afterwards.
"""
import base64,json,time
from pathlib import Path
import numpy as np
from agent import tool,atomic,tray_slot
from goal_perception import COLORS
from perception import Perception,TRAYS
from skills import Stopped
from stack_perception import StackPerception

CUBES=[c+'_cube' for c in COLORS]
LEVEL=.04
STEP={'type':'integer','minimum':1,'maximum':20,'description':'这个动作对应当前计划里的第几步（从 1 开始）'}
TOOLS=[tool('update_plan','记录或修改计划。第一轮必须先调用；之后每次改计划也要调用。它不算动作，同一轮可以再调用一个动作。',
            {'goal_summary':{'type':'string','description':'一句话复述目标结构'},
             'steps':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':16,'description':'每一步对应一个动作工具'},
             'reason':{'type':'string','description':'为什么这样规划；重新规划时写清原因'}},['goal_summary','steps','reason']),
       tool('pick','抓起一块积木。只能抓塔顶或桌面上单独的积木，手里必须是空的。',{'object':{'type':'string','enum':CUBES},'plan_step':STEP},['object','plan_step']),
       tool('stack_on','把手里的积木叠到指定积木上。目标必须是塔顶或单独的积木。',{'object':{'type':'string','enum':CUBES},'plan_step':STEP},['object','plan_step']),
       tool('place_on_table','把手里的积木放到桌面上的空位（板子自动找位置）。',{'plan_step':STEP},['plan_step']),
       tool('place_in','把手里的积木放进托盘空位。',{'tray':{'type':'string','enum':list(TRAYS)},'plan_step':STEP},['tray','plan_step']),
       tool('home','机械臂回到初始位置（手里有积木时保持夹住）。',{},[]),
       tool('finish','结束任务。只有当前塔结构和目标一致时才能 success=true。',{'success':{'type':'boolean'},'summary':{'type':'string'}},['success','summary'])]
ACTIONS={t['function']['name'] for t in TOOLS}-{'update_plan'}
EXPECTED_S={'pick':7,'stack_on':9,'place_on_table':9,'place_in':9,'home':3,'finish':1}

def validate(call):
    fn=call.get('function',{});name=fn.get('name')
    try:args=json.loads(fn.get('arguments') or '{}')
    except ValueError:raise ValueError('arguments are not JSON') from None
    schema=next((t['function']['parameters'] for t in TOOLS if t['function']['name']==name),None)
    if schema is None or not isinstance(args,dict):raise ValueError('unknown tool '+str(name))
    if not set(schema['required'])<=set(args)<=set(schema['properties']):raise ValueError('wrong arguments for '+name)
    for key,value in args.items():
        spec=schema['properties'][key]
        if 'enum' in spec and value not in spec['enum']:raise ValueError('unknown name '+str(value))
        if spec['type']=='boolean' and type(value) is not bool:raise ValueError(key+' must be boolean')
        if spec['type']=='integer' and (type(value) is not int or not spec['minimum']<=value<=spec['maximum']):raise ValueError(key+' out of range')
        if spec['type']=='string' and (not isinstance(value,str) or len(value)>600):raise ValueError('invalid text')
        if spec['type']=='array' and (not isinstance(value,list) or not 1<=len(value)<=16 or any(not isinstance(s,str) or len(s)>200 for s in value)):raise ValueError('invalid steps')
    return name,args

def short(name):return name.removesuffix('_cube')

def describe(scene,holding):
    """Text the model sees: towers bottom→top, loose cubes, held cube, occlusion flags."""
    occluded=[o['name'] for o in scene['objects'] if o.get('occluded') and o.get('in')!='gripper']
    return {'towers':[[c+'_cube' for c in t] for t in scene['towers']],'loose':[c+'_cube' for c in scene['loose']],
            'holding':holding,'occluded_or_inferred':occluded}

def goal_text(goal):
    lines=[]
    for i,t in enumerate(goal['towers'],1):lines.append(f'塔{i}（自下而上）：'+' → '.join(c+'_cube' for c in t))
    extra=[c+'_cube' for c in COLORS if all(c not in t for t in goal['towers'])]
    if extra:lines.append('不在目标里的积木：'+'、'.join(extra)+'（放在哪里都行，但不能压在目标塔上）')
    return '\n'.join(lines)

def check(goal,scene,holding):
    """Board-side comparison of perceived structure against the goal (no truth)."""
    if holding:return {'matched':False,'missing':'手里还拿着 '+holding}
    have=[list(t) for t in scene['towers']];problems=[]
    for t in goal['towers']:
        if list(t) in have:continue
        near=next((h for h in have if h[0]==t[0]),None)
        problems.append(f"目标塔 {'·'.join(t)}：当前 {'·'.join(near) if near else '没有以 '+t[0]+' 为底的塔'}")
    return {'matched':not problems,'problems':problems}

def table_spot(scene,trays,avoid=()):
    """Free table cell away from towers, trays and the robot base, chosen on the board."""
    taken=[np.asarray(o['xy']) for o in scene['objects'] if o.get('xy') is not None and o.get('in')!='gripper']+[np.asarray(p) for p in avoid]
    best=None
    for x in np.arange(.50,.781,.035):
        for y in np.arange(-.21,.211,.035):
            p=np.array([x,y])
            # Open fingers reach ~5 cm sideways; the tray walls stand at |y|~.21, so stay at |y|<=.15 alongside a tray.
            if any(abs(x-t[0])<.17 and abs(abs(y)-abs(t[1]))<.155 and np.sign(y)==np.sign(t[1]) for t in trays.values()):continue
            clearance=min((float(np.linalg.norm(p-q)) for q in taken),default=1.)
            if clearance<.085:continue
            score=min(clearance,.14)-.25*float(np.linalg.norm(p-[.62,0]))
            if best is None or score>best[0]:best=(score,p)
    if best is None:raise ValueError('no free table spot found')
    return best[1].tolist()

def run_goal(root,request,sim,rt,skills,model,emit):
    """Model loop for goal_stack, or the fixed no-planning baseline when kind=='baseline'."""
    goal=request['goal'];baseline=request.get('kind')=='baseline'
    vision=StackPerception();holding=None;trays={};placed_spots=[]
    started=time.monotonic();started_utc=time.time();tokens=0;calls_n=0;last=None;status='limit';steps=0;plan_version=0;actions=0
    stop=lambda:(root/'stop').exists();skills.stop_check=stop
    def state(**fields):atomic(root/'status.json',dict(status='running',kind=request.get('kind'),step=steps,holding=holding,seconds=time.monotonic()-started,started_utc=started_utc,tokens=tokens,calls=calls_n,plan_version=plan_version,**fields))
    def record(row):
        row['images']={}
        try:
            images=sim.call('render_multi',cameras=['top','front','side','wrist'],w=320,h=240)['images']
            for camera,data in images.items():
                name=f'{steps:02d}-{camera}.jpg';(root/name).write_bytes(base64.b64decode(data['jpeg_b64']));row['images'][camera]=name
        except Exception as exc:row['image_error']=type(exc).__name__
        with (root/'steps.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    def observe():
        began=time.perf_counter()
        images=sim.call('render_multi',cameras=['top','front','side'],w=640,h=480)['images']
        if not trays:
            for o in Perception().observe(images['top'])['objects']:
                if o['name'] in TRAYS and o.get('xy'):trays[o['name']]=o['xy']
        scene=vision.observe(images,holding)
        seconds=time.perf_counter()-began
        emit({'type':'observe','scene':{**describe(scene,holding),'objects':scene['objects']},'detections':[{'name':d['name'],'bbox':d['bbox']} for d in scene['detections']],'seconds':seconds})
        return scene
    def find(scene,name):
        obj=next((o for o in scene['objects'] if o['name']==name),None)
        if obj is None or obj.get('xy') is None:raise ValueError(name+' 位置未知；先 home 再观察')
        return obj
    def on_top(scene,name):
        for t in scene['towers']:
            if short(name) in t and t[-1]!=short(name):
                above=t[t.index(short(name))+1:]
                raise ValueError(f"{name} 上面还有 {'、'.join(c+'_cube' for c in above)}，只能操作塔顶的积木")
    def execute(action,args,scene):
        nonlocal holding,status
        if action=='pick':
            name=args['object']
            if holding:raise ValueError('手里已经有 '+holding)
            if not baseline:on_top(scene,name)
            obj=find(scene,name)
            if not skills.pick(*obj['xy'],z=obj['z_est']+.003):
                skills.home();raise RuntimeError('夹爪宽度不像夹住了积木（可能被推开），已回到初始位置')
            holding=name;vision.expected.pop(short(name),None)
            return {'ok':True,'holding':name,'gripper_m':round(rt.call()['gripper'],4)}
        if action in ('stack_on','place_on_table','place_in'):
            if not holding:raise ValueError('手里是空的')
            if action=='stack_on':
                target=args['object']
                if target==holding:raise ValueError('不能叠在自己身上')
                if not baseline:on_top(scene,target)
                obj=find(scene,target);x,y=obj['xy'];z=obj['z_est']+LEVEL
                if 'level_hint' in args:z=.02+LEVEL*args['level_hint']
                surface='on:'+target
            elif action=='place_on_table':
                x,y=table_spot(scene,trays,placed_spots);z=skills.table_z+.021;surface='table'
            else:
                if args['tray'] not in trays:raise ValueError('没有看到 '+args['tray'])
                x,y=trays[args['tray']];x=tray_slot(x,[],[p[0] for p in placed_spots if abs(p[1]-y)<.08]);z=skills.table_z+.028;surface=args['tray']
            skills.place(x,y,z);vision.placed(holding,(x,y),z);placed_spots.append((x,y))
            name=holding;holding=None
            if not baseline:skills.home()
            return {'ok':True,'placed':name,'on':surface,'xy':[round(x,3),round(y,3)],'z':round(z,3)}
        if action=='home':
            skills.home(0. if holding else .08);return {'ok':True}
        status='finished' if args['success'] else 'model_failed'
        return {'ok':True,**args}
    try:
        state(action='观察场景');scene=observe()
        if baseline:
            # Fixed script: build each goal tower bottom-up from the first observation, never re-check.
            todo=[]
            for t in goal['towers']:
                for level in range(1,len(t)):todo+=[('pick',{'object':t[level]+'_cube'}),('stack_on',{'object':t[level-1]+'_cube','level_hint':level-1})]
            plan_version=1
            emit({'type':'plan','version':1,'steps':[f"{a} {v['object']}" for a,v in todo],'reason':'基线：按目标顺序直接 pick + stack_on，不检查当前状态','goal_summary':goal_text(goal)})
            for steps,(action,args) in enumerate(todo,1):
                if stop():status='stopped';break
                began=time.monotonic();emit({'type':'step_start','index':steps,'tool':action,'args':{k:v for k,v in args.items() if k!='level_hint'},'expected_s':EXPECTED_S[action]})
                state(action=action+' '+json.dumps(args))
                try:last=execute(action,args,scene)
                except Stopped:raise
                except (ValueError,RuntimeError,TimeoutError) as exc:last={'ok':False,'error':str(exc)}
                emit({'type':'step_result','ok':last['ok'],'detail':last});record({'step':steps,'tool':action,'arguments':args,'result':last,'seconds':time.monotonic()-began})
            else:status='finished'
            return
        system=Path(__file__).with_name('prompts').joinpath('goal_system.txt').read_text()
        messages=[{'role':'system','content':system},{'role':'user','content':'目标结构（板子从目标图片识别）：\n'+goal_text(goal)}]
        nudges=0
        for steps in range(1,21):
            if stop():status='stopped';break
            if steps>1:state(action='观察场景');scene=observe()
            messages.append({'role':'user','content':json.dumps({'round':steps,'current':describe(scene,holding),'goal_check':check(goal,scene,holding),'previous_result':last},ensure_ascii=False)})
            action=None
            for _ in range(3):
                state(action='调用 DeepSeek');began=time.monotonic()
                response,body,retries=model.call(messages,tools=TOOLS,tool_choice='auto',thinking=True)
                calls_n+=1;message=response['choices'][0]['message'];usage=response.get('usage',{});tokens+=usage.get('total_tokens',0)
                messages.append({k:v for k,v in message.items() if k in ('role','content','reasoning_content','tool_calls')})
                calls=message.get('tool_calls') or []
                row={'step':steps,'scene':describe(scene,holding),'response':message,'usage':usage,'api_seconds':time.monotonic()-began,'retries':retries,'messages_n':len(body['messages'])}
                if not calls:
                    nudges+=1;messages.append({'role':'user','content':'请调用工具：需要的话先 update_plan，然后调用一个动作工具。'});continue
                results={};chosen=[]
                for call in calls:
                    try:name,args=validate(call)
                    except ValueError as exc:results[call['id']]={'ok':False,'error':str(exc)};continue
                    if name=='update_plan':
                        plan_version+=1;emit({'type':'plan','version':plan_version,'steps':args['steps'],'reason':args['reason'],'goal_summary':args['goal_summary']})
                        results[call['id']]={'ok':True,'plan_version':plan_version}
                    else:chosen.append((call,name,args))
                if plan_version==0 and chosen:
                    for call,_,_ in chosen:results[call['id']]={'ok':False,'error':'第一轮必须先调用 update_plan'}
                    chosen=[]
                elif len(chosen)>1:
                    for call,_,_ in chosen:results[call['id']]={'ok':False,'error':'每轮只能调用一个动作工具'}
                    chosen=[]
                if chosen:
                    call,action,args=chosen[0];began=time.monotonic()
                    index=args.get('plan_step',actions+1)
                    emit({'type':'step_start','index':index,'tool':action,'args':{k:v for k,v in args.items() if k!='plan_step'},'expected_s':EXPECTED_S[action]})
                    state(action=action+' '+json.dumps(args,ensure_ascii=False))
                    try:last=execute(action,args,scene);actions+=1
                    except Stopped:raise
                    except (ValueError,RuntimeError,TimeoutError) as exc:last={'ok':False,'error':str(exc)}
                    results[call['id']]=last
                    emit({'type':'step_result','ok':last['ok'],'index':index,'tool':action,'detail':last})
                    row.update(tool=action,arguments=args,result=last,seconds=time.monotonic()-began)
                for call in calls:messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(results.get(call['id'],{'ok':False,'error':'not executed'}),ensure_ascii=False)})
                record(row)
                if chosen:break
            if status in ('finished','model_failed'):break
    except Stopped:status='stopped';last={'ok':False,'error':'stopped by operator'}
    except Exception as exc:status='api_error' if 'api_error' in str(exc) else 'error';last={'ok':False,'error':str(exc)}
    finally:
        skills.stop_check=None
        try:skills.home(0. if holding else .08)
        except Exception as exc:last={**(last or {}),'home_error':str(exc)}
        atomic(root/'status.json',{'status':status,'kind':request.get('kind'),'step':steps,'actions':actions,'plan_version':plan_version,'replans':max(0,plan_version-1),'calls':calls_n,
                                   'seconds':time.monotonic()-started,'started_utc':started_utc,'finished_utc':time.time(),'tokens':tokens,'result':last,'holding':None})
