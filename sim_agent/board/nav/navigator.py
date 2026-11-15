"""Board-side path planning (A* on the perceived occupancy grid) and path following (pure pursuit on odometry).

Odometry is integrated here from wheel encoder angles; every ~1 m the robot stops and re-localises with the
top camera, and checks whether a new obstacle now blocks the rest of the path.
"""
import heapq,math,time
import numpy as np
from nav_perception import X0,Y0,CELL

ROBOT_R=.26;MARGIN=.03;V_MAX=.3;LOOKAHEAD=.35;GOAL_TOL=.10;RELOCALISE_EVERY=.7;RELOCALISE_S=2.5

def inflate(grid,radius):
    r=int(math.ceil(radius/CELL));out=grid.copy();ys,xs=np.nonzero(grid)
    yy,xx=np.mgrid[-r:r+1,-r:r+1];disk=(yy**2+xx**2)<=r*r
    for dy,dx in zip(*np.nonzero(disk)):
        dy-=r;dx-=r;y=np.clip(ys+dy,0,grid.shape[0]-1);x=np.clip(xs+dx,0,grid.shape[1]-1);out[y,x]=True
    return out

def clearance(grid,x,y,reach=.8):
    """Distance (m) from (x,y) to the nearest occupied cell edge."""
    j,i=cell((x,y));r=int(reach/CELL);sub=grid[max(0,j-r):j+r+1,max(0,i-r):i+r+1];js,is_=np.nonzero(sub)
    if not len(js):return reach
    px=X0+(is_+max(0,i-r)+.5)*CELL;py=Y0+(js+max(0,j-r)+.5)*CELL
    return float(np.min(np.hypot(px-x,py-y)))-CELL/2

def cell(p):return int((p[1]-Y0)/CELL),int((p[0]-X0)/CELL)
def point(c):return (X0+(c[1]+.5)*CELL,Y0+(c[0]+.5)*CELL)

def zone_mask(shape,zones,names,pad):
    m=np.zeros(shape,bool)
    for n in names:
        if n not in zones:continue
        (cx,cy),(hx,hy)=zones[n]['center'],zones[n]['half']
        j0,i0=cell((cx-hx-pad,cy-hy-pad));j1,i1=cell((cx+hx+pad,cy+hy+pad))
        m[max(0,j0):j1+1,max(0,i0):i1+1]=True
    return m

def plan(grid,start,goal,zones=None,avoid=()):
    """A* on the inflated grid. Returns (waypoints, length) or raises ValueError with a reason."""
    blocked=inflate(grid,ROBOT_R+MARGIN)
    if avoid:blocked|=zone_mask(grid.shape,zones or {},avoid,ROBOT_R)
    s,g=cell(start),cell(goal)
    # The robot's own cell and the goal cell may sit in inflation near walls/zones; clear a small disk around them.
    for c in (s,g):
        yy,xx=np.ogrid[:grid.shape[0],:grid.shape[1]];near=(yy-c[0])**2+(xx-c[1])**2<=4;blocked[near&~inflate(grid,ROBOT_R*.6)]=False
    if blocked[g]:raise ValueError('goal is inside an obstacle or an avoided zone')
    if blocked[s]:raise ValueError('robot start cell is blocked')
    openq=[(0,s)];came={s:None};cost={s:0.};steps=((0,1,1),(1,0,1),(0,-1,1),(-1,0,1),(1,1,1.414),(1,-1,1.414),(-1,1,1.414),(-1,-1,1.414))
    while openq:
        _,c=heapq.heappop(openq)
        if c==g:break
        for dj,di,w in steps:
            n=(c[0]+dj,c[1]+di)
            if not (0<=n[0]<grid.shape[0] and 0<=n[1]<grid.shape[1]) or blocked[n]:continue
            if dj and di and (blocked[c[0]+dj,c[1]] or blocked[c[0],c[1]+di]):continue
            nc=cost[c]+w
            if nc<cost.get(n,1e9):cost[n]=nc;came[n]=c;heapq.heappush(openq,(nc+math.hypot(g[0]-n[0],g[1]-n[1]),n))
    if g not in came:raise ValueError('no collision-free path'+(' while avoiding '+','.join(avoid) if avoid else ''))
    cells=[];c=g
    while c is not None:cells.append(c);c=came[c]
    cells.reverse()
    def clear(a,b):
        n=int(max(abs(a[0]-b[0]),abs(a[1]-b[1])))+1
        return all(not blocked[int(round(a[0]+(b[0]-a[0])*k/n)),int(round(a[1]+(b[1]-a[1])*k/n))] for k in range(n+1))
    keep=[cells[0]];i=0
    while i<len(cells)-1:
        j=len(cells)-1
        while j>i+1 and not clear(cells[i],cells[j]):j-=1
        keep.append(cells[j]);i=j
    pts=[start]+[point(c) for c in keep[1:-1]]+[goal]
    return pts,sum(math.dist(a,b) for a,b in zip(pts,pts[1:]))

class Odometry:
    def __init__(self,r,track):self.r=r;self.track=track;self.pose=None;self.last=None
    def fix(self,pose):self.pose=[pose['x'],pose['y'],pose['yaw']]
    def update(self,odom):
        if self.last is not None and self.pose is not None:
            dl=(odom['wl']-self.last['wl'])*self.r;dr=(odom['wr']-self.last['wr'])*self.r;ds=(dl+dr)/2;dth=(dr-dl)/self.track
            x,y,th=self.pose;self.pose=[x+ds*math.cos(th+dth/2),y+ds*math.sin(th+dth/2),th+dth]
        self.last=odom;return self.pose

