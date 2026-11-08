"""One-second /proc sampling, JSON for dashboard and CSV for each RAM run."""
import csv,json,os,time
from pathlib import Path

def read(path):
    try:return Path(path).read_text()
    except OSError:return ''
def rt_stats():
    try:
        with open('/tmp/rt_ctl.stats','rb') as f:f.seek(0,2);size=f.tell();f.seek(max(0,size-65536));lines=f.read().splitlines()
        for line in reversed(lines):
            try:
                row=json.loads(line)
                if 'rx' in row:return row
            except ValueError:pass
    except OSError:pass
    return {}
class Monitor:
    def __init__(self):self.previous=None;self.hz=os.sysconf('SC_CLK_TCK')
    def sample(self,pids):
        now=time.monotonic();cpu={};irqs={};procs={}
        for line in read('/proc/stat').splitlines():
            fields=line.split()
            if fields and fields[0].startswith('cpu') and fields[0][3:].isdigit():cpu[fields[0]]=list(map(int,fields[1:9]))
        for line in read('/proc/interrupts').splitlines():
            for label,token in [('eth0','eth0'),('emmc','f9cda1000'),('tf','f99f04000'),('serial','f9c250000')]:
                if token in line:
                    fields=line.split()[1:];irqs[label]=sum(int(x) for x in fields if x.isdigit())
        network={}
        for line in read('/proc/net/dev').splitlines():
            if line.strip().startswith('eth0:'):
                values=line.split(':')[1].split();network={'rx':int(values[0]),'tx':int(values[8])}
        for name,pid in pids.items():
            raw=read(f'/proc/{pid}/stat')
            if raw:
                f=raw.rsplit(')',1)[1].split();procs[name]={'pid':pid,'ticks':int(f[11])+int(f[12]),'cpu':int(f[36]),'priority':int(f[37]),'policy':int(f[38])}
        snapshot={'time':now,'cpu':cpu,'irq':irqs,'net':network,'proc':procs};prev=self.previous;self.previous=snapshot
        if prev is None:return None
        dt=now-prev['time'];cores={}
        for name,values in cpu.items():
            diff=[max(0,a-b) for a,b in zip(values,prev['cpu'].get(name,values))];total=max(1,sum(diff))
            row={key:diff[i]*100/total for key,i in [('user',0),('nice',1),('system',2),('idle',3),('iowait',4),('irq',5),('softirq',6)]};row['busy']=100-row['idle']-row['iowait'];cores[name]=row
        for name,value in procs.items():
            old=prev['proc'].get(name);value['percent']=(value['ticks']-old['ticks'])/self.hz/dt*100 if old and old['pid']==value['pid'] else None
        mem={line.split(':')[0]:int(line.split()[1]) for line in read('/proc/meminfo').splitlines()}
        fs=os.statvfs('/tmp');temps=[]
        for p in Path('/sys/class/thermal').glob('thermal_zone*/temp'):
            try:temps.append(float(p.read_text())/1000)
            except (OSError,ValueError):pass
        return {'utc':time.time(),'cpus':cores,'memory':{'total_mb':mem.get('MemTotal',0)/1024,'available_mb':mem.get('MemAvailable',0)/1024,'tmp_used_mb':(fs.f_blocks-fs.f_bfree)*fs.f_frsize/1048576},
                'loadavg':read('/proc/loadavg').split()[:3],'irq_per_s':{k:(v-prev['irq'].get(k,v))/dt for k,v in irqs.items()},
                'eth0_bytes_per_s':{k:(v-prev['net'].get(k,v))/dt for k,v in network.items()},'processes':procs,'rt':rt_stats(),'temperatures_c':temps}

def main():
    os.sched_setaffinity(0,{0});monitor=Monitor();last_run=None;file=None;writer=None
    try:
        while True:
            started=time.monotonic()
            try:state=json.loads(read('/tmp/rv014/current.json'))
            except ValueError:state={}
            data=monitor.sample(state.get('pids',{}))
            if data:
                path=Path('/tmp/rv014/sysmon.json');tmp=path.with_suffix('.new');tmp.write_text(json.dumps(data));tmp.replace(path)
                run=state.get('run')
                if run!=last_run:
                    if file:file.close()
                    file=None;last_run=run
                    if run:
                        file=open(Path('/tmp/runs')/run/'sysmon.csv','a',newline='');writer=csv.writer(file)
                        if file.tell()==0:writer.writerow(['utc','cpu0_percent','cpu1_percent','available_mb','tmp_used_mb','rt_processing_max_us','data_json'])
                if file:
                    writer.writerow([data['utc'],data['cpus'].get('cpu0',{}).get('busy'),data['cpus'].get('cpu1',{}).get('busy'),data['memory']['available_mb'],data['memory']['tmp_used_mb'],data['rt'].get('lifetime_processing_us_max'),json.dumps(data)]);file.flush()
                rt=data['rt'];cpu=data['cpus'];net=data['eth0_bytes_per_s'];irq=data['irq_per_s']
                print('CPU0 %.0f%% CPU1 %.0f%% | mem %.0f/%.0fM | rt proc %.2f/%.2fms gap %.1fms loss %s | eth0 rx %.0fk tx %.0fk | irq eth0 %.0f/s mmc %.0f/s | agent: %s' %
                    (cpu.get('cpu0',{}).get('busy',0),cpu.get('cpu1',{}).get('busy',0),data['memory']['total_mb']-data['memory']['available_mb'],data['memory']['total_mb'],rt.get('processing_us_mean',0)/1000,rt.get('lifetime_processing_us_max',0)/1000,rt.get('lifetime_interval_ms_max',0),rt.get('lost','?'),net.get('rx',0)/1024,net.get('tx',0)/1024,irq.get('eth0',0),irq.get('emmc',0),state.get('action','idle')),flush=True)
            time.sleep(max(0,1-(time.monotonic()-started)))
    finally:
        if file:file.close()
if __name__=='__main__':main()
