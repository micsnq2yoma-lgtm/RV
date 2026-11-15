"""Run DexJoCo agent episodes. usage: run_local.py LIB.json OUT_DIR task:seed ...
Local (PC): key from env DEEPSEEK_API_KEY. Board: run_board.py (key file + proxy).
The PC runs dexjoco_server.py --agent-ip <this host> and connects in on TCP 15005.
"""
import json,os,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'nav'))
from link import NavLink
import dex_agent as A

def main(board=False):
    lib=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
    link=NavLink(port=15005,timeout=1800);link.sock.settimeout(120);print('simulator connected',flush=True)
    if board:
        from agent import Model;model=Model()
    else:model=A.local_model()
    for spec in sys.argv[3:]:
        task,seed=(spec.split(':')+['0'])[:2];seed=int(seed)
        log=(out/f'{task}-{seed}.events.jsonl').open('w',encoding='utf-8')
        def emit(e):
            e={'ts':time.time(),**e}
            if e['type']!='think_delta':log.write(json.dumps(e,ensure_ascii=False,default=str)+'\n');log.flush()
        try:r=A.run(link,model,emit,lib,task,seed)
        except Exception as exc:r={'status':'error','error':repr(exc),'task':task,'seed':seed}
        log.close()
        try:link.call('video',path=f'C:/Users/jielu/Desktop/RV/.venv/dexjoco/video/{out.name}-{task}-{seed}.mp4')
        except Exception as exc:print('video failed',exc,flush=True)
        with (out/'results.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(r,ensure_ascii=False)+'\n')
        print('RESULT',json.dumps(r,ensure_ascii=False),flush=True)
    link.close()

if __name__=='__main__':main(board=False)
