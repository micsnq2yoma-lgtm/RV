"""Build the DexJoCo skill library from human teleoperation demos (offline, on the PC, DexJoCo conda env).

usage: python dexjoco_build_skills.py DEMO_ROOT OUT.json [task ...]
DEMO_ROOT holds the DexJoCo raw dataset folders (<task>/<demo>/replay.zarr). For each skill below, the demo is
replayed in the simulator from its recorded initial state; at the skill's first step the board-side perception
measures the reference (object / peg) from rendered depth + masks, and the demo's commands for the chosen arm(s)
over [t0, t1) are stored relative to it. The output is not committed: it is derived from the DexJoCo dataset.
"""
import json,sys,importlib
from pathlib import Path
import numpy as np,zarr
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'board'/'dexjoco'))
from dexjoco_server import DexSim
import dex_perception as P,dex_skills as S
from dexjoco.tasks.state_restorers import has_restorer,restore_initial_state

O=lambda n,**k:{'kind':'object','name':n,**k}
PEG=lambda n,ex:{'kind':'peg','name':n,'exclude':[ex]}
WORLD={'kind':'world'}
SPECS={
 'bimanual_hanoi':{'demo':1,'skills':[
   {'name':'pick_disk_medium','arms':{'right':O('disk_medium')},'t':[60,200]},
   {'name':'place_disk_medium','arms':{'right':PEG('peg_C','disk_medium')},'t':[230,400],'held':{'right':'disk_medium'}},
   {'name':'pick_disk_small','arms':{'left':O('disk_small')},'t':[675,815],'demo':0},
   {'name':'place_disk_small','arms':{'left':PEG('peg_C','disk_small')},'t':[600,783],'held':{'left':'disk_small'},'demo':1}]},
 # The microwave is fixed in this task (only the hot dog is randomised), so the door motions are world-frame segments.
 'bimanual_microwave_cook':{'demo':1,'skills':[
   {'name':'open_door','arms':{'left':WORLD},'t':[0,450]},
   {'name':'pick_hot_dog','arms':{'right':O('hot_dog')},'t':[256,396]},   # yaw transfer hurt (noisy PCA yaw)
   {'name':'put_in_microwave','arms':{'right':WORLD},'t':[396,570],'held':{'right':'hot_dog'}},
   {'name':'close_door_and_start','arms':{'left':WORLD,'right':WORLD},'t':[570,750]}]},
 # All assembly skills from one demo so the grasps match the insertion; the socket is measured once it hangs still.
 'bimanual_assembly':{'demo':4,'skills':[
   {'name':'pick_socket','arms':{'left':O('socket')},'t':[47,187]},
   {'name':'pick_peg','arms':{'right':O('peg')},'t':[155,285]},
   {'name':'present_socket','arms':{'left':WORLD},'t':[187,330],'held':{'left':'socket'}},
   {'name':'insert_peg','arms':{'right':O('socket',z='center')},'t':[285,577],'ref_t':330,'held':{'right':'peg'}}]},
 'bimanual_photograph':{'demo':0,'skills':[
   {'name':'pick_camera','arms':{'left':O('camera')},'t':[40,170]},
   {'name':'aim_and_shoot','arms':{'left':O('logo',z='center')},'t':[170,260],'held':{'left':'camera'}},
   # The shutter is pressed by the right index finger (last frame of the demo): its motion relative to the aimed camera.
   {'name':'shoot','arms':{'right':O('camera',anchor='top_center')},'t':[170,260],'ref_t':255}]},
 # One press motion, cut around the press of digit 1 and stored relative to that button; replayed at any button.
 'bimanual_unlock_ipad':{'demo':2,'skills':[
   {'name':'pick_ipad','arms':{'left':O('ipad')},'t':[20,230]},
   {'name':'press','arms':{'right':O('button_1',z='center')},'t':[224,282],'ref_t':262,'mark':269}]},
}

