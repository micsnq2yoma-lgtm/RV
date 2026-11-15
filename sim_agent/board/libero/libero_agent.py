"""DeepSeek agent for LIBERO tasks (protocol libero-1). Runs on the agent host: the PC for local tests, the RV board later.

The model sees text only: the instruction and, every round, the objects localised by libero_perception (name,
centre, top height, size) plus what the gripper holds. It acts through pick / place_on; finish ends the episode.
Success is judged afterwards by LIBERO's own BDDL predicate (truth), which the model never sees.
"""
import json,math,os,sys,time,urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'agent'));sys.path.insert(0,str(HERE.parent/'nav'))
from agent import tool,Model
import libero_perception as P
from libero_skills import Robot

def tools(names):
    return [tool('update_plan','记录或修改计划。第一轮必须先调用；计划变化时再调用。不算动作，同一轮可以再调用一个动作。',
                 {'goal_summary':{'type':'string'},'steps':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':8},'reason':{'type':'string'}},['goal_summary','steps','reason']),
            tool('pick','从上方抓起一个物体（手里必须是空的）。宽于 7 cm 的物体会抓边沿。',{'object':{'type':'string','enum':names},'plan_step':{'type':'integer','minimum':1,'maximum':8}},['object','plan_step']),
            tool('place_on','把手里的物体放到目标物体上（物体中心对准目标中心）。',{'target':{'type':'string','enum':names},'plan_step':{'type':'integer','minimum':1,'maximum':8}},['target','plan_step']),
            tool('finish','结束任务。',{'success':{'type':'boolean'},'summary':{'type':'string'}},['success','summary'])]

SYSTEM='''你控制仿真厨房里的一台 Franka Panda 机械臂，用 LIBERO 基准的任务来测试你。任务是一句英文指令。
你看不到图像。每一轮你会收到场景里各物体的名称和位置（单位 m，x 朝前远离机器人基座，y 朝左，z 朝上），由视觉模块从深度图算出，误差约 1 cm；以及手里拿着什么。
指令里的物体描述（比如 “the black bowl between the plate and the ramekin”）要根据坐标判断对应哪一个物体名。
工具：update_plan（第一轮必须先调用）、pick(object)、place_on(target)、finish(success, summary)。每轮最多一个动作；动作后会重新观察。
放好以后看新的位置确认物体确实到了目标上（xy 接近、高度高于目标顶面），再 finish。用简体中文思考和回答，简洁。'''

def describe(sc,holding):
    objs={n:{'center':v['center'],'top_z':v['top_z'],'size_xy':v['size_xy']} for n,v in sc.items()}
    return {'objects':objs,'holding':holding}

def run(link,model,emit,task,max_rounds=10):
    hello=link.call('reset',suite=task['suite'],task=task['task'],init=task.get('init',0))
    emit({'type':'task_start','kind':'libero','text':hello['instruction'],'scenario':'%s/%d'%(task['suite'],task['task']),'seed':task.get('init',0)})
    model.emit=emit;robot=Robot(link);holding=None;last=None;plan_v=0;calls=0;tokens=0;status='limit';t0=time.monotonic()
    obs=link.call('observe');robot.sync(obs);sc=P.scene(obs);names=sorted(sc)
    T=tools(names)
    messages=[{'role':'system','content':SYSTEM},{'role':'user','content':'指令：'+hello['instruction']}]
    for rnd in range(1,max_rounds+1):
        emit({'type':'observe','summary':'；'.join('%s (%.2f,%.2f,%.2f)'%(n,*v['center']) for n,v in sc.items()),'scene':describe(sc,holding)})
        messages.append({'role':'user','content':'第%d轮观察（请用中文思考）：'%rnd+json.dumps({**describe(sc,holding),'previous_result':last},ensure_ascii=False)})
        acted=False
        for _ in range(3):
            resp,body,_=model.call(messages,tools=T,tool_choice='auto',thinking=True);calls+=1
            msg=resp['choices'][0]['message'];tokens+=resp.get('usage',{}).get('total_tokens',0)
            messages.append({k:v for k,v in msg.items() if k in ('role','content','reasoning_content','tool_calls')})
            tcs=msg.get('tool_calls') or []
            if not tcs:messages.append({'role':'user','content':'请调用工具。'});continue
            results={}
            for c in tcs:
                fn=c['function'];name=fn['name']
                try:args=json.loads(fn.get('arguments') or '{}')
                except ValueError:results[c['id']]={'ok':False,'error':'bad JSON'};continue
                if name=='update_plan':
                    plan_v+=1;emit({'type':'plan','version':plan_v,'steps':args.get('steps',[]),'reason':args.get('reason','')});results[c['id']]={'ok':True};continue
                if acted:results[c['id']]={'ok':False,'error':'每轮只能一个动作'};continue
                if plan_v==0:results[c['id']]={'ok':False,'error':'先调用 update_plan'};continue
                acted=True;emit({'type':'step_start','index':args.get('plan_step',1),'tool':name,'args':{k:v for k,v in args.items() if k!='plan_step'},'expected_s':8})
                try:
                    if name=='pick':
                        if holding:raise ValueError('手里已经有 '+holding)
                        if args['object'] not in sc:raise ValueError('看不到 '+args['object'])
                        last=robot.pick(sc[args['object']]);holding=args['object'] if last['ok'] else None
                    elif name=='place_on':
                        if not holding:raise ValueError('手里是空的')
                        if args['target'] not in sc:raise ValueError('看不到 '+args['target'])
                        last=robot.place_on(sc[args['target']]);holding=None
                    elif name=='finish':
                        last={'ok':True,**args};status='finished' if args.get('success') else 'model_failed'
                    else:raise ValueError('unknown tool '+name)
                except (ValueError,KeyError,RuntimeError) as exc:last={'ok':False,'error':str(exc)}
                results[c['id']]=last;emit({'type':'step_result','ok':last.get('ok',False),'index':args.get('plan_step',1),'tool':name,'detail':last})
            for c in tcs:messages.append({'role':'tool','tool_call_id':c['id'],'content':json.dumps(results.get(c['id'],{'ok':False}),ensure_ascii=False)})
            if acted:break
        if status in ('finished','model_failed'):break
        obs=link.call('observe');robot.sync(obs);sc=P.scene(obs)
    truth=link.call('truth')
    result={'status':status,'truth':truth['success'],'rounds':rnd,'calls':calls,'tokens':tokens,'replans':max(0,plan_v-1),'seconds':round(time.monotonic()-t0,1),'sim_steps':truth['steps'],'task':truth['task']}
    emit({'type':'finish','success_truth':truth['success'],'stats':result});return result

def local_model():
    """Local tests: key from the process environment only (never a file in the repo)."""
    m=Model.__new__(Model);m.key=os.environ['DEEPSEEK_API_KEY'];m.http=urllib.request.build_opener();return m
