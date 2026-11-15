"""Record one web page (the workbench) with headless Chrome's DevTools screencast -> MP4.

Only the page is captured, never the desktop. Runs until --stop-file appears or --seconds elapse.
usage: python record_page.py URL OUT.mp4 [--size 1920x1080] [--fps 10] [--stop-file F] [--seconds 900]
"""
import argparse,asyncio,base64,json,os,subprocess,tempfile,time,urllib.request
from pathlib import Path
import websockets
CHROME=r'C:\Program Files\Google\Chrome\Application\chrome.exe'
FFMPEG=r'E:\Applaction\Miniconda3\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe'

async def main(a):
    w,h=map(int,a.size.split('x'));port=9400+os.getpid()%500;prof=tempfile.mkdtemp(prefix='rvrec-')
    chrome=subprocess.Popen([CHROME,'--headless=new','--disable-gpu','--hide-scrollbars',f'--remote-debugging-port={port}',f'--user-data-dir={prof}',f'--window-size={w},{h}','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    ff=subprocess.Popen([FFMPEG,'-hide_banner','-loglevel','error','-f','image2pipe','-framerate',str(a.fps),'-i','-','-vf',f'scale={w}:{h}','-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-y',a.out],stdin=subprocess.PIPE)
    try:
        http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(50):
            try:tabs=json.loads(http.open(f'http://127.0.0.1:{port}/json',timeout=1).read());break
            except OSError:time.sleep(.2)
        url=next(t['webSocketDebuggerUrl'] for t in tabs if t['type']=='page')
        async with websockets.connect(url,max_size=64*1024*1024) as ws:
            n=0;pending={}
            async def send(method,**params):
                nonlocal n;n+=1;await ws.send(json.dumps({'id':n,'method':method,'params':params}));return n
            await send('Emulation.setDeviceMetricsOverride',width=w,height=h,deviceScaleFactor=1,mobile=False)
            await send('Page.enable');await send('Page.navigate',url=a.url)
            await send('Page.startScreencast',format='jpeg',quality=85,maxWidth=w,maxHeight=h,everyNthFrame=1)
            latest=None;t0=time.monotonic();frames=0;next_t=t0
            while time.monotonic()-t0<a.seconds and not (a.stop_file and Path(a.stop_file).exists()):
                try:
                    m=json.loads(await asyncio.wait_for(ws.recv(),timeout=max(.01,next_t-time.monotonic())))
                    if m.get('method')=='Page.screencastFrame':
                        latest=base64.b64decode(m['params']['data']);await send('Page.screencastFrameAck',sessionId=m['params']['sessionId'])
                except asyncio.TimeoutError:pass
                # Constant frame rate: repeat the latest frame when the page is static.
                while latest is not None and time.monotonic()>=next_t:
                    ff.stdin.write(latest);frames+=1;next_t+=1/a.fps
            print(json.dumps({'frames':frames,'seconds':round(time.monotonic()-t0,1)}),flush=True)
    finally:
        ff.stdin.close();ff.wait(60);chrome.kill()

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('url');ap.add_argument('out');ap.add_argument('--size',default='1920x1080');ap.add_argument('--fps',type=int,default=10)
    ap.add_argument('--stop-file');ap.add_argument('--seconds',type=float,default=900)
    asyncio.run(main(ap.parse_args()))
