"""Render the eight protocol v1.3 targets without advancing a live simulation."""
import base64,json
from pathlib import Path
import mujoco,numpy as np
from sim_server import Simulator
from layouts import render_goal

PRESETS=[('blue-red-green',[['blue','red','green']]),('red-green-blue',[['red','green','blue']]),
 ('four-blue-red-green-orange',[['blue','red','green','orange']]),('four-orange-blue-red-green',[['orange','blue','red','green']]),
 ('two-red-orange-green-blue',[['red','orange'],['green','blue']]),('two-red-green-blue-orange',[['red','green'],['blue','orange']]),
 ('two-orange-red-blue-green',[['orange','red'],['blue','green']]),('green-orange-blue',[['green','orange','blue']])]

def generate(root=None):
    root=Path(root or Path(__file__).resolve().parents[1]/'goals');root.mkdir(parents=True,exist_ok=True)
    sim=Simulator('127.0.0.2');q=sim.data.qpos.copy();v=sim.data.qvel.copy()
    with mujoco.Renderer(sim.model,height=480,width=640) as renderer:
        for name,stacks in PRESETS:
            goal={'towers':stacks};result=render_goal(sim.model,renderer,goal)
            (root/(name+'.json')).write_text(json.dumps({'name':name,'goal':goal},indent=2)+'\n')
            (root/(name+'.jpg')).write_bytes(base64.b64decode(result['jpeg_b64']))
    assert np.array_equal(q,sim.data.qpos) and np.array_equal(v,sim.data.qvel)
    print('Rendered',len(PRESETS),'independent goal images; live q/v unchanged')

if __name__=='__main__':generate()
