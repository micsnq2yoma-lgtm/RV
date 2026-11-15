"""Run LIBERO agent episodes on the RV board. usage: run_board.py OUT_DIR suite:task[:init] ...

The PC runs libero_server.py --agent-ip 192.168.50.2 and connects in on TCP 15004. The DeepSeek key is read from the
board's key file by agent.Model (mode 600, never printed); API traffic uses the SSH reverse-tunnel proxy.
"""
import json,os,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'nav'))
if hasattr(os,'sched_setaffinity'):os.sched_setaffinity(0,{0})
from link import NavLink
import libero_agent as A
from agent import Model
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
link=NavLink(port=15004,timeout=900);print('simulator connected',flush=True)
model=Model()
for spec in sys.argv[2:]:
    suite,task,*rest=spec.split(':');init=int(rest[0]) if rest else 0
    log=(out/f'{suite}-{task}-{init}.events.jsonl').open('w',encoding='utf-8');t_obs=[]
    def emit(e):
        e={'ts':time.time(),**e}
        if e['type']!='think_delta':log.write(json.dumps(e,ensure_ascii=False)+'\n');log.flush()
    try:r=A.run(link,model,emit,{'suite':suite,'task':int(task),'init':init})
    except Exception as exc:r={'status':'error','error':repr(exc),'task':spec}
    log.close()
    with (out/'results.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    print('RESULT',json.dumps(r,ensure_ascii=False),flush=True)
link.close()
