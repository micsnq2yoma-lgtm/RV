"""Offline check of the goal-stacking loop: real MuJoCo renders and board perception, scripted model."""
import json,sys,tempfile,unittest
from pathlib import Path
import mujoco,numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'board'/'agent'))
import stacking
from goal_store import evaluate_goal
from layouts import truth_structure
from sim_server import Simulator

class World:
    """Teleporting stand-in for the robot: pick/place move cube bodies directly."""
    def __init__(self,layout,seed=7):
        self.sim=Simulator('127.0.0.2');self.sim.reset(seed,layout);self.snapshot=mujoco.MjData(self.sim.model)
        self.renderer=mujoco.Renderer(self.sim.model,height=480,width=640);self.holding=None;self.table_z=0.;self.stop_check=None
    def adr(self,name):
        m=self.sim.model;return m.jnt_qposadr[m.body_jntadr[m.body(name).id]]
    def call(self,op,**args):return self.sim.service({'op':op,**args},self.renderer,self.snapshot)
    def pick(self,x,y,z=None):
        best=min(stacking.CUBES,key=lambda c:np.linalg.norm(self.sim.data.body(c).xpos-[x,y,z]))
        if np.linalg.norm(self.sim.data.body(best).xpos-[x,y,z])>.02:return False
        self.holding=best;a=self.adr(best);self.sim.data.qpos[a:a+3]=[.3,0,.6];mujoco.mj_forward(self.sim.model,self.sim.data);return True
    def place(self,x,y,z):
        a=self.adr(self.holding);self.sim.data.qpos[a:a+7]=[x,y,z-.001,1,0,0,0];self.holding=None
        for _ in range(200):mujoco.mj_step(self.sim.model,self.sim.data)
    def home(self,grip=.08):pass

class RT:
    def call(self):return {'gripper':.04}

class Script:
    """Returns pre-written tool calls; records what the model would have seen."""
    def __init__(self,turns):self.turns=list(turns);self.seen=[]
    def call(self,messages,tools=None,tool_choice='required',thinking=False):
        self.seen.append(messages[-1]);calls=[]
        for i,(name,args) in enumerate(self.turns.pop(0)):
            calls.append({'id':f'c{len(self.seen)}-{i}','type':'function','function':{'name':name,'arguments':json.dumps(args)}})
        return {'choices':[{'message':{'role':'assistant','content':'','tool_calls':calls}}],'usage':{'total_tokens':10}},{'messages':list(messages)},0

PLAN=('update_plan',{'goal_summary':'红·绿·蓝','steps':['pick red','place_on_table','pick green','stack_on red','pick blue','stack_on green'],'reason':'红压着蓝，先拿开'})
class StackingLoopTest(unittest.TestCase):
    def run_goal(self,layout,goal,turns,kind='goal_stack'):
        world=World(layout);model=Script(turns);events=[]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            stacking.run_goal(root,{'kind':kind,'goal':goal},world,RT(),world,model,events.append)
            status=json.loads((root/'status.json').read_text())
        truth=evaluate_goal(goal,world.call('objects'))
        return status,events,model,truth,world

    def test_g3_sussman_variant_succeeds_with_rules_enforced(self):
        goal={'towers':[['red','green','blue']]}
        turns=[[PLAN,('pick',{'object':'blue_cube','plan_step':1})],   # blue is under red: must be rejected
               [('pick',{'object':'red_cube','plan_step':1})],
               [('place_on_table',{'plan_step':2})],
               [('pick',{'object':'green_cube','plan_step':3})],[('stack_on',{'object':'red_cube','plan_step':4})],
               [('pick',{'object':'blue_cube','plan_step':5})],[('stack_on',{'object':'green_cube','plan_step':6})],
               [('finish',{'success':True,'summary':'done'})]]
        status,events,model,truth,world=self.run_goal({'towers':[['blue','red']]},goal,turns)
        self.assertEqual(status['status'],'finished');self.assertTrue(truth)
        results=[e for e in events if e['type']=='step_result']
        self.assertFalse(results[0]['ok']);self.assertIn('只能操作塔顶',results[0]['detail']['error'])
        self.assertTrue(all(r['ok'] for r in results[1:]))
        final=json.loads(model.seen[-1]['content'])
        self.assertTrue(final['goal_check']['matched']);self.assertEqual(final['current']['towers'],[['red_cube','green_cube','blue_cube']])
        self.assertEqual([e['version'] for e in events if e['type']=='plan'],[1])
        self.assertTrue(any(e['type']=='observe' and e['detections'] for e in events))

    def test_action_before_first_plan_is_rejected(self):
        turns=[[('pick',{'object':'red_cube','plan_step':1})],[('finish',{'success':False,'summary':'stop'})]]
        status,events,model,truth,world=self.run_goal({'towers':[]},{'towers':[['blue','red']]},turns)
        rejected=model.seen[1]
        self.assertEqual(rejected['role'],'tool');self.assertIn('update_plan',json.loads(rejected['content'])['error'])
        self.assertFalse(any(e['type']=='step_start' for e in events))

    def test_baseline_does_not_unstack(self):
        goal={'towers':[['red','green','blue']]}
        status,events,model,truth,world=self.run_goal({'towers':[['blue','red']]},goal,[],kind='baseline')
        self.assertEqual(status['status'],'finished');self.assertFalse(truth);self.assertEqual(model.seen,[])

    def test_table_spot_avoids_cubes_and_trays(self):
        scene={'objects':[{'name':'a','xy':[.62,0.],'in':'table'},{'name':'b','xy':[.6,.1],'in':'table'}]}
        trays={'left_tray':[.5,.3],'right_tray':[.5,-.3]}
        x,y=stacking.table_spot(scene,trays)
        self.assertGreaterEqual(min(np.hypot(x-.62,y),np.hypot(x-.6,y-.1)),.085)
        self.assertFalse(abs(x-.5)<.15 and abs(abs(y)-.3)<.12)

if __name__=='__main__':unittest.main()
