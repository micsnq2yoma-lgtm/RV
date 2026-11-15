"""One-tool-at-a-time model loop. Images/decisions stay in RAM, no truth in planning."""
import base64,json,os,stat,sys,time,urllib.request,urllib.error
from pathlib import Path
from perception import Perception,CUBES,TRAYS
from transport import RTClient
from skills import Skills
from local_rpc import LocalSim

def atomic(path,data):
    path=Path(path);tmp=path.with_suffix('.new');tmp.write_text(json.dumps(data,ensure_ascii=False));tmp.replace(path)

def tool(name,description,props,required):
    return {'type':'function','function':{'name':name,'description':description,'parameters':{'type':'object','properties':props,'required':required,'additionalProperties':False}}}
TOOLS=[tool('pick','抓住方块',{'object':{'type':'string','enum':list(CUBES)}},['object']),
       tool('place_in','放入托盘空位',{'tray':{'type':'string','enum':list(TRAYS)}},['tray']),
       tool('stack_on','叠在方块上',{'object':{'type':'string','enum':list(CUBES)}},['object']),
       tool('home','回到home',{},[]),tool('finish','结束并说明结果',{'success':{'type':'boolean'},'summary':{'type':'string'}},['success','summary'])]

class Model:
    def __init__(self):
        path=Path('/root/.config/rv-agent/deepseek.key')
        if stat.S_IMODE(path.stat().st_mode)!=0o600:raise RuntimeError('API key file must have mode 600')
        self.key=path.read_text().strip()
        if not self.key:raise RuntimeError('API key file empty')
        self.http=urllib.request.build_opener(urllib.request.ProxyHandler({'https':'http://127.0.0.1:7897'}))
    def call(self,messages,tools=None,tool_choice='required',thinking=False):
        body={'model':'deepseek-flash','messages':list(messages),'tools':tools or TOOLS,'tool_choice':tool_choice,'temperature':0,'max_tokens':600,'thinking':{'type':'disabled'},'stream':True,'stream_options':{'include_usage':True}}
        if thinking:
            # Report 015: thinking mode rejects tool_choice='required' with HTTP 400, so it only runs with 'auto'.
            body.update(thinking={'type':'enabled'},tool_choice='auto',max_tokens=4000)
            body.pop('temperature',None)
        self.last_body=body
        for attempt in range(3):
            try:
                req=urllib.request.Request('https://api.deepseek.com/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+self.key})
                message={'role':'assistant','content':''};calls={};usage={}
                with self.http.open(req,timeout=90 if thinking else 45) as response:
                    complete=False
                    for line in response:
                        if not line.startswith(b'data:'):continue
                        data=line[5:].strip()
                        if data==b'[DONE]':complete=True;break
                        chunk=json.loads(data)
                        if chunk.get('usage'):usage=chunk['usage']
                        for choice in chunk.get('choices',[]):
                            delta=choice.get('delta',{})
                            for field in ('content','reasoning_content'):
                                if delta.get(field):
                                    message[field]=message.get(field,'')+delta[field]
                                    if getattr(self,'emit',None):self.emit({'type':'think_delta','text':delta[field],'channel':field})
                            for part in delta.get('tool_calls',[]):
                                call=calls.setdefault(part['index'],{'id':'','type':'function','function':{'name':'','arguments':''}})
                                if part.get('id'):call['id']=part['id']
                                for field in ('name','arguments'):call['function'][field]+=part.get('function',{}).get(field,'')
                    if not complete:raise ValueError('incomplete model stream')
                message['tool_calls']=[calls[k] for k in sorted(calls)]
                result={'choices':[{'message':message}],'usage':usage}
                if getattr(self,'emit',None):self.emit({'type':'think_end','text':message.get('reasoning_content','')+message['content'],'tokens':usage})
                return result,body,attempt
            except (OSError,ValueError) as exc:
                if attempt==2:
                    detail=exc.read(300).decode('utf-8','replace') if isinstance(exc,urllib.error.HTTPError) else ''
                    raise RuntimeError('api_error: '+type(exc).__name__+(' '+detail if detail else '')) from None
                time.sleep(1+attempt)

def validate_call(call):
    fn=call.get('function',{});name=fn.get('name');args=json.loads(fn.get('arguments','{}'))
    schema=next((t['function']['parameters'] for t in TOOLS if t['function']['name']==name),None)
    if schema is None or not isinstance(args,dict) or set(args)!=set(schema['required']):raise ValueError('invalid tool name or arguments')
    for key,value in args.items():
        spec=schema['properties'][key]
        if 'enum' in spec and value not in spec['enum']:raise ValueError('unknown object')
        if spec['type']=='boolean' and type(value) is not bool:raise ValueError('success must be boolean')
        if spec['type']=='string' and (not isinstance(value,str) or len(value)>1000):raise ValueError('invalid text')
    return name,args

def tray_slot(x,occupied,reserved):
    """Use visual occupancy and prior commanded positions during occlusion."""
    slot=next((d for d in (-.055,0,.055) if all(abs(px-(x+d))>.035 for px in occupied+reserved)),None)
    if slot is None:raise ValueError('tray has no free slot')
    return x+slot

def run(directory,context=None,emit=None):
    os.sched_setaffinity(0,{0});root=Path(directory);request=json.loads((root/'request.json').read_text())
    if context is None:
        sim=LocalSim();rt=RTClient();skills=Skills(sim,rt);model=Model()
    else:sim,rt,skills,model=context
    emit=emit or (lambda event:None);model.emit=emit
    if request.get('kind') in ('goal_stack','baseline'):
        from stacking import run_goal
        try:return run_goal(root,request,sim,rt,skills,model,emit)
        finally:
            if context is None:rt.close()
    from skills import Stopped
    skills.stop_check=lambda:(root/'stop').exists()
    vision=Perception(skills.table_z);holding=None;placements={}
    messages=[{'role':'system','content':Path(__file__).with_name('prompts').joinpath('system.txt').read_text()}, {'role':'user','content':request['task']}]
    started=time.monotonic();started_utc=time.time();tokens=0;last=None;status='limit';steps=0
    def state(**fields):atomic(root/'status.json',dict(status='running',step=steps,holding=holding,seconds=time.monotonic()-started,started_utc=started_utc,tokens=tokens,**fields))
    def record(row):
        row['images']={}
        try:
            images=sim.call('render_multi',cameras=['top','front','side','wrist'],w=320,h=240)['images']
            for camera,data in images.items():
                name=f'{steps:02d}-{camera}.jpg';(root/name).write_bytes(base64.b64decode(data['jpeg_b64']));row['images'][camera]=name
        except Exception as exc:row['image_error']=type(exc).__name__
        with (root/'steps.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
    try:
        state(action='观察场景')
        for steps in range(1,13):
            if (root/'stop').exists():status='stopped';break
            image=sim.call('render',camera='top',w=640,h=480);scene=vision.observe(image,holding)
            emit({'type':'observe','scene':scene,'detections':[]})
            messages.append({'role':'user','content':json.dumps({'scene':scene,'previous_result':last},ensure_ascii=False)})
            state(action='调用 DeepSeek')
            began=time.monotonic()
            try:response,body,retries=model.call(messages)
            except RuntimeError as exc:
                record({'step':steps,'scene':scene,'request':model.last_body,'response':None,'result':{'ok':False,'error':str(exc)},'retries':2,'seconds':time.monotonic()-began,'usage':{}})
                raise
            message=response['choices'][0]['message'];calls=message.get('tool_calls',[]);usage=response.get('usage',{});tokens+=usage.get('total_tokens',0)
            row={'step':steps,'scene':scene,'request':body,'response':message,'usage':usage,'api_seconds':time.monotonic()-began,'retries':retries}
            messages.append({k:v for k,v in message.items() if k in ('role','content','reasoning_content','tool_calls')})
            last={'ok':False};action='invalid';args={}
            try:
                if len(calls)!=1:raise ValueError('exactly one tool call required')
                action,args=validate_call(calls[0]);state(action=action+' '+json.dumps(args,ensure_ascii=False))
                emit({'type':'step_start','index':steps,'tool':action,'args':args,'expected_s':8})
                if (root/'stop').exists():
                    status='stopped';row.update(tool=action,arguments=args,result={'ok':False,'error':'stopped before execution'},seconds=time.monotonic()-began);record(row);break
                objects={x['name']:x for x in scene['objects']}
                if action=='pick':
                    if holding:raise ValueError('already holding an object')
                    obj=objects[args['object']]
                    if obj['occluded'] or obj['xy'] is None:raise ValueError('target occluded; home and observe first')
                    if not skills.pick(*obj['xy'],z=obj['z_est']+.003):raise RuntimeError('grasp width did not confirm a cube')
                    holding=args['object'];placements.pop(holding,None);last={'ok':True,'holding':holding}
                elif action in ('place_in','stack_on'):
                    if not holding:raise ValueError('gripper is empty')
                    dest=args.get('tray',args.get('object'))
                    if dest==holding:raise ValueError('cannot stack on held object')
                    obj=objects[dest]
                    if obj['xy'] is None or obj['occluded']:raise ValueError('destination occluded')
                    x,y=obj['xy']
                    if action=='place_in':
                        occupied=[o for o in objects.values() if o['in']==dest and o['name']!=holding]
                        # Remember commanded slots across temporary visual occlusion.
                        reserved=[p[1] for name,p in placements.items() if p[0]==dest and name!=holding]
                        x=tray_slot(x,[o['xy'][0] for o in occupied],reserved);z=skills.table_z+.028;surface=dest
                    else:z=obj['z_est']+.04;surface='on:'+dest
                    skills.place(x,y,z);placements[holding]=(surface,x);vision.placed(holding,surface);holding=None;last={'ok':True,'placed_in':surface}
                elif action=='home':skills.home();holding=None;last={'ok':True}
                else:
                    last={'ok':True,**args};status='finished' if args['success'] else 'model_failed'
            except Stopped:status='stopped';last={'ok':False,'error':'stopped by operator'}
            except (ValueError,RuntimeError,TimeoutError) as exc:last={'ok':False,'error':str(exc)}
            row.update(tool=action,arguments=args,result=last,seconds=time.monotonic()-began)
            emit({'type':'step_result','ok':last.get('ok',False),'detail':last})
            record(row)
            for call in calls:messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(last,ensure_ascii=False)})
            if status in ('finished','model_failed','stopped'):break
    except Exception as exc:status='api_error' if 'api_error' in str(exc) else 'error';last={'ok':False,'error':str(exc)}
    finally:
        skills.stop_check=None
        try:skills.home(0. if holding else .08)
        except Exception as exc:last={**(last or {}),'home_error':str(exc)}
        if context is None:rt.close()
        atomic(root/'status.json',{'status':status,'step':steps,'seconds':time.monotonic()-started,'started_utc':started_utc,'finished_utc':time.time(),'tokens':tokens,'result':last,'holding':None})

if __name__=='__main__':run(sys.argv[1])
