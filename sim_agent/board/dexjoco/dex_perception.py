"""Object localisation for the DexJoCo demo, run on the agent side (PC for local tests, RV board for deployment).

Input per camera: depth in mm, instance mask, intrinsics K and camera pose (OpenCV convention). The instance mask
comes from the simulator and stands in for a learned detector; positions, heights, extents and yaw are computed here
from depth, never read from simulator state. Images are upright (row 0 = top).
"""
import base64,io,math
import numpy as np
from PIL import Image

def _png(b64):return np.asarray(Image.open(io.BytesIO(base64.b64decode(b64))))

def points(cam):
    d=_png(cam['depth_mm_png']).astype(np.float32)/1000.;seg=_png(cam['seg_png']).astype(np.int32)
    h,w=d.shape;K=np.asarray(cam['K']);E=np.asarray(cam['cam_to_world'])
    vv,uu=np.mgrid[:h,:w]
    x=(uu-K[0,2])/K[0,0]*d;y=(vv-K[1,2])/K[1,1]*d
    pc=np.stack([x,y,d,np.ones_like(d)],-1).reshape(-1,4)
    return (pc@E.T)[:,:3],seg.reshape(-1),d.reshape(-1)

def _yaw(p):
    """Major axis of the points in the xy plane, folded to [-90, 90) degrees (an axis has no direction)."""
    q=p[:,:2]-p[:,:2].mean(0)
    if len(q)<20:return 0.,1.
    w,v=np.linalg.eigh(np.cov(q.T));a=v[:,1];y=math.degrees(math.atan2(a[1],a[0]))
    y=(y+90)%180-90
    return y,float(w[1]/max(w[0],1e-9))

def scene(obs):
    """Per object: centre, top height, bottom, xy extent, yaw of the major axis (deg) and how elongated it is."""
    names=obs['instances'];acc={}
    for c,cam in obs['cameras'].items():
        pw,ids,d=points(cam);ok=(d>.05)&(d<6.)
        for i in np.unique(ids[ok]):
            n=names.get(str(int(i)))
            if n:acc.setdefault(n,[]).append(pw[ok&(ids==i)])
    out={}
    for n,parts in acc.items():
        p=np.concatenate(parts)
        if len(p)<10:continue
        # Reject stray pixels (mask edges, mislabelled strips): keep points near the median on every axis.
        med=np.median(p,0);mad=np.median(np.abs(p-med),0)
        p=p[np.all(np.abs(p-med)<=np.maximum(4*mad,.015),1)]
        if len(p)<10:continue
        lo,hi=np.percentile(p,3,axis=0),np.percentile(p,97,axis=0);yaw,elong=_yaw(p)
        tc=p[p[:,2]>hi[2]-.005].mean(0)   # centre of the top 5 mm (a button on top, the top face)
        out[n]={'center':[round(float(v),3) for v in (lo+hi)/2],'top_z':round(float(hi[2]),3),'bottom_z':round(float(lo[2]),3),
                'size_xy':[round(float(v),3) for v in (hi-lo)[:2]],'yaw_deg':round(yaw,1),'elongation':round(elong,1),'pixels':int(len(p)),
                'top_center':[round(float(v),3) for v in tc]}
    return out
