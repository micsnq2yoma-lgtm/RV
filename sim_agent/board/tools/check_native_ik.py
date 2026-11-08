"""Validate native solve against independent numpy FK, including failure boundaries."""
import json,sys,os
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from kin import Kinematics,HOME,down,rotation_error
os.sched_setaffinity(0,{0});k=Kinematics(json.loads(Path('/tmp/rv014/kinematics.json').read_text()));assert k.native is not None
rng=np.random.default_rng(14);maximum=[0.,0.]
for i in range(30):
    q=rng.uniform(k.limits[:,0]+.1,k.limits[:,1]-.1);pos,rot=k.fk(q)
    result=k.ik(pos,rot,q+rng.uniform(-.05,.05,7));p,r=k.fk(result)
    pe=float(np.linalg.norm(p-pos));re=float(np.linalg.norm(rotation_error(rot,r)))
    assert pe<.001 and re<np.pi/180;maximum=[max(maximum[0],pe),max(maximum[1],re)]
try:k.ik([5,5,5],down(),HOME)
except RuntimeError:pass
else:raise AssertionError('unreachable target accepted')
for seed in [[0]*6,[float('nan')]*7]:
    try:k.ik([.6,0,.1],down(),seed)
    except ValueError:pass
    else:raise AssertionError('bad seed accepted')
print(json.dumps({'native_checks':30,'max_position_m':maximum[0],'max_rotation_deg':maximum[1]*180/np.pi,'unreachable_and_invalid_rejected':True}),flush=True)
