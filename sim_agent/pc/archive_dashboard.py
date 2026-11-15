"""Continuously mirror board RAM evidence to PC; never fetch credentials."""
import argparse,json,time,urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--manifest',action='store_true');p.add_argument('--files-every',type=float,default=1);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
http=urllib.request.build_opener(urllib.request.ProxyHandler({}));sizes={};completed=set();last_files=0
def get(path):
    with http.open('http://192.168.50.2:8080'+path,timeout=5) as response:return response.read()
try:
    while not (a.out/'STOP').exists():
        start=time.monotonic()
        try:
            state=json.loads(get('/state'))
            with (a.out/'resources.jsonl').open('a') as f:f.write(json.dumps({'host_utc':time.time(),**state})+'\n')
            if time.monotonic()-last_files<a.files_every:
                time.sleep(max(.1,1-(time.monotonic()-start)));continue
            last_files=time.monotonic();runs=json.loads(get('/runs'))
            for run in runs:
                name=run['run']
                if name in completed:continue
                target=a.out/name;target.mkdir(exist_ok=True);manifest=json.loads(get('/runs/'+name+('/manifest' if a.manifest else '')))
                for file,size in manifest['files'].items():
                    if Path(file).name!=file:raise ValueError('unsafe file name')
                    signature=(size,manifest.get('versions',{}).get(file))
                    if sizes.get((name,file))==signature and (a.manifest or not file.endswith('.json')):continue
                    data=get('/runs/'+name+'/file/'+file);temp=target/(file+'.partial');temp.write_bytes(data);temp.replace(target/file);sizes[name,file]=signature
                if run.get('status')!='running' and 'evaluation.json' in manifest['files']:completed.add(name)
        except Exception as exc:
            with (a.out/'connection.jsonl').open('a') as f:f.write(json.dumps({'host_utc':time.time(),'error':type(exc).__name__})+'\n')
        time.sleep(max(.1,1-(time.monotonic()-start)))
except KeyboardInterrupt:pass
