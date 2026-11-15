"""Top-camera perception for the navigation demo. Runs on the board; never uses simulator truth.

Robot pose: cyan (front) and magenta (rear) markers on the chassis -> position and heading.
Target zones: colour segmentation -> centre and extent. Obstacles and walls: dark, unsaturated pixels ->
occupancy grid (5 cm cells) in world coordinates.
"""
import base64,io,math,sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from perception import centroid

MARK_Z=.133;ZONE_Z=.004;OBST_Z=.35;CELL=.05   # obstacles: lit top faces of boxes (.4 m) and walls (.3 m)
X0,X1,Y0,Y1=-2.1,2.1,-1.6,1.6        # grid extent (m), covers the walled arena
ZONES={'red':lambda h,s,v:((h<12)|(h>245))&(s>110)&(v>150),'green':lambda h,s,v:(h>80)&(h<105)&(s>110),
       'blue':lambda h,s,v:(h>140)&(h<165)&(s>100),'yellow':lambda h,s,v:(h>28)&(h<52)&(s>85)&(v>180)}

def decode(image):
    data=base64.b64decode(image['jpeg_b64'],validate=True)
    return np.asarray(Image.open(io.BytesIO(data)).convert('HSV')).astype(np.int16)

class Camera:
    def __init__(self,image):
        self.w,self.h=image['w'],image['h'];self.f=self.h/(2*math.tan(math.radians(image['fovy'])/2))
        self.R=np.asarray(image['cam_xmat']).reshape(3,3);self.o=np.asarray(image['cam_pos'])
    def ground(self,u,v,z):
        """Pixel(s) -> world xy on the horizontal plane at height z."""
        u=np.asarray(u,float);v=np.asarray(v,float)
        d=np.stack([(u+.5-self.w/2)/self.f,-(v+.5-self.h/2)/self.f,-np.ones_like(u)],-1)@self.R.T
        t=(z-self.o[2])/d[...,2];return self.o[:2]+t[...,None]*d[...,:2]
    def pixel(self,x,y,z):
        p=self.R.T@(np.array([x,y,z])-self.o);return self.w/2+self.f*p[0]/-p[2]-.5,self.h/2-self.f*p[1]/-p[2]-.5

class NavPerception:
    def __init__(self):self.zones={};self.area={};self.mem=None
    def observe(self,image):
        hsv=decode(image);h,s,v=hsv[...,0],hsv[...,1],hsv[...,2];cam=Camera(image);det=[]
        front=centroid((h>118)&(h<138)&(s>150)&(v>120));rear=centroid((h>203)&(h<232)&(s>150)&(v>120))
        robot=None
        if front and rear:
            pf=cam.ground(front[0],front[1],MARK_Z);pr=cam.ground(rear[0],rear[1],MARK_Z);c=(pf+pr)/2
            robot={'x':float(c[0]),'y':float(c[1]),'yaw':math.atan2(pf[1]-pr[1],pf[0]-pr[0])}
            det.append({'name':'robot','bbox':[int(min(front[0],rear[0]))-14,int(min(front[1],rear[1]))-14,int(abs(front[0]-rear[0]))+28,int(abs(front[1]-rear[1]))+28]})
        zones={}
        for name,rule in ZONES.items():
            mask=rule(h,s,v)
            if robot:mask&=~self.footprint(cam,robot,mask.shape,.3)
            c=centroid(mask)
            if c is None or c[2]<150:continue
            ys,xs=np.nonzero(mask);sel=(np.abs(xs-c[0])<90)&(np.abs(ys-c[1])<90);xs,ys=xs[sel],ys[sel]
            lo=cam.ground(xs.min(),ys.max(),ZONE_Z);hi=cam.ground(xs.max(),ys.min(),ZONE_Z);ctr=cam.ground(c[0],c[1],ZONE_Z)
            det.append({'name':name,'bbox':[int(xs.min()),int(ys.min()),int(xs.max()-xs.min()+1),int(ys.max()-ys.min()+1)]})
            # Zones are fixed: keep the most complete view; a view partly covered by the robot does not replace it.
            if c[2]<.85*self.area.get(name,0):continue
            self.area[name]=max(c[2],self.area.get(name,0))
            self.zones[name]={'center':[round(float(ctr[0]),3),round(float(ctr[1]),3)],'half':[round(float(abs(hi[0]-lo[0])/2),3),round(float(abs(hi[1]-lo[1])/2),3)]}
        zones=dict(self.zones)
        # Lit tops only (dark side faces would project inward): brown boxes (H 5-40, S 28-100, any lit V, also the bright
        # arena centre) or grey walls (S < 28, V < 190). The light-grey start pad (S < 12, V 199-226) is not an obstacle.
        obst=(v>110)&(((s>=28)&(s<100)&(h>=5)&(h<=40))|((s<28)&(v<190)))
        # The white chassis is not an obstacle colour; only its rim and wheels need masking, so keep the radius small.
        if robot:obst&=~self.footprint(cam,robot,obst.shape,.22)
        grid=self.grid(cam,obst)
        if robot:
            # Cells hidden under/next to the robot keep what was seen there before, so a box corner beside the robot
            # does not vanish from the map when the robot stops close to it.
            nx,ny=grid.shape[1],grid.shape[0];jj,ii=np.mgrid[:ny,:nx]
            hidden=(X0+(ii+.5)*CELL-robot['x'])**2+(Y0+(jj+.5)*CELL-robot['y'])**2<.26**2
            if self.mem is not None:grid=np.where(hidden,self.mem,grid)
        self.mem=grid.copy()
        return {'robot':robot,'zones':zones,'grid':grid,'detections':det}
    def footprint(self,cam,robot,shape,radius):
        u,v=cam.pixel(robot['x'],robot['y'],MARK_Z);r=radius*cam.f/(cam.o[2]-MARK_Z)
        yy,xx=np.ogrid[:shape[0],:shape[1]];return (xx-u)**2+(yy-v)**2<r*r
    def grid(self,cam,mask):
        nx,ny=int(round((X1-X0)/CELL)),int(round((Y1-Y0)/CELL));g=np.zeros((ny,nx),bool)
        ys,xs=np.nonzero(mask)
        if len(xs):
            p=cam.ground(xs,ys,OBST_Z);i=((p[:,0]-X0)/CELL).astype(int);j=((p[:,1]-Y0)/CELL).astype(int)
            ok=(i>=0)&(i<nx)&(j>=0)&(j<ny);np.add.at(g,(j[ok],i[ok]),True)
        # Opening (3x3 erode then dilate) drops one-cell lines such as the start pad's rendered edge.
        def shift_all(a,op):
            p=np.pad(a,1,constant_values=op is np.logical_and);out=a.copy()
            for dj in (0,1,2):
                for di in (0,1,2):out=op(out,p[dj:dj+a.shape[0],di:di+a.shape[1]])
            return out
        g=shift_all(shift_all(g,np.logical_and),np.logical_or)
        # Border cells are walls even if the camera rim is cut off.
        g[0,:]=g[-1,:]=True;g[:,0]=g[:,-1]=True
        return g