def replay(task,demo,skills):
    """Replay one demo; at each skill's first step measure its references and cut its frames."""
    z=zarr.open(str(demo/'replay.zarr'),mode='r');A=np.asarray(z['data']['action']);st=np.asarray(z['data']['state'][0]).ravel()
    sim=DexSim(realtime=False,views=False);sim.reset(task,0);cfg=importlib.import_module(f'dexjoco.tasks.{task}.config').TaskConfig()
    if has_restorer(task):restore_initial_state(sim.env,task,cfg,st)
    marks={};checks={}
    for s in skills:marks.setdefault(s.get('ref_t',s['t'][0]),[]).append(s)   # ref_t: measure the reference later (a moving object)
    out={};static=None
    for t in range(len(A)):
        if static is None:   # fixtures measured once at the start, as the agent does at run time
            static={n:v for n,v in P.scene(sim.observe()).items() if n in S.STATIC}
        for s in marks.get(t,[]):
            obs=sim.observe();sc_now=P.scene(obs);sc={**sc_now,**static}
            entry={'arms':list(s['arms']),'frames':{},'ref':s['arms'],'demo':demo.name,'t':s['t'],'squeeze':s.get('squeeze',0),**({'mark_index':s['mark']-s['t'][0]} if 'mark' in s else {})}
            for arm,ref in s['arms'].items():
                r=S.ref_from_scene(ref,sc,exclude=ref.get('exclude',()),arms=obs['arms']);sl=slice(0,23) if arm=='right' else slice(23,46)
                entry['frames'][arm]=np.round(S.to_rel(A[s['t'][0]:s['t'][1],sl],r),5).tolist();entry.setdefault('ref_demo',{})[arm]=r
            for arm,ref in s['arms'].items():   # object held by the other hand: where it sits relative to that flange
                if ref['kind']=='flange' and ref.get('obj') in sc_now:
                    entry.setdefault('obj_rel',{})[arm]=(np.asarray(sc_now[ref['obj']]['center'])-np.asarray(obs['arms'][ref['arm']]['flange'][:3])).tolist()
            for arm,obj in s.get('held',{}).items():
                entry.setdefault('held_offset',{})[arm]=S.held_offset(obs['arms'][arm]['flange'],sc_now[obj]['center']);entry.setdefault('held',{})[arm]=obj
            if s.get('held'):   # closed-loop check ~0.8 s before the demo opens the hand
                arm=list(s['held'])[0];entry['check_index']=S.check_points(entry['frames'][arm])
                for j,ck in enumerate(entry['check_index']):checks.setdefault(t+ck,[]).append((s['name'],entry,j))
                ri=S.Arms.release_index(entry['frames'][arm])
                if ri and ri>2:checks.setdefault(t+ri-2,[]).append((s['name'],entry,'release'))
            out[s['name']]=entry;print(task,s['name'],demo.name[:30],'ref',{a:[round(v,3) for v in r['p']] for a,r in entry['ref_demo'].items()},flush=True)
        for name,entry,j in checks.get(t,[]):   # where the held object was, relative to the reference, at each check frame
            sc_now=P.scene(sim.observe())
            for arm,obj in entry['held'].items():
                r=entry['ref_demo'][arm];rel=(S.Rz(-r['yaw'])@(np.asarray(sc_now[obj]['center'])-np.asarray(r['p']))).tolist()
                if j=='release':entry.setdefault('release_rel',{})[arm]=rel   # how 'aligned' looks to perception, just before release
                else:entry.setdefault('check_rel',{}).setdefault(arm,[]).append(rel)
            print('   check',name,j,np.round(rel,3).tolist())
        a=A[t];sim.step([{'right':a[:23].tolist(),'left':a[23:46].tolist()}])
    return out,{a:[float(x) for x in A[0][(0 if a=='right' else 23):(23 if a=='right' else 46)]] for a in ('right','left')}

def build(task,spec,root):
    demos=sorted(p for p in (Path(root)/task).iterdir() if (p/'replay.zarr').exists())
    groups={}
    for s in spec['skills']:groups.setdefault(s.get('demo',spec.get('demo',0)),[]).append(s)
    out={};home=None
    for k,sk in sorted(groups.items()):
        o,h=replay(task,demos[k],sk);out.update(o);home=home or h
    return {'home':home,'skills':out}

def main():
    root,dst=sys.argv[1],Path(sys.argv[2]);tasks=sys.argv[3:] or list(SPECS)
    lib=json.loads(dst.read_text(encoding='utf-8')) if dst.exists() else {}
    for t in tasks:lib[t]=build(t,SPECS[t],root)
    dst.write_text(json.dumps(lib),encoding='utf-8');print('wrote',dst,round(dst.stat().st_size/1e6,2),'MB')
if __name__=='__main__':main()
