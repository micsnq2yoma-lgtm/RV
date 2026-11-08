"""Local Unix-socket broker: simulation calls only, never shell execution."""
import json,socket
PATH='/tmp/rv014/sim.sock'
class LocalSim:
    def __init__(self,path=PATH):self.path=path
    def call(self,op,**args):
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(40);s.connect(self.path);s.sendall((json.dumps({'op':op,**args})+'\n').encode())
            with s.makefile('rb') as f:raw=f.readline(8*1024*1024)
        result=json.loads(raw)
        if 'error' in result:raise RuntimeError(result['error'])
        return result
