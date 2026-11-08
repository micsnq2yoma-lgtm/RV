"""RGB-only tabletop perception. Truth endpoints are never used here."""
import base64,io,math
import ctypes
from pathlib import Path
import numpy as np
from PIL import Image

CUBES=('red_cube','green_cube','blue_cube')
TRAYS=('left_tray','right_tray')
_native=None
_library=Path(__file__).with_name('libvision_native.so')
if _library.exists():
    _native=ctypes.CDLL(str(_library)).rv_centroid
    _native.argtypes=[np.ctypeslib.ndpointer(dtype=np.uint8,flags='C_CONTIGUOUS'),ctypes.c_int,ctypes.c_int,np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')]
    _native.restype=ctypes.c_int

def centroid(mask):
    """Largest 4-connected component, using row runs and union-find."""
    if _native is not None:
        data=np.array(mask,dtype=np.uint8,order='C',copy=True);out=np.zeros(3);result=_native(data,data.shape[1],data.shape[0],out)
        if result<0:raise RuntimeError('component scan failed')
        return (float(out[0]),float(out[1]),int(out[2])) if result else None
    parent=[];runs=[];previous=[]
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for y,row in enumerate(mask):
        edges=np.flatnonzero(np.diff(np.r_[False,row,False]));current=[]
        for left,right in edges.reshape(-1,2):
            ident=len(parent);parent.append(ident);runs.append((int(left),int(right),y));current.append(ident)
            for old in previous:
                a,b,_=runs[old]
                if a<right and b>left:parent[root(old)]=root(ident)
        previous=current
    groups={}
    for i,(a,b,y) in enumerate(runs):
        n=b-a;v=groups.setdefault(root(i),[0.,0.,0.]);v[0]+=n;v[1]+=(a+b-1)*n/2;v[2]+=y*n
    if not groups:return None
    n,x,y=max(groups.values(),key=lambda v:v[0])
    return (x/n,y/n,int(n)) if n>=12 else None

def project(u,v,height,image):
    w,h=image['w'],image['h'];f=h/(2*math.tan(math.radians(image['fovy'])/2))
    ray=np.array([(u+.5-w/2)/f,-(v+.5-h/2)/f,-1.])
    ray=np.asarray(image['cam_xmat']).reshape(3,3)@ray;origin=np.asarray(image['cam_pos'])
    if abs(ray[2])<1e-8:raise ValueError('camera ray parallel to table')
    distance=(height-origin[2])/ray[2]
    if distance<=0:raise ValueError('surface behind camera')
    return (origin+distance*ray)[:2]

class Perception:
    def __init__(self,table_z=0.):self.previous={};self.table_z=table_z;self.hints={}
    def placed(self,name,surface):self.hints[name]=surface
    def observe(self,image,holding=None):
        rgb=Image.open(io.BytesIO(base64.b64decode(image['jpeg_b64'],validate=True))).convert('HSV')
        hsv=np.asarray(rgb);h,s,v=hsv[:,:,0],hsv[:,:,1],hsv[:,:,2];color=(s>100)&(v>60)
        masks={'red_cube':((h<12)|(h>245)),'green_cube':((h>65)&(h<110)),
               'blue_cube':((h>135)&(h<185)),'left_tray':((h>25)&(h<55)),'right_tray':((h>190)&(h<235))}
        found={}
        for name,mask in masks.items():
            point=centroid(mask&((s>55)&(v>45) if name=='right_tray' else color));old=self.previous.get(name)
            if point is None or name==holding:
                found[name]={**(old or {'name':name,'xy':None,'z_est':None,'in':'unknown'}),'occluded':True}
                continue
            surface=self.hints.get(name,'table');height=.008 if name in TRAYS else .04
            if surface in TRAYS:height=.048
            elif surface.startswith('on:'):height=.08
            xy=project(point[0],point[1],self.table_z+height,image)
            found[name]={'name':name,'xy':xy.tolist(),'z_est':self.table_z+(height-.02 if name in CUBES else 0.),
                         'in':'table','occluded':False,'pixels':point[2]}
        for name in CUBES:
            obj=found[name]
            if name==holding:obj['in']='gripper';continue
            if obj['occluded']:continue
            xy=np.asarray(obj['xy'])
            for tray in TRAYS:
                pos=found[tray]['xy']
                if pos and np.all(np.abs(xy-pos)<[.09,.07]):obj['in']=tray
            hint=self.hints.get(name,'')
            if hint.startswith('on:'):
                support=found.get(hint[3:],{}).get('xy')
                if support and np.linalg.norm(xy-support)<.03:obj['in']=hint
        self.previous=found
        return {'objects':list(found.values()),'gripper':'holding:'+holding if holding else 'empty'}
