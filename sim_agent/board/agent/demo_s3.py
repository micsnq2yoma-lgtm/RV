"""S3 seeded ground-truth evaluation; no perception and no model API."""
import argparse,json,time,os
from pathlib import Path
import numpy as np
from kin import HOME,down,quat_matrix,rotation_error
from skills import Skills
from transport import RTClient,SimClient


def emit(**data):print(json.dumps(data),flush=True)


def validate(skills,seed=11):
    rng=np.random.default_rng(seed);kin=skills.kin;fk_rows=[];ik_rows=[]
    for i in range(50):
        goal=rng.uniform(kin.limits[:,0],kin.limits[:,1])
        skills.joints(goal,.08,settle=1.)
        actual=skills.sim.call('ee_pose')
        p,r=kin.fk(actual['q'])
        row=dict(test='fk',i=i,goal=goal.tolist(),actual_q=actual['q'],position_error_m=float(np.linalg.norm(p-actual['pos'])),
                 rotation_error_deg=float(np.linalg.norm(rotation_error(quat_matrix(actual['quat']),r))*180/np.pi),
                 tracking_error_rad=float(np.max(np.abs(np.array(actual['q'])-goal))))
        fk_rows.append(row);emit(**row)
    for i in range(30):
        target=[float(rng.uniform(.45,.70)),float(rng.uniform(-.25,.25)),float(rng.uniform(.025,.25))]
        start=time.perf_counter()
        try:
            q=kin.ik(target,down(),HOME);p,r=kin.fk(q)
            row=dict(test='ik',i=i,target=target,ok=True,seconds=time.perf_counter()-start,
                     position_error_m=float(np.linalg.norm(p-target)),rotation_error_deg=float(np.linalg.norm(rotation_error(down(),r))*180/np.pi))
        except RuntimeError as e:row=dict(test='ik',i=i,target=target,ok=False,seconds=time.perf_counter()-start,error=str(e))
        ik_rows.append(row);emit(**row)
    emit(validation_summary=True,fk_position_max=max(r['position_error_m'] for r in fk_rows),
         fk_rotation_max=max(r['rotation_error_deg'] for r in fk_rows),ik_success=sum(r['ok'] for r in ik_rows),
         ik_mean_seconds=float(np.mean([r['seconds'] for r in ik_rows])))


def demo(skills,count,out,first_seed=0,tasks=(1,2)):
    results=[]
    for task in tasks:
        for trial in range(count):
            seed=first_seed+trial; start=time.monotonic();reason=None;success=False
            try:
                skills.rt.cancel();skills.sim.call('reset',seed=seed);time.sleep(.5)
                skills.home();objects=skills.objects()
                if task==2 and trial==0:skills.sim.photo(out/'stack-before.jpg')
                source=objects['red_cube' if task==1 else 'blue_cube']['pos']
                if not skills.pick(*source[:2]):raise RuntimeError('grasp width outside 0.03-0.05m')
                if task==2 and trial==0:skills.sim.photo(out/'stack-picked.jpg')
                if task==1:
                    tray=objects['left_tray']['pos'];skills.place(tray[0],tray[1],.028)
                else:
                    green=skills.objects()['green_cube']['pos'];skills.place(green[0],green[1],green[2]+.04)
                time.sleep(1.)
                after=skills.objects()
                if task==1:
                    red=np.array(after['red_cube']['pos']);tray=np.array(after['left_tray']['pos'])
                    success=bool(abs(red[0]-tray[0])<.08 and abs(red[1]-tray[1])<.06 and .02<red[2]<.05)
                else:
                    blue=np.array(after['blue_cube']['pos']);green=np.array(after['green_cube']['pos'])
                    success=bool(np.linalg.norm(blue[:2]-green[:2])<.02 and abs(blue[2]-green[2]-.04)<.01)
                    if success and not (out/'stack-success.jpg').exists():skills.sim.photo(out/'stack-success.jpg')
                if not success:reason='ground-truth placement outside tolerance'
                emit(final_objects=after,task=task,trial=trial)
            except (RuntimeError,TimeoutError,ValueError) as e:
                reason=str(e)
                try:skills.rt.cancel()
                except Exception:pass
            row=dict(task=task,trial=trial,seed=seed,success=success,seconds=time.monotonic()-start,reason=reason)
            results.append(row);emit(**row)
    for task in tasks:
        rows=[r for r in results if r['task']==task]
        emit(summary=True,task=task,success=sum(r['success'] for r in rows),total=len(rows),mean_seconds=float(np.mean([r['seconds'] for r in rows])))


if __name__=='__main__':
    os.sched_setaffinity(0,{0})
    emit(agent_cpus=sorted(os.sched_getaffinity(0)))
    p=argparse.ArgumentParser();p.add_argument('--validate',action='store_true');p.add_argument('--count',type=int,default=10)
    p.add_argument('--task',type=int,choices=[1,2]);p.add_argument('--check-interfaces',action='store_true');p.add_argument('--first-seed',type=int,default=0);p.add_argument('--out',type=Path,default=Path('/root/rv011-images'));a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    sim=SimClient();rt=RTClient()
    try:
        for attempt in range(50):
            try:rt.call();break
            except RuntimeError as e:
                if 'status=2' not in str(e):raise
                time.sleep(.1)
        else:raise RuntimeError('no simulation state after five seconds')
        skills=Skills(sim,rt)
        if a.check_interfaces:
            from check_interfaces import check_interfaces
            check_interfaces(skills)
        if a.validate:validate(skills)
        else:demo(skills,a.count,a.out,a.first_seed,(a.task,) if a.task else (1,2))
    finally:
        try:rt.cancel()
        finally:rt.close();sim.close()
