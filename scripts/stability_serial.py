"""Windows-side continuous capture; task 012's only transmit action is SysRq w/l/t."""
import argparse,json,time
from pathlib import Path
import serial
from serial_console import TimestampLog

p=argparse.ArgumentParser();p.add_argument('--port',required=True);p.add_argument('--log',required=True);p.add_argument('--control',required=True);a=p.parse_args()
control=Path(a.control)
conn=serial.Serial(port=None,baudrate=115200,timeout=.1,write_timeout=2)
conn.dtr=conn.rts=False;conn.port=a.port
with conn,TimestampLog(a.log) as log:
 print('Continuous serial capture ready',flush=True)
 sequence=[]
 while True:
  data=conn.read(max(1,min(conn.in_waiting,8192)))
  if data:log.write(data)
  if control.exists():
   action=control.read_text().strip();control.unlink()
   if action=='stop':break
   if action=='sysrq':
    # The 30-second passive observation precedes any break/letter.
    start=time.monotonic();sequence=[(start+30+5*i,k) for i,k in enumerate('wlt')]
    log.write(b'\n[host] Suspected hang; observe 30 seconds before SysRq\n')
  if sequence and time.monotonic()>=sequence[0][0]:
   _,key=sequence.pop(0);conn.send_break(.25);conn.write(key.encode())
   log.write(('\n[host] Sent serial break then SysRq '+key+'\n').encode())
   if not sequence:print('SysRq w/l/t transmitted; capture continues',flush=True)
