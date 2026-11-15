"""Scripted check of the skill library in new randomised scenes (no LLM). usage: dexjoco_skill_test.py LIB.json task seeds...

Runs the simulator in-process (no network) and the board-side perception + skill code on its observations.
"""
import json,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'board'/'dexjoco'))
from dexjoco_server import DexSim
import dex_perception as P,dex_skills as S

class LocalLink:
    def __init__(self,sim):self.sim=sim
    def call(self,op,**kw):
        r=json.loads(json.dumps(self.sim.service({'op':op,**kw})))
        if 'error' in r:raise RuntimeError(r['error'])
        return r

DEBUG=[]
PLANS={'bimanual_hanoi':['pick_disk_medium',('servo','disk_medium','peg_C'),'pick_disk_small',('servo','disk_small','peg_C')]}

def run(lib,task,seed,video=None):
    sim=DexSim(realtime=False);link=LocalLink(sim);link.call('reset',task=task,seed=seed);arms=S.Arms(link)
    L=lib[task];holding=None;log=[];static=None
    dims={};arm_of={}
    def look():
        o=link.call('observe');arms.sync(o);return o,{**P.scene(o),**static}
    for name in PLANS[task]:
        obs=link.call('observe');arms.sync(obs);sc=P.scene(obs)
        if static is None:
            static={n:v for n,v in sc.items() if n in S.STATIC};dims={n:v['top_z']-v['bottom_z'] for n,v in sc.items()}
        sc={**sc,**static}
        if isinstance(name,tuple):
            _,obj,peg=name;arm=arm_of[obj];h=dims[obj]
            top=S.ref_from_scene({'kind':'peg','name':peg},sc,exclude=[obj])['p'][2]
            lg=arms.servo_place(arm,look,obj,static[peg]['center'][:2],static[peg]['top_z']+h/2+.03,top+h/2+.008,arms.open_hand[arm])
            log.append((name,lg))
            if DEBUG:print('   after',name,'truth:',{b:[round(float(v),3) for v in sim.d.body(b).xpos] for b in DEBUG},flush=True)
            continue
        sk=L['skills'][name]
        refs={a:S.ref_from_scene(r,sc,exclude=r.get('exclude',())) for a,r in sk['ref'].items()}
        held={a:S.held_offset(obs['arms'][a]['flange'],sc[o]['center']) for a,o in sk.get('held',{}).items() if o in sc}
        if DEBUG and held:print('   held now',held,'demo',sk.get('held_offset'),'peg',[round(v,3) for v in list(refs.values())[0]['p']]);
        def correct(skill,refs,j=0):
            o=link.call('observe');sc2={**P.scene(o),**static};e=S.check_error(skill,refs,sc2,j)
            if DEBUG:print('   check error',{a:[round(float(x),3) for x in v] for a,v in e.items()})
            return e
        arms.play(sk,refs,held,correct=correct)
        a0=list(sk['frames'])[0]
        if name.startswith('pick'):
            arm_of[name[5:]]=a0;arms.open_hand=getattr(arms,'open_hand',{});arms.open_hand[a0]=S.to_world(sk['frames'][a0][:1],{'p':[0,0,0],'yaw':0})[0][7:]
            if sk.get('squeeze'):arms.grip(a0)
        log.append((name,{a:[round(v,3) for v in r['p']] for a,r in refs.items()}))
        if DEBUG:print('   after',name,'truth:',{b:[round(float(v),3) for v in sim.d.body(b).xpos] for b in DEBUG},flush=True)
    arms.send([{}]*60)
    tr=link.call('truth')
    if video:sim.save_video(video)
    return tr['success'],log

if __name__=='__main__':
    import os;DEBUG.extend(os.environ.get('DBG_BODIES','').split(',') if os.environ.get('DBG_BODIES') else [])
    lib=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));task=sys.argv[2]
    for s in sys.argv[3:]:
        t=time.time();ok,log=run(lib,task,int(s),video=f'C:/Users/jielu/Desktop/RV/.venv/dexjoco/test-{task}-{s}.mp4')
        print('seed',s,'SUCCESS' if ok else 'fail','%.0fs'%(time.time()-t),log,flush=True)
