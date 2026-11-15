"""Resident simulation agent, with a fixed JSON task channel and no shell input."""
import contextlib,json,os,sys,time
from pathlib import Path
os.sched_setaffinity(0,{0})
from agent import run,Model,atomic
from transport import RTClient
from local_rpc import LocalSim
from skills import Skills
import stacking  # preload goal-stacking perception so the first goal task does not pay import time

def main():
    sim=LocalSim();rt=RTClient();model=Model()
    while True:
        try:skills=Skills(sim,rt);break
        except (OSError,RuntimeError,TimeoutError):time.sleep(.5)
    context=(sim,rt,skills,model)
    print(json.dumps({'type':'worker_ready','ts':time.time(),'run':None}),flush=True)
    try:
        for line in sys.stdin:
            item=json.loads(line)
            if item is None:break
            name=item.get('run','')
            if not name or any(c not in '0123456789T-' for c in name):raise ValueError('invalid run id')
            root=Path('/tmp/runs')/name
            with (root/'agent.log').open('a') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
                def emit(event):print(json.dumps({'ts':time.time(),'run':name,**event},ensure_ascii=False),file=sys.__stdout__,flush=True)
                try:run(root,context,emit)
                except Exception as exc:atomic(root/'status.json',{'status':'error','error':type(exc).__name__})
            print(json.dumps({'type':'worker_done','ts':time.time(),'run':name}),flush=True)
    finally:rt.close()

if __name__=='__main__':main()
