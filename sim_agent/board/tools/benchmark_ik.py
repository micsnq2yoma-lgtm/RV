"""Deterministic 30 reachable tabletop targets; profile and accuracy, no robot motion."""
import argparse,cProfile,importlib,json,pstats,sys,time
from pathlib import Path
import numpy as np
import os
os.sched_setaffinity(0,{0})
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
p=argparse.ArgumentParser();p.add_argument('--module',default='kin');p.add_argument('--profile',action='store_true');p.add_argument('--warm',action='store_true');a=p.parse_args()
m=importlib.import_module(a.module);k=m.Kinematics(json.loads(Path('/tmp/rv014/kinematics.json').read_text()))
targets=[[float(x),float(y),float(z)] for z in [.023,.123] for x in [.50,.60,.70] for y in [-.30,-.15,0,.15,.30]]
prof=cProfile.Profile();samples=[];q=m.HOME
if a.profile:prof.enable()
for pos in targets:
 start=time.perf_counter();q=k.ik(pos,m.down(),q if a.warm else m.HOME);elapsed=time.perf_counter()-start
 pp,rr=k.fk(q);pe=float(np.linalg.norm(pp-pos));re=float(np.linalg.norm(m.rotation_error(m.down(),rr))*180/np.pi)
 assert pe<.001 and re<1,(pos,pe,re)
 samples.append({'target':pos,'ms':elapsed*1000,'position_m':pe,'rotation_deg':re,'iterations':k.last_iterations})
 print(json.dumps(samples[-1]),flush=True)
if a.profile:prof.disable();pstats.Stats(prof).sort_stats('cumulative').print_stats(10)
print(json.dumps({'module':a.module,'warm':a.warm,'profile':a.profile,'mean_ms':float(np.mean([x['ms'] for x in samples])),'max_ms':max(x['ms'] for x in samples),'samples':samples}),flush=True)
