"""Model-exported Panda kinematics; numpy only, no copied DH table."""
import math
import ctypes
import os
from pathlib import Path
import numpy as np

HOME = np.array([0, 0, 0, -1.57079, 0, 1.57079, -0.7853])


def quat_matrix(quat):
    w, x, y, z = np.asarray(quat, dtype=float)/np.linalg.norm(quat)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def rotation(axis, angle):
    a = np.asarray(axis, dtype=float); a = a/np.linalg.norm(a)
    x, y, z = a
    k = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3)+math.sin(angle)*k+(1-math.cos(angle))*(k@k)


def rotation_error(target, actual):
    r = target@actual.T
    angle = math.acos(float(np.clip((np.trace(r)-1)/2, -1, 1)))
    skew = np.array([r[2,1]-r[1,2], r[0,2]-r[2,0], r[1,0]-r[0,1]])
    if angle < 1e-7:
        return skew*.5
    if math.pi-angle < 1e-5:
        values, vectors = np.linalg.eigh((r+np.eye(3))/2)
        axis = vectors[:, np.argmax(values)]
        if np.dot(axis, skew) < 0: axis = -axis
        return axis*angle
    return skew*(angle/(2*math.sin(angle)))


def down(yaw=0):
    return rotation([0, 0, 1], yaw)@np.diag([1., -1., -1.])


class Kinematics:
    def __init__(self, exported):
        self.chain = exported['chain']
        self.tcp = exported['tcp']
        self.limits = np.array([j['range'] for b in self.chain for j in b['joints']])
        if self.limits.shape != (7, 2): raise ValueError('expected seven hinge joints')
        self.frames = [(np.array(b['pos']), quat_matrix(b['quat']), b['joints']) for b in self.chain]
        self.tcp_pos=np.asarray(self.tcp['pos']);self.tcp_rot=quat_matrix(self.tcp['quat'])
        self.prepared=[]
        for offset,orient,joints in self.frames:
            prepared=[]
            for joint in joints:
                axis=np.asarray(joint['axis'],dtype=float);axis/=np.linalg.norm(axis)
                x,y,z=axis;k=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
                prepared.append((np.asarray(joint['pos']),axis,k,k@k,joint.get('qpos0',0)))
            self.prepared.append((offset,orient,prepared))
        self.native=None
        library=Path(__file__).with_name('libkin_native.so')
        if library.exists() and os.environ.get('RV_IK_BACKEND')!='python':
            rows=[];index=0
            for offset,orient,joints in self.prepared:
                if len(joints)>1:raise ValueError('native backend expects at most one hinge per body')
                if joints:
                    anchor,axis,_,_,q0=joints[0];joint_index=index;index+=1
                else:anchor=axis=np.zeros(3);q0=0.;joint_index=-1
                rows.append(np.r_[offset,orient.ravel(),anchor,axis,q0,joint_index])
            self.native_frames=np.ascontiguousarray(rows,dtype=np.float64)
            self.native_tcp=np.r_[self.tcp_pos,self.tcp_rot.ravel()]
            self.native=ctypes.CDLL(str(library)).rv_ik
            pointer=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
            self.native.argtypes=[pointer,ctypes.c_int,pointer,pointer,pointer,pointer,pointer,pointer]
            self.native.restype=ctypes.c_int

    def _forward(self, q, jacobian=False):
        q = np.asarray(q, dtype=float)
        if q.shape != (7,) or not np.all(np.isfinite(q)): raise ValueError('invalid q')
        p, r, axes, origins, i = np.zeros(3), np.eye(3), [], [], 0
        for offset, orient, joints in self.prepared:
            p = p+r@offset; r = r@orient
            for anchor,axis,k,k2,q0 in joints:
                origin = p+r@anchor
                if jacobian:axes.append(r@axis); origins.append(origin)
                angle=q[i]-q0
                r = r@(np.eye(3)+math.sin(angle)*k+(1-math.cos(angle))*k2)
                p = origin-r@anchor
                i += 1
        p = p+r@self.tcp_pos; r = r@self.tcp_rot
        if not jacobian: return p, r
        j = np.concatenate((np.cross(np.asarray(axes),p-np.asarray(origins)),axes),axis=1).T
        return p, r, j

    def fk(self, q):
        return self._forward(q)

    def ik(self, pos, R_target, q_seed):
        pos, target = np.asarray(pos, dtype=float), np.asarray(R_target, dtype=float)
        if pos.shape != (3,) or target.shape != (3, 3) or not np.all(np.isfinite(pos)) or not np.all(np.isfinite(target)):
            raise ValueError('invalid target pose')
        if not np.allclose(target.T@target, np.eye(3), atol=1e-6) or np.linalg.det(target)<.99:
            raise ValueError('target is not a rotation')
        seed=np.asarray(q_seed,dtype=float)
        if seed.shape!=(7,) or not np.all(np.isfinite(seed)):raise ValueError('invalid q seed')
        q = np.clip(seed, self.limits[:,0], self.limits[:,1])
        if self.native is not None:
            result=self.native(self.native_frames,len(self.native_frames),self.native_tcp,self.limits,np.ascontiguousarray(pos),np.ascontiguousarray(target),np.ascontiguousarray(seed),q)
            if result>0:self.last_iterations=result;return q
            raise RuntimeError('IK did not converge in 200 iterations (native backend)')
        for iteration in range(200):
            p, r, j = self._forward(q, True)
            pe, re = pos-p, rotation_error(target, r)
            if np.linalg.norm(pe)<.001 and np.linalg.norm(re)<math.pi/180:
                self.last_iterations = iteration+1
                return q
            e = np.r_[pe, re*.4]; j = j.copy(); j[3:] *= .4
            damping = .01
            bias=.015*(HOME-q)
            solved=np.linalg.solve(j@j.T+damping*damping*np.eye(6),np.column_stack((e,j@bias)))
            task=j.T@solved[:,0]
            dq = task+bias-j.T@solved[:,1]
            dq *= min(1., .18/max(1e-12, np.max(np.abs(dq))))
            score = np.linalg.norm(e)
            accepted = False
            for scale in (1., .5, .25, .125, .0625):
                candidate = np.clip(q+scale*dq, self.limits[:,0]+1e-5, self.limits[:,1]-1e-5)
                pp, rr = self.fk(candidate)
                if np.linalg.norm(np.r_[pos-pp, .4*rotation_error(target, rr)]) < score:
                    q = candidate; accepted = True; break
            if not accepted:
                # Task error takes precedence over the weak home null-space bias.
                q = np.clip(q+.25*task, self.limits[:,0]+1e-5, self.limits[:,1]-1e-5)
        p, r = self.fk(q)
        raise RuntimeError('IK did not converge in 200 iterations: position=%.6fm rotation=%.4fdeg' %
                           (np.linalg.norm(pos-p), np.linalg.norm(rotation_error(target,r))*180/math.pi))
