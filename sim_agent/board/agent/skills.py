"""Simulation-only skills. Ground truth is used explicitly for S3."""
import json
import time
import numpy as np
from kin import Kinematics, HOME, down


class Stopped(RuntimeError):
    """The operator pressed stop; the current motion was cancelled in place."""


class Skills:
    def __init__(self, sim, rt):
        self.sim,self.rt=sim,rt
        self.kin=Kinematics(sim.call('kinematics'))
        self.table_z=sim.call('hello')['table_z']
        self.yaw=0.
        self.stop_check=None

    def _stopping(self):
        if self.stop_check is not None and self.stop_check():
            self.rt.cancel()
            raise Stopped('stopped by operator')

    def joints(self, q, grip=None, minimum=.5, settle=.25):
        self._stopping()
        state=self.rt.call()
        q=np.asarray(q,dtype=float)
        if q.shape!=(7,) or not np.all(np.isfinite(q)):raise ValueError('invalid q')
        duration=max(minimum,float(np.max(np.abs(q-np.array(state['q_des']))))/.5)
        if grip is None:grip=float(np.clip(state['gripper_des'],0,.08))
        response=self.rt.segment(q,grip,duration)
        deadline=time.monotonic()+duration+5
        while time.monotonic()<deadline:
            time.sleep(.05);self._stopping();state=self.rt.call()
            if state['generation']!=response['generation']:raise RuntimeError('trajectory superseded or reset')
            if not state['active']:
                time.sleep(settle)
                return self.rt.call()
        raise TimeoutError('trajectory completion timeout')

    def home(self, grip=.08):
        return self.joints(HOME,grip)

    def gripper(self, opened):
        return self.joints(self.rt.call()['q_des'],.08 if opened else 0.,minimum=.8)

    def move_to(self, x,y,z,yaw=0,settle=.25):
        start=time.perf_counter()
        q=self.kin.ik([x,y,z],down(yaw),self.rt.call()['q'])
        print(json.dumps({'ik_seconds':time.perf_counter()-start,'iterations':self.kin.last_iterations,'target':[x,y,z]}),flush=True)
        self.yaw=yaw
        return self.joints(q,settle=settle)

    def pick(self,x,y,yaw=0,z=None):
        z=self.table_z+.023 if z is None else z
        self.gripper(True)
        self.move_to(x,y,z+.10,yaw)
        self.move_to(x,y,z,yaw)
        self.gripper(False)
        time.sleep(.5)
        width=self.rt.call()['gripper']
        print(json.dumps({'pick_width':width}),flush=True)
        if not .03<=width<=.05:
            # Open and lift straight up first, so the way home does not sweep through a neighbouring tower.
            self.gripper(True);self.move_to(x,y,z+.10,yaw)
            return False
        self.move_to(x,y,z+.10,yaw)
        return .03<=self.rt.call()['gripper']<=.05

    def place(self,x,y,z):
        # z is the requested cube-center height; TCP is 3mm above cube center.
        self.move_to(x,y,z+.103,self.yaw)
        # Let the arm settle before releasing: release-time jitter along x was ~9 mm (report 015).
        self.move_to(x,y,z+.003,self.yaw,settle=.6)
        self.gripper(True)
        self.move_to(x,y,z+.103,self.yaw)

    def objects(self):
        return {o['name']:o for o in self.sim.call('objects')['objects']}
