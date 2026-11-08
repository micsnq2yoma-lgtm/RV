"""Local trajectory datagrams and the board-side TCP requester (protocol v1.1)."""
import base64
import json
import os
from pathlib import Path
import socket
import struct
import time
import uuid

REQUEST = struct.Struct('<4sI9d')
REPLY = struct.Struct('<4sIII16d')


class RTClient:
    def __init__(self, path='/tmp/rt_ctl.sock'):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind('\0rv-agent-'+str(os.getpid())+'-'+uuid.uuid4().hex)
        self.sock.settimeout(2)
        self.path = path

    def call(self, op=2, q=None, grip=0., duration=.5):
        self.sock.sendto(REQUEST.pack(b'RVT1', op, *(q if q is not None else [0.]*7), grip, duration), self.path)
        raw = self.sock.recv(145)
        if len(raw)!=REPLY.size: raise RuntimeError('bad RT reply length')
        magic, status, active, generation, *values = REPLY.unpack(raw)
        if magic!=b'RVR1' or status: raise RuntimeError('RT reply status=%d' % status)
        return dict(active=bool(active), generation=generation, q=values[:7], q_des=values[7:14],
                    gripper=values[14], gripper_des=values[15])

    def segment(self, q, grip, duration):
        return self.call(1, q, grip, duration)

    def cancel(self):
        return self.call(3)

    def close(self):
        self.sock.close()


class SimClient:
    def __init__(self, timeout=60):
        self.listener=socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self.listener.bind(('0.0.0.0',15002)); self.listener.listen(1); self.listener.settimeout(timeout)
        print(json.dumps({'tcp_listening':15002}),flush=True)
        self.sock,_=self.listener.accept(); self.sock.settimeout(30)
        self.stream=self.sock.makefile('rb'); self.seq=0

    def call(self, op, **args):
        ident=self.seq; self.seq+=1
        self.sock.sendall((json.dumps(dict(id=ident,op=op,**args))+'\n').encode())
        line=self.stream.readline(4*1024*1024)
        if not line.endswith(b'\n'):raise RuntimeError('truncated/oversized simulation response')
        reply=json.loads(line)
        if reply.get('id')!=ident or 'error' in reply:raise RuntimeError('simulation error: '+str(reply))
        return reply

    def photo(self, path, camera='top'):
        reply=self.call('render',camera=camera,w=640,h=480)
        data=base64.b64decode(reply['jpeg_b64'],validate=True)
        Path(path).parent.mkdir(parents=True,exist_ok=True);Path(path).write_bytes(data)
        return len(data)

    def close(self):
        self.stream.close();self.sock.close();self.listener.close()
