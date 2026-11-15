"""Loopback-only latest-frame MJPEG cache, rendered by the graphics thread."""
import base64,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs

CAMERAS=('top','front','side','wrist')
def parameters(path,cameras=CAMERAS):
    url=urlsplit(path);parts=url.path.split('/')
    if len(parts)!=3 or parts[1]!='stream' or not parts[2].endswith('.mjpg'):raise ValueError('unknown stream')
    camera=parts[2][:-5];q=parse_qs(url.query,strict_parsing=True,keep_blank_values=True)
    if camera not in cameras or set(q)-{'w','h','fps'} or any(len(v)!=1 for v in q.values()):raise ValueError('invalid stream')
    w=int(q.get('w',['640'])[0]);h=int(q.get('h',['480'])[0]);fps=float(q.get('fps',['8'])[0])
    if (w,h) not in ((640,480),(320,240)) or not .5<=fps<=8:raise ValueError('invalid dimensions or fps')
    return camera,w,h,fps

class Streams:
    def __init__(self,address,cameras=CAMERAS):
        host,port=address.rsplit(':',1)
        if host!='127.0.0.1':raise ValueError('MJPEG must bind 127.0.0.1')
        self.condition=threading.Condition();self.clients={};self.frames={};self.due={};self.closed=False
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                try:camera,w,h,fps=parameters(self.path,cameras)
                except ValueError:self.send_error(400);return
                key=(camera,w,h);token=object()
                with owner.condition:owner.clients[token]=(key,fps)
                try:
                    self.connection.settimeout(5)
                    self.send_response(200);self.send_header('Content-Type','multipart/x-mixed-replace; boundary=rvframe');self.send_header('Cache-Control','no-store');self.end_headers();previous=-1
                    while not owner.closed:
                        with owner.condition:
                            owner.condition.wait_for(lambda:owner.closed or owner.frames.get(key,(-1,None))[0]!=previous,timeout=2)
                            frame=owner.frames.get(key)
                        if not frame or frame[0]==previous:continue
                        previous,data=frame
                        self.wfile.write(b'--rvframe\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+b'\r\n\r\n'+data+b'\r\n');self.wfile.flush();time.sleep(1/fps)
                except (OSError,TimeoutError):pass
                finally:
                    with owner.condition:owner.clients.pop(token,None)
        self.server=ThreadingHTTPServer((host,int(port)),Handler);self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def pump(self,sim,renderers,snapshot):
        now=time.monotonic()
        with self.condition:
            demand={}
            for key,fps in self.clients.values():demand[key]=max(fps,demand.get(key,0))
            for key in list(self.frames):
                if key not in demand:self.frames.pop(key,None);self.due.pop(key,None)
        for key,fps in demand.items():
            if now<self.due.get(key,0):continue
            camera,w,h=key;image=sim.service({'op':'render','camera':camera,'w':w,'h':h},renderers,snapshot)
            data=base64.b64decode(image['jpeg_b64'])
            with self.condition:self.frames[key]=(self.frames.get(key,(0,None))[0]+1,data);self.condition.notify_all()
            self.due[key]=time.monotonic()+1/fps
    def close(self):
        with self.condition:self.closed=True;self.condition.notify_all()
        self.server.shutdown();self.server.server_close();self.thread.join(3)
