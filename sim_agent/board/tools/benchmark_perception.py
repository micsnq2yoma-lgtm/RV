"""Isolated evaluator: truth is never sent to the model or perception algorithm."""
import sys,json,time,os
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from local_rpc import LocalSim
from perception import Perception
os.sched_setaffinity(0,{0});sim=LocalSim('/tmp/rv014/evaluation.sock');rows=[]
for seed in range(1400,1420):
    sim.call('reset',seed=seed);time.sleep(.7)
    image=sim.call('render',camera='top',w=640,h=480);start=time.perf_counter();scene=Perception().observe(image);elapsed=time.perf_counter()-start
    truth={o['name']:o['pos'] for o in sim.call('objects')['objects']}
    for obj in scene['objects']:
        row={'seed':seed,'name':obj['name'],'occluded':obj['occluded'],'perception_seconds':elapsed,'error_m':float(np.linalg.norm(np.array(obj['xy'])-truth[obj['name']][:2])) if obj['xy'] else None}
        rows.append(row);print(json.dumps(row),flush=True)
assert all(not r['occluded'] for r in rows)
print(json.dumps({'mean_m':float(np.mean([r['error_m'] for r in rows])),'max_m':max(r['error_m'] for r in rows),'observations':len(rows),'mean_scene_seconds':float(np.mean([r['perception_seconds'] for r in rows]))}),flush=True)
