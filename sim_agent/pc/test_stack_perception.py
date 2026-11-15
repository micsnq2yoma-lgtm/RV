import sys,unittest,json
from pathlib import Path
import mujoco,numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'board'/'agent'))
from stack_perception import StackPerception
from sim_server import Simulator
from layouts import COLORS,truth_structure

class StacksTest(unittest.TestCase):
    def test_twenty_random_layouts(self):
        sim=Simulator('127.0.0.2');snapshot=mujoco.MjData(sim.model);results=[]
        with mujoco.Renderer(sim.model,height=480,width=640) as r:
            for seed in range(20):
                colors=list(COLORS);np.random.default_rng(seed).shuffle(colors)
                lengths=[(1,1,1,1),(2,1,1),(3,1),(2,2),(4,)][seed%5];stacks=[];offset=0
                for size in lengths:stacks.append(colors[offset:offset+size]);offset+=size
                sim.reset(15000+seed,{'towers':stacks})
                for _ in range(300):mujoco.mj_step(sim.model,sim.data)
                images=sim.service({'op':'render_multi','cameras':['top','front','side'],'w':640,'h':480},r,snapshot)['images']
                scene=StackPerception().observe(images)
                truth=truth_structure(sim.service({'op':'objects'},r,snapshot))
                expected=sorted(map(tuple,truth['towers']));actual=sorted(map(tuple,scene['towers']))
                results.append({'seed':seed,'expected':expected,'actual':actual})
                with self.subTest(seed=seed):
                    self.assertEqual(actual,expected)
                    self.assertEqual(set(scene['loose']),set(truth['loose']))
                    self.assertEqual(expected,sorted(tuple(t) for t in stacks if len(t)>1))
        print(json.dumps({'stack_layout_results':results}),flush=True)

if __name__=='__main__':unittest.main()
