"""Local UI preview: serves the real workbench files with a scripted event stream (no board needed).

The event sequence is synthetic and labelled as such; it exists to check layout and rendering.
Video tiles still come from a running sim_server --mjpeg 127.0.0.1:8090 if one is up.
"""
import argparse,json,math,random,threading,time
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
AGENT=Path(__file__).resolve().parents[1]/'board'/'agent';GOALS=Path(__file__).resolve().parents[1]/'goals'

def script(t0):
    plan1=['pick green_cube','place_on_table','pick red_cube','stack_on blue_cube','pick green_cube','stack_on red_cube']
    plan2=['pick red_cube（按新位置）','stack_on blue_cube','pick green_cube','stack_on red_cube']
    scene=lambda towers,loose,h=None:{'towers':towers,'loose':loose,'holding':h,'occluded_or_inferred':[]}
    det=[{'name':'red','bbox':[352,250,30,30]},{'name':'blue','bbox':[300,200,30,30]},{'name':'green','bbox':[301,201,28,28]},{'name':'orange','bbox':[420,300,30,30]}]
    think='目标是蓝在最下面、红在中间、绿在最上面。现在绿色压在蓝色上，必须先把绿色拿开，否则红色放不上去。橙色不在目标里，留在桌面。'
    ev=[(0,{'type':'task_start','kind':'goal_stack','text':'按照目标图片的顺序把积木叠起来','scenario':'G2','seed':15201,
             'goal':{'towers':[['blue','red','green']],'loose':['orange'],'image_url':'/goal-images/preview.jpg','confidence':.95}}),
        (.5,{'type':'observe','scene':scene([['blue_cube','green_cube']],['red_cube','orange_cube']),'detections':det,'seconds':.62})]
    t=1.
    for ch in [think[i:i+3] for i in range(0,len(think),3)]:ev.append((t,{'type':'think_delta','text':ch,'channel':'reasoning_content'}));t+=.06
    ev+=[(t,{'type':'think_end','text':think,'tokens':{'total_tokens':1180}}),(t+.1,{'type':'plan','version':1,'steps':plan1,'reason':'绿压在蓝上，先拆再搭'}),
         (t+.3,{'type':'step_start','index':1,'tool':'pick','args':{'object':'green_cube'},'expected_s':7}),
         (t+3,{'type':'step_result','ok':True,'index':1,'detail':{'ok':True,'holding':'green_cube','gripper_m':.0401}}),
         (t+3.5,{'type':'step_start','index':2,'tool':'place_on_table','args':{},'expected_s':9}),
         (t+6,{'type':'step_result','ok':True,'index':2,'detail':{'ok':True,'placed':'green_cube','on':'table','xy':[.58,-.18],'z':.021}}),
         (t+6.5,{'type':'observe','scene':scene([],['blue_cube','green_cube','red_cube','orange_cube']),'detections':det,'seconds':.58}),
         (t+7,{'type':'think_end','text':'绿色已经放到桌面，蓝色露出来了。下一步抓红色。','tokens':{'total_tokens':1210}}),
         (t+7.2,{'type':'step_start','index':3,'tool':'pick','args':{'object':'red_cube'},'expected_s':7}),
         (t+10,{'type':'step_result','ok':False,'index':3,'detail':{'ok':False,'error':'夹爪宽度不像夹住了积木（可能被推开），已回到初始位置'}}),
         (t+10.5,{'type':'observe','scene':scene([],['blue_cube','green_cube','red_cube','orange_cube']),'detections':det,'seconds':.6}),
         (t+11,{'type':'think_end','text':'红色被推开了，按新位置重抓，剩下的步骤重新规划。','tokens':{'total_tokens':1300}}),
         (t+11.2,{'type':'plan','version':2,'steps':plan2,'reason':'抓取失败，红色位置变了'}),
         (t+11.4,{'type':'step_start','index':1,'tool':'pick','args':{'object':'red_cube'},'expected_s':7}),
         (t+14,{'type':'step_result','ok':True,'index':1,'detail':{'ok':True,'holding':'red_cube','gripper_m':.0399}}),
         (t+14.4,{'type':'step_start','index':2,'tool':'stack_on','args':{'object':'blue_cube'},'expected_s':9})]
    return [(t0+dt,e) for dt,e in ev]

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def send(self,code,body,ctype):
        self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def json(self,obj):self.send(200,json.dumps(obj).encode(),'application/json')
    def do_GET(self):
        p=self.path.split('?')[0]
        if p=='/':return self.send(200,(AGENT/'dashboard.html').read_bytes(),'text/html; charset=utf-8')
        if p.startswith('/static/'):
            f=(AGENT/p.lstrip('/')).resolve()
            if AGENT in f.parents and f.is_file():return self.send(200,f.read_bytes(),{'.css':'text/css','.js':'text/javascript','.woff2':'font/woff2'}.get(f.suffix,'text/plain'))
        if p=='/goal-images/preview.jpg':return self.send(200,(GOALS/'blue-red-green.jpg').read_bytes(),'image/jpeg')
        if p=='/state':return self.json({'connected':True,'worker_ready':True,'busy':True})
        if p=='/goals':return self.json({'presets':[{'id':x.stem,'name':x.stem} for x in sorted(GOALS.glob('*.json'))],'scenarios':{'G2':{'title':'绿压在蓝上 → 蓝·红·绿','goal':'blue-red-green'}}})
        if p=='/runs':return self.json([])
        if p=='/events':
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            t0=time.time();queue=script(t0);n=0;rng=random.Random(1);lost=0
            try:
                while True:
                    now=time.time()
                    while queue and queue[0][0]<=now:
                        ts,e=queue.pop(0);n+=1;self.wfile.write(f"id: {n}\ndata: {json.dumps({'ts':ts,'run':'preview',**e},ensure_ascii=False)}\n\n".encode())
                    if int(now*2)%2==0 and getattr(self,'_last',0)!=int(now):
                        self._last=int(now);n+=1;w=.42+rng.random()*.2
                        e={'type':'sysmon','utc':now,'ts':now,'kernel':'6.6.90-rt54+','loadavg':['1.02','0.96','0.88'],
                           'cpus':{'cpu0':{'busy':55+rng.random()*20},'cpu1':{'busy':12+rng.random()*6}},'memory':{'total_mb':2000,'available_mb':1840},
                           'rt':{'processing_us_mean':177,'processing_us_max':560,'interval_ms_max':14.2,'lost':lost,'window_processing_us_max':w*1000},
                           'eth0_bytes_per_s':{'rx':47000,'tx':34000},'irq_per_s':{'eth0':511,'emmc':0,'serial':3},'temperatures_c':[],
                           'processes':{'rt_ctl':{'percent':9,'cpu':1,'policy':1,'priority':-81},'agent':{'percent':38,'cpu':0,'policy':0,'priority':20},'dashboard':{'percent':6,'cpu':0,'policy':0,'priority':20}}}
                        self.wfile.write(f"id: {n}\ndata: {json.dumps({'run':None,**e})}\n\n".encode())
                    self.wfile.flush();time.sleep(.05)
            except OSError:return
        self.send(404,b'not found','text/plain')

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--port',type=int,default=8099);args=a.parse_args()
    s=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);s.daemon_threads=True;print('preview on http://127.0.0.1:%d'%args.port,flush=True);s.serve_forever()