class Driver:
    def __init__(self,link,perception,hello,emit=lambda e:None,stop=lambda:False):
        self.link=link;self.p=perception;self.emit=emit;self.stop=stop
        self.r=hello['wheel_radius'];self.track=hello['track_width'];self.wmax=min(hello['max_wheel_speed'],10.)
        self.odom=Odometry(self.r,self.track);self.scene=None
    def observe(self):
        self.drive(0,0);time.sleep(.25)
        began=time.perf_counter();scene=self.p.observe(self.link.call('render',camera='top',w=640,h=480))
        if scene['robot']:self.odom.update(self.link.call('odom'));self.odom.fix(scene['robot'])
        scene['seconds']=time.perf_counter()-began;self.scene=scene;return scene
    def drive(self,v,w):
        wl=(v-w*self.track/2)/self.r;wr=(v+w*self.track/2)/self.r;k=max(1.,abs(wl)/self.wmax,abs(wr)/self.wmax)
        self.link.call('drive',wl=wl/k,wr=wr/k)
    def follow(self,path,grid,goal_tol=GOAL_TOL,timeout=90.):
        """Pure pursuit along path planned on grid. Returns dict(ok, reason, travelled)."""
        known=inflate(grid,2*CELL)   # occupancy seen at planning time, with a 2-cell tolerance for re-observation jitter
        self.odom.update(self.link.call('odom'));since_fix=0.;travelled=0.;i=1;t0=time.monotonic();prev=list(self.odom.pose)
        x,y,th=self.odom.pose
        if clearance(grid,x,y)<.27:
            # Too close to turn in place (half-diagonal 0.25 m): first move 0.25 m straight, forward or back,
            # whichever direction gains more clearance.
            fwd=clearance(grid,x+.25*math.cos(th),y+.25*math.sin(th));back=clearance(grid,x-.25*math.cos(th),y-.25*math.sin(th))
            v=.2 if fwd>back else -.2;t=time.monotonic()
            while time.monotonic()-t<1.25:self.drive(v,0);time.sleep(.05)
            self.drive(0,0);self.odom.update(self.link.call('odom'));self.emit({'type':'nav_escape','direction':'forward' if v>0 else 'back','clearance':round(max(fwd,back),2)})
        last_fix=time.monotonic();stall_t=time.monotonic();stall_d=0.;last_seen=None;odom_at_fix=0.
        try:
            while True:
                if self.stop():return {'ok':False,'reason':'stopped by operator','travelled':travelled}
                if time.monotonic()-t0>timeout:return {'ok':False,'reason':'timeout','travelled':travelled}
                x,y,th=self.odom.update(self.link.call('odom'))
                step=math.hypot(x-prev[0],y-prev[1]);turn=abs(th-prev[2]);travelled+=step;since_fix+=step;prev=[x,y,th]
                if math.dist((x,y),path[-1])<goal_tol:return {'ok':True,'reason':'arrived','travelled':travelled}
                stall_d+=step+.1*turn   # turning in place counts as progress
                if time.monotonic()-stall_t>1.:
                    stalled=stall_d<.02;stall_t=time.monotonic();stall_d=0.
                else:stalled=False
                if since_fix>RELOCALISE_EVERY or time.monotonic()-last_fix>RELOCALISE_S or stalled:
                    since_fix=0.;scene=self.observe();last_fix=time.monotonic()   # count from the end of the (slow on the board) observation
                    if scene['robot'] is None:return {'ok':False,'reason':'robot not visible to the top camera','travelled':travelled}
                    x,y,th=self.odom.pose;self.emit({'type':'nav_fix','pose':scene['robot'],'detections':scene['detections']})
                    # Wheels can slip against an obstacle while encoders keep counting: judge "stuck" from the camera.
                    # Stuck = the encoders say the wheels moved >= 10 cm since the last fix but the camera sees < 3 cm (slipping).
                    if last_seen is not None and travelled-odom_at_fix>=.10 and math.dist(last_seen,(x,y))<.03:
                        return {'ok':False,'reason':'robot is stuck (wheels turn but the camera shows no motion)','travelled':travelled}
                    last_seen=(x,y);odom_at_fix=travelled
                    new=scene['grid']&~known
                    if new.sum()<4:
                        if stalled:return {'ok':False,'reason':'robot is not moving (stuck) and no new obstacle is visible','travelled':travelled}
                        continue
                    blocked=inflate(new,ROBOT_R+.08)   # the body sweeps wider than the centre line
                    for a,b in zip([(x,y)]+path[i:],path[i:]):
                        n=max(2,int(math.dist(a,b)/CELL))
                        for k in range(1,n+1):
                            c=cell((a[0]+(b[0]-a[0])*k/n,a[1]+(b[1]-a[1])*k/n))
                            if 0<=c[0]<blocked.shape[0] and 0<=c[1]<blocked.shape[1] and blocked[c] and math.dist(point(c),(x,y))>.12:
                                return {'ok':False,'reason':'path blocked by an obstacle at (%.2f, %.2f)'%point(c),'travelled':travelled,'blocked_at':[round(v,2) for v in point(c)]}
                while i<len(path)-1 and math.dist((x,y),path[i])<LOOKAHEAD:i+=1
                tx,ty=path[i];a=math.atan2(ty-y,tx-x)-th;a=(a+math.pi)%(2*math.pi)-math.pi;d=math.dist((x,y),path[-1])
                if abs(a)>math.radians(50):self.drive(0,1.6*math.copysign(1,a))
                else:
                    v=min(V_MAX,.25+d*.6) if i==len(path)-1 else V_MAX;self.drive(v,2.2*a*v/max(.15,LOOKAHEAD))
                time.sleep(.04)
        finally:self.drive(0,0)
