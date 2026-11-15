"""Object localisation for the LIBERO demo, run on the agent side (PC now, RV board later).

Input per camera: depth in mm, instance mask, intrinsics K and the camera pose (OpenCV convention, as robosuite's
get_camera_extrinsic_matrix returns it). The instance mask comes from the simulator and stands in for a learned
detector; positions and sizes are computed here from depth, never read from simulator state.
Images arrive upright (row 0 = top); the intrinsics apply to them directly.
"""
import base64,io
import numpy as np
from PIL import Image

SKIP=('robot','mount','gripper','floor','wall','table','main_table','panda','ontheground')

def _png(b64):return np.asarray(Image.open(io.BytesIO(base64.b64decode(b64))))

def points(cam):
    """All pixels of one camera as world points (N,3) plus their instance ids (N,)."""
    d=_png(cam['depth_mm_png']).astype(np.float32)/1000.;seg=_png(cam['seg_png']).astype(np.int32)
    h,w=d.shape;K=np.asarray(cam['K']);E=np.asarray(cam['cam_to_world'])
    vv,uu=np.mgrid[:h,:w]   # K applies to the upright image as served (verified against truth: errors 1-3 cm)
    x=(uu-K[0,2])/K[0,0]*d;y=(vv-K[1,2])/K[1,1]*d
    pc=np.stack([x,y,d,np.ones_like(d)],-1).reshape(-1,4)
    pw=(pc@E.T)[:,:3];return pw,seg.reshape(-1),d.reshape(-1)

def scene(obs,cams=('agentview','robot0_eye_in_hand')):
    """Per object: centre, top height, xy extent, pixel count, from all given cameras."""
    names=obs['instances'];acc={}
    for c in cams:
        if c not in obs['cameras']:continue
        pw,ids,d=points(obs['cameras'][c])
        ok=(d>.05)&(d<5.)
        for i in np.unique(ids[ok]):
            name=names.get(str(int(i)))
            if not name or i==0 or any(k in name.lower() for k in SKIP):continue
            acc.setdefault(name,[]).append(pw[ok&(ids==i)])
    out={}
    for name,parts in acc.items():
        p=np.concatenate(parts)
        if len(p)<15:continue
        lo,hi=np.percentile(p,5,axis=0),np.percentile(p,95,axis=0)
        out[name]={'center':[round(float(v),3) for v in (lo+hi)/2],'top_z':round(float(hi[2]),3),
                   'size_xy':[round(float(v),3) for v in (hi-lo)[:2]],'height':round(float(hi[2]-lo[2]),3),'pixels':int(len(p))}
    return out
