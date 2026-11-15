"""Run LIBERO agent episodes. usage: run_local.py OUT_DIR suite:task[:init] ...  (env DEEPSEEK_API_KEY)"""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'nav'))
from link import NavLink
import libero_agent as A
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
link=NavLink(port=15004,timeout=600);print('simulator connected',flush=True)
model=A.local_model()
for spec in sys.argv[2:]:
    suite,task,*rest=spec.split(':');init=int(rest[0]) if rest else 0
    log=(out/f'{suite}-{task}-{init}.events.jsonl').open('w',encoding='utf-8')
    def emit(e):
        e={'ts':time.time(),**e}
        if e['type']!='think_delta':log.write(json.dumps(e,ensure_ascii=False)+'\n');log.flush()
    try:r=A.run(link,model,emit,{'suite':suite,'task':int(task),'init':init})
    except Exception as exc:r={'status':'error','error':repr(exc),'task':spec}
    log.close()
    with (out/'results.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    print(json.dumps(r,ensure_ascii=False),flush=True)
link.close()
