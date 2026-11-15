"""Closed-loop end-effector skills for the LIBERO demo, run on the agent side.

The simulator exposes only LIBERO's official 7-D OSC action ([dx,dy,dz,drx,dry,drz,grip], position scale
0.05 m per unit). Each control step here reads the end-effector position returned by the previous step and
sends the next delta, so the skills work the same over loopback or the board's Ethernet link.
"""
import math
import numpy as np

STEP_M=.05      # OSC position scale (m per action unit)
MAX_UNIT=.5     # at most 2.5 cm per 50 ms step (0.5 m/s)

class Robot:
    def __init__(self,link,stop=lambda:False):
        self.link=link;self.stop=stop;self.eef=None;self.grip_open=True;self.steps=0
    def _step(self,dpos,grip):
        a=list(np.clip(np.asarray(dpos)/STEP_M,-MAX_UNIT,MAX_UNIT))+[0.,0.,0.,1. if grip=='close' else -1.]
        r=self.link.call('step',actions=[a]);self.eef=np.asarray(r['eef_pos']);self.width=float(sum(abs(v) for v in r['gripper_qpos']));self.steps=r['steps']
        return r
    def sync(self,obs):self.eef=np.asarray(obs['eef_pos']);self.width=float(sum(abs(v) for v in obs['gripper_qpos']))
    def move_to(self,target,tol=.006,max_steps=120):
        g='open' if self.grip_open else 'close';target=np.asarray(target,float)
        if self.eef is None:self._step([0,0,0],g)
        for _ in range(max_steps):
            if self.stop():raise RuntimeError('stopped by operator')
            err=target-self.eef
            if np.linalg.norm(err)<tol:return True
            self._step(err*1.2,g)
        return False
    def gripper(self,close,steps=12):
        self.grip_open=not close
        for _ in range(steps):self._step([0,0,0],'close' if close else 'open')
        return self.width
    def pick(self,obj,grasp=None):
        """Top-down grasp. The fingers close along world y; objects wider than the 8 cm gripper (bowls, plates)
        are grasped by the rim wall on the +y side, others at the centre."""
        c=np.asarray(obj['center'],float);top=obj['top_z']
        if grasp is None:
            grasp=c.copy();grasp[2]=max(top-.02,c[2])
            if max(obj['size_xy'])>.07:grasp[1]+=max(obj['size_xy'])/2-.012;grasp[2]=top-.015
        self.gripper(False,6)
        if not self.move_to(grasp+[0,0,.12]):return {'ok':False,'error':'could not reach above the object'}
        if not self.move_to(grasp,tol=.008):return {'ok':False,'error':'could not reach the grasp point'}
        self.gripper(True,14)
        held_z=self.eef[2]
        self.move_to(self.eef+[0,0,.15])
        held=self.width>.004
        # Remember where the object sits relative to the fingers, so place_on can put the object (not the hand) on target.
        self.held={'offset_xy':(grasp[:2]-c[:2]).tolist(),'eef_above_bottom':float(held_z-(top-obj['height']))} if held else None
        return {'ok':held,'gripper_width_m':round(self.width,4),**({} if held else {'error':'gripper closed on nothing'})}
    def place_on(self,target):
        h=getattr(self,'held',None) or {'offset_xy':[0,0],'eef_above_bottom':.03}
        p=np.asarray(target['center'],float).copy();p[:2]+=h['offset_xy'];p[2]=target['top_z']+h['eef_above_bottom']+.015
        if not self.move_to(p+[0,0,.08]):return {'ok':False,'error':'could not reach above the target'}
        self.move_to(p,tol=.008)
        self.gripper(False,10);self.move_to(self.eef+[0,0,.12]);self.held=None
        return {'ok':True,'released_at':[round(float(v),3) for v in p]}
