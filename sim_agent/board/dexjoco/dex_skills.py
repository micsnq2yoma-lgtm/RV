"""Skill execution for the DexJoCo bimanual demo, run on the agent side.

A skill is a short segment cut from one human teleoperation demo (flange pose + 16 Allegro joint targets per step,
30 Hz), stored relative to a reference: an object seen by perception (its centre / top, optionally its yaw), a peg
(its xy and the top of whatever is stacked on it) or the world. At run time the same reference is measured in the
new, randomised scene and the segment is moved there (translation, plus rotation about z when the skill uses yaw).
A lead-in path joins the arm's current command to the first frame. The skill library is built offline on the PC
(dexjoco_build_skills.py) and copied to the board; it is not committed (derived from the DexJoCo dataset).
"""
import json,math
import numpy as np

# ---------- geometry ----------
def qmul(a,b):
    w1,x1,y1,z1=a;w2,x2,y2,z2=b
    return np.array([w1*w2-x1*x2-y1*y2-z1*z2,w1*x2+x1*w2+y1*z2-z1*y2,w1*y2-x1*z2+y1*w2+z1*x2,w1*z2+x1*y2-y1*x2+z1*w2])
def qyaw(y):return np.array([math.cos(y/2),0,0,math.sin(y/2)])
def Rz(y):c,s=math.cos(y),math.sin(y);return np.array([[c,-s,0],[s,c,0],[0,0,1]])
def slerp(a,b,t):
    a=np.asarray(a,float);b=np.asarray(b,float);d=float(np.dot(a,b))
    if d<0:b=-b;d=-d
    if d>.9995:q=a+t*(b-a);return q/np.linalg.norm(q)
    th=math.acos(d);return (math.sin((1-t)*th)*a+math.sin(t*th)*b)/math.sin(th)

def qmat(q):
    w,x,y,z=np.asarray(q,float)/np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
def held_offset(flange,center):
    """Where a held object sits in the flange frame (flange = [x,y,z,qw,qx,qy,qz])."""
    return (qmat(flange[3:7]).T@(np.asarray(center,float)-np.asarray(flange[:3],float))).tolist()

def to_rel(frames,ref):
    """World frames (N,23) -> relative to ref {'p':[3],'yaw':rad}."""
    F=np.asarray(frames,float).copy();p=np.asarray(ref['p'],float);R=Rz(-ref['yaw']);q=qyaw(-ref['yaw'])
    F[:,:3]=(F[:,:3]-p)@R.T
    for i in range(len(F)):F[i,3:7]=qmul(q,F[i,3:7])
    return F
def to_world(rel,ref):
    F=np.asarray(rel,float).copy();p=np.asarray(ref['p'],float);R=Rz(ref['yaw']);q=qyaw(ref['yaw'])
    F[:,:3]=F[:,:3]@R.T+p
    for i in range(len(F)):F[i,3:7]=qmul(q,F[i,3:7])
    return F

# ---------- references measured from the perceived scene ----------
# Fixtures that never move: measured once at the start of an episode, before a hand can hide them.
STATIC=('peg_A','peg_B','peg_C','base','microwave','start_button','stand','logo')
def ref_from_scene(spec,sc,exclude=(),arms=None):
    k=spec['kind']
    if k=='world':return {'p':[0,0,0],'yaw':0.}
    if k=='flange':   # the other hand's flange (an object it holds rigidly), from the arm state in the observation
        if not arms:raise ValueError('flange reference needs the arm state')
        return {'p':list(arms[spec['arm']]['flange'][:3]),'yaw':0.}
    if k=='object':
        o=sc.get(spec['name'])
        if o is None:raise ValueError('看不到 '+spec['name'])
        if spec.get('anchor')=='top_center':return {'p':list(o['top_center']),'yaw':0.}
        z=o['top_z'] if spec.get('z','top')=='top' else o['center'][2]
        return {'p':[o['center'][0],o['center'][1],z],'yaw':math.radians(o['yaw_deg']) if spec.get('yaw') else 0.}
    if k=='peg':   # xy of the peg, z of the highest disk resting on it (or of the base)
        peg=sc.get(spec['name'])
        if peg is None:raise ValueError('看不到 '+spec['name'])
        xy=np.asarray(peg['center'][:2]);top=sc['base']['top_z'] if 'base' in sc else peg['bottom_z']
        for n,o in sc.items():
            if n.startswith('disk_') and n not in exclude and np.linalg.norm(np.asarray(o['center'][:2])-xy)<.04:top=max(top,o['top_z'])
        return {'p':[float(xy[0]),float(xy[1]),float(top)],'yaw':0.}
    raise ValueError('unknown ref '+k)

