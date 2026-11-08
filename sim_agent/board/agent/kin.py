"""Model-exported Panda kinematics; numpy only, no copied DH table."""
import math
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

    def _forward(self, q, jacobian=False):
        q = np.asarray(q, dtype=float)
        if q.shape != (7,) or not np.all(np.isfinite(q)): raise ValueError('invalid q')
        p, r, axes, origins, i = np.zeros(3), np.eye(3), [], [], 0
        for offset, orient, joints in self.frames:
            p = p+r@offset; r = r@orient
            for joint in joints:
                anchor = np.array(joint['pos'])
                origin = p+r@anchor
                axes.append(r@joint['axis']); origins.append(origin)
                r = r@rotation(joint['axis'], q[i]-joint.get('qpos0', 0))
                p = origin-r@anchor
                i += 1
        p = p+r@self.tcp['pos']; r = r@quat_matrix(self.tcp['quat'])
        if not jacobian: return p, r
        j = np.array([np.r_[np.cross(a, p-o), a] for a, o in zip(axes, origins)]).T
        return p, r, j

    def fk(self, q):
        return self._forward(q)

    def ik(self, pos, R_target, q_seed):
        pos, target = np.asarray(pos, dtype=float), np.asarray(R_target, dtype=float)
        if pos.shape != (3,) or target.shape != (3, 3) or not np.all(np.isfinite(pos)) or not np.all(np.isfinite(target)):
            raise ValueError('invalid target pose')
        if not np.allclose(target.T@target, np.eye(3), atol=1e-6) or np.linalg.det(target)<.99:
            raise ValueError('target is not a rotation')
        q = np.clip(np.asarray(q_seed, dtype=float), self.limits[:,0], self.limits[:,1])
        for iteration in range(200):
            p, r, j = self._forward(q, True)
            pe, re = pos-p, rotation_error(target, r)
            if np.linalg.norm(pe)<.001 and np.linalg.norm(re)<math.pi/180:
                self.last_iterations = iteration+1
                return q
            e = np.r_[pe, re*.4]; j = j.copy(); j[3:] *= .4
            damping = .01
            inv = j.T@np.linalg.solve(j@j.T+damping*damping*np.eye(6), np.eye(6))
            dq = inv@e + (np.eye(7)-inv@j)@(.015*(HOME-q))
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
                q = np.clip(q+.25*(inv@e), self.limits[:,0]+1e-5, self.limits[:,1]-1e-5)
        p, r = self.fk(q)
        raise RuntimeError('IK did not converge in 200 iterations: position=%.6fm rotation=%.4fdeg' %
                           (np.linalg.norm(pos-p), np.linalg.norm(rotation_error(target,r))*180/math.pi))
