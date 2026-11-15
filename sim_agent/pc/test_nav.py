"""Offline check of the navigation agent loop: real MuJoCo physics + board perception/planning, scripted model."""
import json,sys,tempfile,threading,unittest
from pathlib import Path
import mujoco
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'board'/'nav'))
import navigator as N
import nav_agent
from nav_perception import NavPerception
from nav_server import NavSim

class World:
    def __init__(self,scenario,seed):
        self.sim=NavSim('127.0.0.2');self.sim.reset(seed,scenario);threading.Thread(target=self.sim.physics,daemon=True).start()
        self.r={(640,480):mujoco.Renderer(self.sim.model,480,640),(320,240):mujoco.Renderer(self.sim.model,240,320)};self.d=mujoco.MjData(self.sim.model);self.lock=threading.Lock()
    def call(self,op,**a):
        with self.lock:return self.sim.service({'op':op,**a},self.r,self.d)

class Script:
    """Replies with scripted tool calls; a turn may be a function of the last message (to react to results)."""
    def __init__(self,turns):self.turns=list(turns);self.seen=[]
    def call(self,messages,tools=None,tool_choice='required',thinking=False):
        self.seen.append(messages[-1]);turn=self.turns.pop(0)
        if callable(turn):turn=turn(messages[-1])
        calls=[{'id':f'c{len(self.seen)}-{i}','type':'function','function':{'name':n,'arguments':json.dumps(a)}} for i,(n,a) in enumerate(turn)]
        return {'choices':[{'message':{'role':'assistant','content':'','tool_calls':calls}}],'usage':{'total_tokens':10}},{'messages':list(messages)},0

def body(msg):
    """Round messages are a short Chinese preface followed by JSON."""
    c=msg['content'];return json.loads(c[c.index('{'):])

PLAN=lambda steps:('update_plan',{'goal_summary':'g','steps':steps,'reason':'r'})
class NavLoopTest(unittest.TestCase):
    def run_task(self,scenario,seed,turns,task='t'):
        w=World(scenario,seed);model=Script(turns);events=[]
        driver=N.Driver(w,NavPerception(),w.call('hello'))
        with tempfile.TemporaryDirectory() as tmp:
            nav_agent.run(Path(tmp),{'task':task},w,driver,model,events.append)
            status=json.loads((Path(tmp)/'status.json').read_text(encoding='utf-8'))
        truth=w.call('truth');w.sim.stop.set();return status,events,model,truth

    def test_n3_avoid_zone(self):
        turns=[[PLAN(['去红色区域，避开黄色']),('navigate_to',{'target':'red','avoid':['yellow'],'plan_step':1})],[('finish',{'success':True,'summary':'ok'})]]
        status,events,model,truth=self.run_task('N3',3,turns)
        self.assertEqual(status['status'],'finished')
        self.assertNotIn('yellow',[v['zone'] for v in truth['visits']]);self.assertEqual(truth['visits'][-1]['zone'],'red')
        self.assertEqual(body(model.seen[-1])['in_zone'],'red')
        self.assertTrue(any(e['type']=='nav_plan' for e in events))

    def test_n4_blocked_then_replan(self):
        def second(msg):
            prev=body(msg)['previous_result']
            self.assertFalse(prev['ok']);self.assertIn('blocked',prev['error'])
            return [PLAN(['重新规划去红色区域']),('navigate_to',{'target':'red','avoid':[],'plan_step':1})]
        turns=[[PLAN(['去红色区域']),('navigate_to',{'target':'red','avoid':[],'plan_step':1})],second,[('finish',{'success':True,'summary':'ok'})]]
        status,events,model,truth=self.run_task('N4',4,turns)
        self.assertEqual(status['status'],'finished');self.assertEqual(status['replans'],1)
        self.assertIsNotNone(truth['event']);self.assertEqual(truth['visits'][-1]['zone'],'red')

    def test_rejects_action_before_plan_and_bad_zone(self):
        turns=[[('navigate_to',{'target':'red','avoid':[],'plan_step':1})],[('navigate_to',{'target':'purple','avoid':[],'plan_step':1})],[('finish',{'success':False,'summary':'x'})]]
        status,events,model,truth=self.run_task('N1',1,turns)
        self.assertIn('update_plan',json.loads(model.seen[1]['content'])['error'])
        self.assertIn('unknown',json.loads(model.seen[2]['content'])['error'])

if __name__=='__main__':unittest.main()
