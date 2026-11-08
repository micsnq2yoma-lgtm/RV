"""Run only against the simulation controller: malformed datagrams and replacement continuity."""
import time,json,math
import numpy as np
from transport import REQUEST,REPLY


def check_interfaces(skills):
    rt=skills.rt;initial=rt.call();q=np.array(initial['q_des']);grip=float(np.clip(initial['gripper_des'],0,.08))
    for raw in [b'bad',REQUEST.pack(b'FAIL',2,*([0.]*9)),REQUEST.pack(b'RVT1',1,math.nan,*([0.]*6),grip,1.)]:
        rt.sock.sendto(raw,rt.path);reply=REPLY.unpack(rt.sock.recv(145))
        assert reply[1]==1,'malformed request was accepted'
    goal=q.copy();goal[0]=float(np.clip(goal[0]+.1,skills.kin.limits[0,0],skills.kin.limits[0,1]))
    first=rt.segment(goal,grip,1.);time.sleep(.3);before=rt.call()
    rt.segment(q,grip,1.);after=rt.call()
    jump=float(np.max(np.abs(np.array(before['q_des'])-after['q_des'])))
    assert jump<.01,'replacement discontinuity'
    assert after['generation']>first['generation'] and after['active']
    time.sleep(1.1);final=rt.call()
    assert not final['active'] and np.max(np.abs(np.array(final['q_des'])-q))<1e-10
    try:skills.sim.call('not_an_operation')
    except RuntimeError as e:assert 'unknown op' in str(e)
    else:raise AssertionError('unknown TCP operation accepted')
    print(json.dumps({'interface_tests_passed':True,'replacement_jump_rad':jump}),flush=True)
