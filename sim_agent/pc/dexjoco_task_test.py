"""Scripted run of a task's fixed plan through dex_tasks (no LLM), in-process. usage: dexjoco_task_test.py LIB.json task seeds...
Prints each step's result and DexJoCo's own success check; writes the wide-view video to .venv/dexjoco/."""
import json,sys,time,os
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'board'/'dexjoco'))
from dexjoco_server import DexSim
import dex_tasks as T

class LocalLink:
    def __init__(self,sim):self.sim=sim
    def call(self,op,**kw):
        r=json.loads(json.dumps(self.sim.service({'op':op,**kw})))
        if 'error' in r:raise RuntimeError(r['error'])
        return r

def run(lib,task,seed,video=None,verbose=True):
    sim=DexSim(realtime=False);link=LocalLink(sim);link.call('reset',task=task,seed=seed,password=T.password_for(seed) if task=='bimanual_unlock_ipad' else None)
    ep=T.Episode(link,lib,task);spec=T.TASKS[task];log=[]
    plan=spec['scripted'] or [('pick',{'object':'ipad'})]+[('press',{'digit':str(d)}) for d in T.password_for(seed)]
    for name,args in plan:
        try:r=spec['run'][name](ep,args)
        except (ValueError,RuntimeError) as e:r={'ok':False,'error':str(e)}
        log.append((name,args,r))
        if verbose:print('  ',name,args,json.dumps(r,ensure_ascii=False,default=str)[:160],flush=True)
    ep.arms.send([{}]*45)
    tr=link.call('truth')
    if video:sim.save_video(video)
    sim.close()
    return tr['success'],log

if __name__=='__main__':
    lib=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));task=sys.argv[2];ok=0
    for s in sys.argv[3:]:
        t=time.time();r,_=run(lib,task,int(s),video=f'C:/Users/jielu/Desktop/RV/.venv/dexjoco/test-{task}-{s}.mp4')
        ok+=r;print('seed',s,'SUCCESS' if r else 'fail','%.0fs'%(time.time()-t),flush=True)
    print('TOTAL',ok,'/',len(sys.argv)-3)
