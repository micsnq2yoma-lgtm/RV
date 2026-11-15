"""Screenshot a live page with headless Chrome over the DevTools protocol (real time, streams allowed).

usage: python shoot.py URL OUT.png [--size 1920x1080] [--wait 8] [--dark] [--js "expr"]
"""
import argparse,asyncio,base64,json,os,subprocess,tempfile,time,urllib.request
import websockets
CHROME=r'C:\Program Files\Google\Chrome\Application\chrome.exe'

async def main(a):
    w,h=map(int,a.size.split('x'));port=9300+os.getpid()%500
    prof=tempfile.mkdtemp(prefix='rvshot-')
    p=subprocess.Popen([CHROME,'--headless=new','--disable-gpu','--hide-scrollbars',f'--remote-debugging-port={port}',f'--user-data-dir={prof}',f'--window-size={w},{h}','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(50):
            try:tabs=json.loads(http.open(f'http://127.0.0.1:{port}/json',timeout=1).read());break
            except OSError:time.sleep(.2)
        ws_url=next(t['webSocketDebuggerUrl'] for t in tabs if t['type']=='page')
        async with websockets.connect(ws_url,max_size=64*1024*1024) as ws:
            n=0
            async def cmd(method,**params):
                nonlocal n;n+=1;me=n;await ws.send(json.dumps({'id':me,'method':method,'params':params}))
                while True:
                    m=json.loads(await ws.recv())
                    if m.get('id')==me:return m.get('result',{})
            await cmd('Emulation.setDeviceMetricsOverride',width=w,height=h,deviceScaleFactor=1,mobile=False)
            if a.dark:await cmd('Emulation.setEmulatedMedia',features=[{'name':'prefers-color-scheme','value':'dark'}])
            await cmd('Page.navigate',url=a.url);await asyncio.sleep(a.wait)
            for expr in a.js or []:
                r=await cmd('Runtime.evaluate',expression=expr,awaitPromise=True,returnByValue=True);await asyncio.sleep(a.after)
                if 'exceptionDetails' in r:print('js error',r['exceptionDetails'].get('text'))
            shot=await cmd('Page.captureScreenshot',format='png',captureBeyondViewport=False)
            open(a.out,'wb').write(base64.b64decode(shot['data']));print('saved',a.out)
    finally:p.kill()

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('url');ap.add_argument('out');ap.add_argument('--size',default='1920x1080')
    ap.add_argument('--wait',type=float,default=8);ap.add_argument('--after',type=float,default=1.5);ap.add_argument('--dark',action='store_true');ap.add_argument('--js',action='append')
    asyncio.run(main(ap.parse_args()))
