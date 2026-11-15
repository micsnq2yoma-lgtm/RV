"""DeepSeek agent for the DexJoCo bimanual tasks (protocol dexjoco-1). Runs on the agent host: PC for local tests, RV board.

The model sees text only: the instruction and, every round, the task state computed from perception (object
positions, what is stacked where, what each hand holds, door / screen state). It acts through the task's tools
(skills cut from human demos plus visual-servo placement, see dex_skills / dex_tasks); finish ends the episode.
Success is judged afterwards by DexJoCo's own check (truth), which the model never sees.
"""
import json,os,sys,time,urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'agent'))
from agent import tool,Model
import dex_tasks as T

SYSTEM='''你控制仿真里的一台双臂机器人：两台 Franka 机械臂，各装一只 16 自由度的 Allegro 灵巧手，面对一张桌子。
你看不到图像。每一轮你会收到视觉模块从深度图算出的场景状态（单位 m，x 朝前远离机器人，y 朝左，z 朝上）和每只手拿着什么。
你只能通过工具行动。工具是从人类遥操作演示中提取的技能（抓取、开门、按键等，按物体的实测位置迁移到当前场景）和视觉伺服放置。
规则：第一轮必须先调用 update_plan；每轮最多调用一个动作工具；动作后会重新观察。
动作失败时，先根据新的观察判断原因（物体掉落、没抓起、位置偏），可以重试或换个顺序；不要重复完全相同的失败超过两次。
确认任务完成（依据观察）后调用 finish。用简体中文思考和回答，简洁。'''

TASK_HINTS={
 'bimanual_hanoi':'汉诺塔规则：一次只移动一个盘；大盘不能压在小盘上。目标是三个盘都在 peg_C 上，从下到上 大、中、小。只有 disk_small、disk_medium 可以移动（disk_large 已在 peg_C）。',
 'bimanual_microwave_cook':'微波炉门要先打开才能放热狗；放进去后关门并按启动键。close_door_and_start 会同时关门和按启动键。',
 'bimanual_assembly':'需要一只手拿住插座（socket），另一只手拿住圆柱销（peg），再把销插进插座的孔里。',
 'bimanual_photograph':'先拿起相机，再对准墙上的标志拍照。',
 'bimanual_unlock_ipad':'先用左手把 iPad 从支架上拿起来，再用右手依次按密码的每一位数字。按错一位就会失败，务必按指令中的顺序。',
}

def tools_for(task):
    out=[tool('update_plan','记录或修改计划。第一轮必须先调用；计划变化时再调用。不算动作。',
              {'steps':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':10},'reason':{'type':'string'}},['steps','reason'])]
    for name,params,desc in T.TASKS[task]['tools']:
        props={k:{'type':'string','enum':v} if isinstance(v,list) else v for k,v in params.items()}
        out.append(tool(name,desc,{**props,'plan_step':{'type':'integer','minimum':1,'maximum':10}},list(params)+['plan_step']))
    out.append(tool('finish','结束任务。',{'success':{'type':'boolean'},'summary':{'type':'string'}},['success','summary']))
    return out

def run(link,model,emit,lib,task,seed=0,max_rounds=12,stop=lambda:False,overlay=True):
    pw=T.password_for(seed) if task=='bimanual_unlock_ipad' else None
    hello=link.call('reset',task=task,seed=seed,password=pw)
    emit({'type':'task_start','kind':'dexjoco','text':hello['instruction'],'scenario':task,'seed':seed})
    model.emit=emit;ep=T.Episode(link,lib,task,stop);spec=T.TASKS[task];TL=tools_for(task)
    plan_v=0;calls=0;tokens=0;status='limit';last=None;t0=time.monotonic();rnd=0
    def show(note=''):
        if overlay:
            try:link.call('overlay',tokens=tokens,note=note,speed='1x, DeepSeek agent')
            except Exception:pass
    messages=[{'role':'system','content':SYSTEM},{'role':'user','content':'指令：'+hello['instruction']+'\n提示：'+TASK_HINTS[task]}]
    for rnd in range(1,max_rounds+1):
        if stop():status='stopped';break
        state=spec['state'](ep);emit({'type':'observe','scene':state})
        messages.append({'role':'user','content':'第%d轮观察（请用中文思考）：'%rnd+json.dumps({'state':state,'previous_result':last},ensure_ascii=False)})
        acted=False
        for _ in range(3):
            resp,_,_=model.call(messages,tools=TL,tool_choice='auto',thinking=True);calls+=1
            msg=resp['choices'][0]['message'];tokens+=resp.get('usage',{}).get('total_tokens',0);show()
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
                acted=True;a2={k:v for k,v in args.items() if k!='plan_step'}
                emit({'type':'step_start','index':args.get('plan_step',1),'tool':name,'args':a2});show(name+' '+' '.join(str(v) for v in a2.values()))
                try:
                    if name=='finish':last={'ok':True,**args};status='finished' if args.get('success') else 'model_failed'
                    elif name in spec['run']:last=spec['run'][name](ep,a2)
                    else:raise ValueError('unknown tool '+name)
                except (ValueError,KeyError,RuntimeError) as exc:last={'ok':False,'error':str(exc)}
                last=json.loads(json.dumps(last,default=lambda o:o.tolist() if hasattr(o,'tolist') else str(o)))
                results[c['id']]=last;emit({'type':'step_result','ok':last.get('ok',False),'index':args.get('plan_step',1),'tool':name,'detail':last})
            for c in tcs:messages.append({'role':'tool','tool_call_id':c['id'],'content':json.dumps(results.get(c['id'],{'ok':False}),ensure_ascii=False)})
            if acted:break
        if status in ('finished','model_failed'):break
    ep.arms.send([{}]*45)
    truth=link.call('truth')
    result={'status':status,'truth':truth['success'],'rounds':rnd,'calls':calls,'tokens':tokens,'replans':max(0,plan_v-1),
            'seconds':round(time.monotonic()-t0,1),'sim_steps':truth['steps'],'task':task,'seed':seed}
    show('done: '+('success' if truth['success'] else 'failed'))
    emit({'type':'finish','success_truth':truth['success'],'stats':result});return result

def local_model():
    """Local tests: key from the process environment only (never a file in the repo)."""
    m=Model.__new__(Model);m.key=os.environ['DEEPSEEK_API_KEY'];m.http=urllib.request.build_opener();return m
