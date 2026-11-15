"""Recognize simple colored-block target images locally; no model/image API."""
import base64,io,math
import numpy as np
from PIL import Image
from perception import centroid

COLORS=('red','green','blue','orange')
def color_masks(hsv):
    h,s,v=hsv[:,:,0],hsv[:,:,1],hsv[:,:,2];valid=(s>140)&(v>45)
    return {'red':valid&((h<11)|(h>245)),'green':valid&(h>65)&(h<115),
            'blue':valid&(h>130)&(h<190),'orange':valid&(h>=11)&(h<30)}

def detections(image):
    if isinstance(image,dict):data=base64.b64decode(image['jpeg_b64'],validate=True)
    elif isinstance(image,bytes):data=image
    else:raise ValueError('image must be bytes or a render response')
    if len(data)>4*1024*1024:raise ValueError('image exceeds 4 MiB')
    opened=Image.open(io.BytesIO(data))
    if opened.width>2048 or opened.height>2048:raise ValueError('image dimensions exceed 2048')
    hsv=np.asarray(opened.convert('HSV'));found=[]
    for name,mask in color_masks(hsv).items():
        point=centroid(mask)
        if point is None or point[2]<25:continue
        radius=int(math.ceil(math.sqrt(point[2])*1.5))
        left=max(0,int(point[0])-radius);right=min(opened.width,int(point[0])+radius+1)
        top=max(0,int(point[1])-radius);bottom=min(opened.height,int(point[1])+radius+1)
        ys,xs=np.where(mask[top:bottom,left:right]);xs+=left;ys+=top
        found.append({'name':name,'center':[point[0],point[1]],'area':point[2],
                      'bbox':[int(xs.min()),int(ys.min()),int(xs.max()-xs.min()+1),int(ys.max()-ys.min()+1)]})
    return found

def recognize(image):
    found=detections(image);groups=[]
    for obj in sorted(found,key=lambda o:o['center'][0]):
        match=next((g for g in groups if abs(np.mean([o['center'][0] for o in g])-obj['center'][0])<max(12,math.sqrt(obj['area'])*.8)),None)
        if match is None:groups.append([obj])
        else:match.append(obj)
    towers=[];loose=[]
    for group in groups:
        ordered=[o['name'] for o in sorted(group,key=lambda o:o['center'][1],reverse=True)]
        if len(ordered)>1:towers.append(ordered)
        else:loose.extend(ordered)
    confidence=.95 if len(found)>=2 and all(o['area']>=25 for o in found) else .4 if found else 0.
    return {'towers':towers,'loose':loose,'confidence':confidence,'detections':found}
