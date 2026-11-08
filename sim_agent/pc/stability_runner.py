import argparse,json,os,subprocess,threading,time,shlex,re
from pathlib import Path
import paramiko
p=argparse.ArgumentParser();p.add_argument('experiment',choices=['E1','E2','E3','E4','E5','E6']);p.add_argument('--label');a=p.parse_args()
a.rt='/tmp/rv012/rt_ctl-buildroot --cpu 1 --sine'
label=a.label or a.experiment
if not re.fullmatch('[A-Za-z0-9_-]+',label):p.error('label must contain only letters, numbers, underscore or hyphen')
out=Path('.venv/012')/label
if out.exists() and any(out.iterdir()):p.error('evidence directory already exists; choose a new --label')
out.mkdir(exist_ok=True)
c=paramiko.SSHClient();c.load_host_keys('.venv/012/known_hosts');c.set_missing_host_key_policy(paramiko.RejectPolicy());c.connect('192.168.50.2',username='root',password=os.environ.pop('RV_BOARD_PASSWORD'),look_for_keys=False,allow_agent=False,timeout=15)
c.get_transport().set_keepalive(5)
def event(**kw):
 row={'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),**kw}
 with (out/'orchestration.log').open('a') as f:f.write(json.dumps(row)+'\n')
 print(json.dumps(row),flush=True)
def command(cmd,name=None,timeout=15):
 _,o,e=c.exec_command(cmd,timeout=timeout);data=o.read()+e.read();rc=o.channel.recv_exit_status()
 if name:(out/name).write_bytes(data)
 if rc:raise RuntimeError('remote command failed '+str(rc))
 return data
def reader(stream,path):
 with path.open('wb') as f:
  while True:
   data=stream.read(1) if hasattr(stream,'read') else stream.recv(8192)
   if not data:break
   f.write(data);f.flush()
pc=ping=None;rt=None;pid=None;hung=False;load=None;load_pid=None;mounted=False;bound=False
def stop_pid(value,token):
 command("if [ -r /proc/"+str(value)+"/cmdline ]; then tr '\\000' ' ' < /proc/"+str(value)+"/cmdline | grep -Fq "+shlex.quote(token)+" && kill -TERM "+str(value)+"; fi")
try:
 command('sha256sum /tmp/rv012/src/rt_ctl /tmp/rv012/src/rt_ctl.c /tmp/rv012/tools/isolation_load.py','build-hashes.log')
 if a.experiment!='E1':
  command("printf 'exit\\n' | HISTFILE=/dev/null sh /mount_emmc.sh start",'mount.log',60);mounted=True
  if a.experiment=='E4':command("if find /mnt/ubuntu/tmp -maxdepth 1 -name 'rv012-stress.*' | grep .; then exit 1; fi; echo 'No E3 stress file remains'",'stress-cleanup-check.log')
  if a.experiment=='E3':command('df -Pk /mnt/ubuntu; set -- $(df -Pk /mnt/ubuntu | tail -1); test "$4" -gt 65536','space.log')
  if a.experiment!='E3':command('mount --bind /tmp /mnt/ubuntu/tmp');bound=True
  command('chroot /mnt/ubuntu ps -eLo pid,tid,cls,rtprio,psr,comm --sort=-rtprio | head -60','threads-before.log')
 if a.experiment in ['E4','E5','E6']:
  a.rt='chroot /mnt/ubuntu /tmp/rv012/src/rt_ctl --cpu 1'+({'E5':' --fifo-priority 40','E6':' --sched-other'}.get(a.experiment,''))
 command('cat /proc/interrupts; cat /proc/mounts; cat /proc/uptime','before.log')
 command("test -x /tmp/rv012/rt_ctl-buildroot; test ! -e /tmp/rt_ctl.sock")
 if a.experiment=='E1':command("! grep -q ' /mnt/ubuntu ' /proc/mounts")
 board_log='/tmp/rv012/logs/'+label+'-rt.log'
 _,rt,_=c.exec_command('sh -c '+shlex.quote('echo OWNED_PID=$$; exec '+a.rt)+' 2>&1 | tee '+board_log)
 t=threading.Thread(target=reader,args=(rt,out/'rt-stream.log'),daemon=True);t.start()
 for _ in range(100):
  s=(out/'rt-stream.log').read_text(errors='replace') if (out/'rt-stream.log').exists() else ''
  if 'mlockall=ok' in s:pid=int(s.split('OWNED_PID=')[1].splitlines()[0]);break
  if rt.channel.exit_status_ready():raise RuntimeError('RT startup failed')
  time.sleep(.1)
 else:raise RuntimeError('RT startup timeout')
 if a.experiment!='E1':
  if a.experiment=='E3':
   cmd='echo OWNED_PID=$$; exec chroot /mnt/ubuntu sh -s < /tmp/rv012/stability_emmc_load.sh'
  else:
   cmd='echo OWNED_PID=$$; exec chroot /mnt/ubuntu env PYTHONDONTWRITEBYTECODE=1 python3 /tmp/rv012/tools/isolation_load.py '+('ik' if a.experiment=='E2' else 'full')+' --out /tmp/rv012/images-'+label
  _,load,_=c.exec_command('sh -c '+shlex.quote(cmd)+' 2>&1 | tee /tmp/rv012/logs/'+label+'-load.log')
  lt=threading.Thread(target=reader,args=(load,out/'load-stream.log'),daemon=True);lt.start()
  for _ in range(100):
   s=(out/'load-stream.log').read_text(errors='replace') if (out/'load-stream.log').exists() else ''
   if 'OWNED_PID=' in s and '\n' in s:load_pid=int(s.split('OWNED_PID=')[1].splitlines()[0]);break
   time.sleep(.1)
  else:raise RuntimeError('load startup timeout')
 command('cat /proc/'+str(pid)+'/stat; cat /proc/'+str(pid)+'/status','rt-process.log')
 if mounted:command('chroot /mnt/ubuntu ps -p '+str(pid)+' -o pid,cls,rtprio,psr,comm','rt-policy.log')
 pinglog=(out/'ping.log').open('wb')
 ping=subprocess.Popen(['ping.exe','-t','192.168.50.2'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 def ping_read():
  for line in iter(ping.stdout.readline,b''):
   pinglog.write(time.strftime('%Y-%m-%dT%H:%M:%SZ ',time.gmtime()).encode()+line);pinglog.flush()
 threading.Thread(target=ping_read,daemon=True).start()
 pcfile=(out/'pc.log').open('w')
 pc=subprocess.Popen([str(Path('.venv/010/py/Scripts/python.exe').resolve()),'sim_agent/pc/sim_server.py','--seconds','600','--stop-on-stdin'],stdin=subprocess.PIPE,stdout=pcfile,stderr=subprocess.STDOUT,text=True)
 event(started=a.experiment,rt_pid=pid,pc_pid=pc.pid,rt_command=a.rt)
 started=time.monotonic();last=0
 while pc.poll() is None:
  if time.monotonic()-started>690:raise TimeoutError('PC deadline')
  if load and load.channel.exit_status_ready():
   event(load_channel_ended=True,elapsed=time.monotonic()-started)
   # RPC clients can see EOF while the PC is closing its graphics process.
   for _ in range(100):
    if pc.poll() is not None:break
    time.sleep(.1)
   else:raise RuntimeError('load exited before PC completion')
   finals=[]
   for line in (out/'pc.log').read_text(errors='replace').splitlines():
    try:
     row=json.loads(line)
     if row.get('final'):finals.append(row)
    except ValueError:pass
   if not finals or finals[-1]['wall_seconds']<600:raise RuntimeError('load ended without a complete PC window')
   break
  if time.time()-(out/'rt-stream.log').stat().st_mtime>15:
   hung=True;event(suspected_hang=True,elapsed=time.monotonic()-started)
   Path('.venv/012/serial-control.txt').write_text('sysrq')
   pc.stdin.write('STOP\n');pc.stdin.flush()
   for i in range(46):time.sleep(1)
   event(sysrq_observation_complete=True);break
  if time.monotonic()-last>30:event(running_seconds=round(time.monotonic()-started));last=time.monotonic()
  time.sleep(.5)
 if not hung:
  if pc.returncode:raise RuntimeError('PC failed')
  if load_pid:
   stop_pid(load_pid,'sh -s' if a.experiment=='E3' else 'isolation_load.py')
   for _ in range(150):
    if load.channel.exit_status_ready():break
    time.sleep(.1)
   else:raise RuntimeError('load stop timeout')
   lt.join(2);event(load_exit=load.channel.recv_exit_status())
   command('cat /tmp/rv012/logs/'+label+'-load.log','load.log')
  command("tr '\\000' ' ' < /proc/"+str(pid)+"/cmdline | grep -q 'rt_ctl' && kill -INT "+str(pid))
  for _ in range(100):
   if rt.channel.exit_status_ready():break
   time.sleep(.1)
  else:raise RuntimeError('RT stop timeout')
  t.join(2);event(rt_exit=rt.channel.recv_exit_status())
  command('cat '+board_log,'rt.log')
  command('cat /proc/interrupts; dmesg | tail -30; for f in /sys/class/thermal/thermal_zone*/temp; do [ ! -f "$f" ] || cat "$f"; done; cat /proc/uptime','after.log')
  event(completed=True)
finally:
 if pc and pc.poll() is None:
  try:pc.stdin.write('STOP\n');pc.stdin.flush();pc.wait(15)
  except Exception:pc.terminate();pc.wait(5)
 if ping and ping.poll() is None:ping.terminate();ping.wait(5)
 if not hung and pid:
  try:command("if [ -r /proc/"+str(pid)+"/cmdline ]; then tr '\\000' ' ' < /proc/"+str(pid)+"/cmdline | grep -q rt_ctl && kill -INT "+str(pid)+"; fi")
  except Exception as e:event(cleanup_error=str(e))
 if not hung and load_pid:
  try:stop_pid(load_pid,'sh -s' if a.experiment=='E3' else 'isolation_load.py')
  except Exception as e:event(load_cleanup_error=str(e))
 if not hung and mounted:
  try:
   if bound:command('umount /mnt/ubuntu/tmp')
   command('sh /mount_emmc.sh stop; sh /mount_emmc.sh status','unmount.log',30)
  except Exception as e:event(unmount_error=str(e))
 c.close()
raise SystemExit(3 if hung else 0)