def stack_on(peg,sc,exclude=()):
    """Disks on a peg, bottom to top, from perceived positions (used for the agent's observation)."""
    xy=np.asarray(sc[peg]['center'][:2])
    ds=[(o['center'][2],n) for n,o in sc.items() if n.startswith('disk_') and n not in exclude and np.linalg.norm(np.asarray(o['center'][:2])-xy)<.04]
    return [n for _,n in sorted(ds)]

# ---------- execution ----------
# Extra flexion added to the demo's hand targets while an object is held (Allegro order: 3 fingers x [abd, f1, f2, f3],
# then thumb [rot, f1, f2, f3]). The demo grip is often just enough for the demo's exact contact; this keeps a margin.
SQUEEZE=np.array([0,.15,.15,.15]*3+[0,0,.15,.15])

class Arms:
    CHUNK=45
    def __init__(self,link,stop=lambda:False):
        self.link=link;self.stop=stop;self.cmd={};self.steps=0;self.holding={}
    def sync(self,reply):
        for a in ('right','left'):self.cmd[a]=np.asarray(reply['arms'][a]['cmd'],float)
        self.steps=reply.get('steps',reply.get('step',self.steps))
    def send(self,seq):
        for i in range(0,len(seq),self.CHUNK):
            if self.stop():raise RuntimeError('stopped by operator')
            chunk=[{a:[round(float(x),5) for x in v] for a,v in f.items()} for f in seq[i:i+self.CHUNK]]
            self.sync(self.link.call('step',cmds=chunk))
    def lead_in(self,targets,speed=.35,lift=.04):
        """Frames moving each arm from its current command to targets[arm] (23-vectors), lifting over obstacles."""
        paths={}
        for a,t in targets.items():
            c=self.cmd[a];t=np.asarray(t,float);pts=[c[:3]]
            if np.linalg.norm(t[:2]-c[:2])>.08:   # go up, across, then down
                z=max(c[2],t[2])+lift;pts+= [np.r_[c[:2],z],np.r_[t[:2],z]]
            pts.append(t[:3]);L=sum(np.linalg.norm(pts[i+1]-pts[i]) for i in range(len(pts)-1))
            n=max(12,int(L/speed*30));paths[a]=(pts,L,n,c,t)
        n=max(p[2] for p in paths.values());seq=[{} for _ in range(n)]
        for a,(pts,L,_,c,t) in paths.items():
            seg=[np.linalg.norm(pts[i+1]-pts[i]) for i in range(len(pts)-1)]
            for k in range(n):
                s=0.5-0.5*math.cos(math.pi*(k+1)/n)   # smooth start and stop
                d=s*L;i=0
                while i<len(seg)-1 and d>seg[i]:d-=seg[i];i+=1
                p=pts[i]+(pts[i+1]-pts[i])*(d/seg[i] if seg[i]>1e-9 else 1)
                seq[k][a]=np.r_[p,slerp(c[3:7],t[3:7],s),c[7:]+(t[7:]-c[7:])*s]
        return seq
    @staticmethod
    def release_index(F):
        """First frame where the hand opens clearly (sum of joint targets drops 1.5 rad below the start)."""
        s0=np.asarray(F)[0,7:].sum()
        for i,f in enumerate(F):
            if np.sum(f[7:])<s0-1.5:return i
        return None
    def play(self,skill,refs,held=None,correct=None,offset=None):
        """held: {arm: offset of the held object in the flange frame, measured now}. The skill stores the offset seen in
        the demo; each frame is shifted so the object, not the hand, follows the demo's path relative to the target."""
        world={a:to_world(skill['frames'][a],refs[a]) for a in skill['frames']}
        for a,v in (offset or {}).items():world[a][:,:3]+=np.asarray(v,float)
        speed=.15 if held else .35   # carry slowly: Allegro pinch grasps slip when swung fast
        for a,o_r in (held or {}).items():
            o_d=skill.get('held_offset',{}).get(a)
            if o_d is None or a not in world:continue
            dv=np.asarray(o_d)-np.asarray(o_r);n=np.linalg.norm(dv)
            if n>.06:dv*=.06/n
            F=world[a]
            for i in range(len(F)):F[i,:3]+=qmat(F[i,3:7])@dv
        for a,F in world.items():
            if a in self.holding:   # squeeze until the demo opens the hand (hand sum drops clearly below the start)
                s0=F[0,7:].sum()
                for i in range(len(F)):
                    if F[i,7:].sum()<s0-1.5:self.holding.pop(a,None);break
                    F[i,7:]+=SQUEEZE
        self.send(self.lead_in({a:F[0] for a,F in world.items()},speed=speed))
        n=max(len(F) for F in world.values())
        seq=lambda k0,k1:[{a:F[min(k,len(F)-1)] for a,F in world.items()} for k in range(k0,k1)]
        cks=[c for c in skill.get('check_index',[]) if 0<c<n] if correct else []
        k0=0
        for j,ck in enumerate(cks):
            # Closed loop on the way down: look again and move the rest of the path by the held object's measured error.
            self.send(seq(k0,ck));self.send([{}]*6)
            for a,dv in (correct(skill,refs,j) or {}).items():
                dv=np.asarray(dv,float);m=np.linalg.norm(dv)
                if m>.05:dv*=.05/m
                world[a][ck:,:3]+=dv
            k0=ck
        self.send(seq(k0,n))
        if skill.get('held'):   # after a release: settle, then lift the empty hand straight up
            self.send([{}]*12)
            for a in skill['held']:self.move_rel(a,[0,0,.08],steps=25)
    def move_to(self,arm,flange_pos,steps=None,speed=.12):
        """Straight move of one flange to a position, keeping its orientation and hand."""
        c=self.cmd[arm];t=c.copy();t[:3]=flange_pos;d=np.linalg.norm(t[:3]-c[:3])
        n=steps or max(8,int(d/speed*30))
        self.send([{arm:c+(t-c)*(0.5-0.5*math.cos(math.pi*(k+1)/n))} for k in range(n)])
    def servo_place(self,arm,look,obj,xy,z_align,z_release,open_hand,tol=.003,iters=8,spiral=0.):
        """Visual-servo placement of a held object (no demo replay): carry it above xy at z_align, correct with fresh
        observations until the object's measured centre is within tol, lower it to z_release, open the hand, lift.
        look() -> (obs, scene). Heights refer to the object's centre. Returns the log of measured errors."""
        obs,sc=look()
        if obj not in sc:raise ValueError('看不到手里的 '+obj)
        off=np.asarray(sc[obj]['center'])-np.asarray(obs['arms'][arm]['flange'][:3])   # object relative to flange (world axes)
        goal=np.r_[xy,z_align]
        self.send(self.lead_in({arm:np.r_[goal-off,self.cmd[arm][3:]]},speed=.15));self.send([{}]*10)
        log=[]
        for _ in range(iters):
            obs,sc=look()
            if obj not in sc:raise ValueError('看不到手里的 '+obj)
            e=goal-np.asarray(sc[obj]['center']);log.append([round(float(v),4) for v in e])
            if np.linalg.norm(e[:2])<tol and abs(e[2])<.02:break
            self.move_to(arm,self.cmd[arm][:3]+e,steps=20);self.send([{}]*15)
        self.move_to(arm,self.cmd[arm][:3]+[0,0,z_release-z_align],speed=.06);self.send([{}]*10)
        if spiral:   # search for the hole: widening circles while pressing down a little
            c0=self.cmd[arm].copy();seq=[]
            for k in range(60):
                r=spiral*min(1,(k+1)/30);a=k*2*math.pi/15;t=c0.copy();t[:3]+=[r*math.cos(a),r*math.sin(a),-.012*(k+1)/60];seq.append({arm:t})
            self.send(seq);self.send([{arm:c0+[0,0,-.012]+[0]*20}]*8)
        c=self.cmd[arm];t=c.copy();t[7:]=open_hand
        self.send([{arm:c+(t-c)*((k+1)/20)} for k in range(20)]);self.send([{}]*10)
        self.holding.pop(arm,None);self.move_rel(arm,[0,0,.10],steps=30)
        return log
    def grip(self,arm,steps=15):
        """After a pick: close a little more and remember that this arm holds something."""
        c=self.cmd[arm];t=c.copy();t[7:]+=SQUEEZE;self.holding[arm]=True
        self.send([{arm:c+(t-c)*((k+1)/steps)} for k in range(steps)])
    def move_rel(self,arm,dpos,steps=20,hand=None):
        c=self.cmd[arm];t=c.copy();t[:3]+=dpos
        if hand is not None:t[7:]=hand
        self.send([{arm:c+(t-c)*((k+1)/steps)} for k in range(steps)])
    def home(self,arm,pose,steps=None):
        self.send(self.lead_in({arm:np.asarray(pose,float)}))

def check_points(F):
    """Frames at which to re-check a placement: while the hand descends, 7 cm and 3.5 cm above where it opens."""
    ri=Arms.release_index(F)
    if not ri:return []
    zr=F[ri][2];out=[]
    for h in (.07,.035):
        i=next((i for i in range(ri) if all(F[k][2]<zr+h for k in range(i,ri))),None)
        if i and i>5 and (not out or i>out[-1]+5):out.append(i)
    return out

def check_error(skill,refs,sc,j=0):
    """World-frame xy error of each held object against where the demo had it at check point j."""
    out={}
    for a,obj in skill.get('held',{}).items():
        rel=(skill.get('check_rel',{}).get(a) or [None]*9)[j]
        if rel is None or obj not in sc:continue
        r=refs[a];want=np.asarray(r['p'])+Rz(r['yaw'])@np.asarray(rel)
        e=want-np.asarray(sc[obj]['center']);e[2]=0;out[a]=e
    return out

def load_library(path):
    with open(path,encoding='utf-8') as f:return json.load(f)
