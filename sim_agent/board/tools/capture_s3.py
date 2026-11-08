"""Supplemental S3 illustration, excluded from fixed-seed acceptance statistics."""
import json,os,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from transport import SimClient,RTClient
from skills import Skills

os.sched_setaffinity(0,{0})
out=Path('/root/rv011-images/evidence');out.mkdir(parents=True,exist_ok=True)
sim=SimClient();rt=RTClient()
try:
 for _ in range(50):
  try:rt.call();break
  except RuntimeError:time.sleep(.1)
 skills=Skills(sim,rt);rt.cancel();sim.call('reset',seed=0);time.sleep(.5);skills.home()
 sim.photo(out/'stack-before.jpg')
 obj=skills.objects();assert skills.pick(*obj['blue_cube']['pos'][:2])
 sim.photo(out/'stack-picked-wrist.jpg',camera='wrist')
 green=skills.objects()['green_cube']['pos'];skills.place(green[0],green[1],green[2]+.04)
 time.sleep(1);sim.photo(out/'stack-released-wrist.jpg',camera='wrist')
 skills.home();time.sleep(.5);sim.photo(out/'stack-clear-top.jpg')
 after=skills.objects();blue=after['blue_cube']['pos'];green=after['green_cube']['pos']
 ok=(sum((blue[i]-green[i])**2 for i in [0,1])**.5<.02 and abs(blue[2]-green[2]-.04)<.01)
 print(json.dumps({'supplemental_evidence_only':True,'seed':0,'success_after_retreat':ok,'objects':after}),flush=True)
 assert ok
finally:
 try:rt.cancel()
 finally:rt.close();sim.close()
