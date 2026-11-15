"""Board side of protocol nav-1: listen on TCP 15003, the PC simulator connects in (no firewall change)."""
import json,socket,threading

class NavLink:
    def __init__(self,port=15003,timeout=3600):
        self.listener=socket.socket();self.listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self.listener.bind(('0.0.0.0',port));self.listener.listen(1);self.listener.settimeout(timeout)
        print(json.dumps({'nav_listening':port}),flush=True)
        self.sock,_=self.listener.accept();self.sock.settimeout(20)
        self.stream=self.sock.makefile('rb');self.seq=0;self.lock=threading.Lock()
    def call(self,op,**args):
        with self.lock:
            ident=self.seq;self.seq+=1
            self.sock.sendall((json.dumps(dict(id=ident,op=op,**args))+'\n').encode())
            line=self.stream.readline(4*1024*1024)
        if not line.endswith(b'\n'):raise RuntimeError('truncated simulator reply')
        reply=json.loads(line)
        if reply.get('id')!=ident or 'error' in reply:raise RuntimeError('simulator error: '+str(reply.get('error',reply)))
        return reply
    def close(self):
        for x in (self.stream,self.sock,self.listener):
            try:x.close()
            except OSError:pass
