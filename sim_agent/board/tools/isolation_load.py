"""Task 012: CPU0 IK-only or full S3 load; all output goes to RAM."""
import argparse,json,os,signal,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from kin import Kinematics,HOME,down
from transport import SimClient,RTClient
from skills import Skills
from demo_s3 import demo

def main():
 def stop(signum, frame):raise KeyboardInterrupt
 signal.signal(signal.SIGTERM,stop)
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['ik','full']);p.add_argument('--out',type=Path,default=Path('/tmp/rv012/images'));a=p.parse_args()
 os.sched_setaffinity(0,{0})
 sim=SimClient();rt=None
 try:
  kin=Kinematics(sim.call('kinematics'));start=time.monotonic();count=0
  if a.mode=='ik':
   while True:
    kin.ik([.65,.12,.08],down(),HOME);count+=1
    print(json.dumps({'ik_completed':count,'elapsed':time.monotonic()-start,'cpus':sorted(os.sched_getaffinity(0))}),flush=True)
  else:
   rt=RTClient()
   for _ in range(50):
    try:rt.call();break
    except RuntimeError:time.sleep(.1)
   skills=Skills(sim,rt);directory=a.out;directory.mkdir(parents=True,exist_ok=True)
   while True:
    demo(skills,1,directory,first_seed=count,tasks=(1,2));count+=1
 except KeyboardInterrupt:pass
 finally:
  if rt:
   try:rt.cancel()
   finally:rt.close()
  sim.close()

if __name__=='__main__':main()
