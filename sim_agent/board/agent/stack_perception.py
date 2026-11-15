"""Multi-view color geometry. Never accesses the objects truth endpoint."""
import math
from functools import cmp_to_key
import numpy as np
from goal_perception import detections,COLORS

def ray(image,pixel):
    w,h=image['w'],image['h'];f=h/(2*math.tan(math.radians(image['fovy'])/2))
    d=np.asarray(image['cam_xmat']).reshape(3,3)@np.array([(pixel[0]+.5-w/2)/f,-(pixel[1]+.5-h/2)/f,-1.])
    return np.asarray(image['cam_pos']),d/np.linalg.norm(d)

def triangulate(lines):
    a=np.zeros((3,3));b=np.zeros(3)
    for origin,d in lines:
        p=np.eye(3)-np.outer(d,d);a+=p;b+=p@origin
    if np.linalg.cond(a)>1e6:raise ValueError('degenerate camera geometry')
    return np.linalg.solve(a,b)

class StackPerception:
    def __init__(self):self.previous={};self.expected={}
    def placed(self,name,xy,z):self.expected[name.replace('_cube','')]=[float(xy[0]),float(xy[1]),float(z)]
    def observe(self,images,holding=None):
        found={camera:detections(image) for camera,image in images.items()};lines={c:[] for c in COLORS};objects={}
        for camera,items in found.items():
            for item in items:lines[item['name']].append(ray(images[camera],item['center']))
        held=holding.replace('_cube','') if holding else None
        for color,sights in lines.items():
            if color==held:continue
            if len(sights)>=2:
                point=triangulate(sights);level=int(np.clip(round((point[2]-.02)/.04),0,3))
                objects[color]={'name':color+'_cube','xy':point[:2].tolist(),'z_est':.02+.04*level,'level':level,'occluded':False,'inferred':False,'in':'table'}
        for color,sights in lines.items():
            if color in objects or color==held:continue
            old=self.previous.get(color);hint=self.expected.get(color)
            if sights:
                o,d=sights[0];candidates=[]
                for level in range(4):
                    z=.02+.04*level;t=(z-o[2])/d[2];xy=(o+t*d)[:2]
                    score=min((np.linalg.norm(xy-v['xy']) for v in objects.values() if v['level']>level),default=1.)
                    candidates.append((score,level,xy))
                best=min(candidates,key=lambda x:x[0])
                if best[0]>.05:best=candidates[0]
                _,level,xy=best
                objects[color]={'name':color+'_cube','xy':xy.tolist(),'z_est':.02+.04*level,'level':level,'occluded':True,'inferred':True,'in':'table'}
            elif hint:
                objects[color]={'name':color+'_cube','xy':hint[:2],'z_est':hint[2],'level':int(round((hint[2]-.02)/.04)),'occluded':True,'inferred':True,'in':'unknown'}
            elif old:objects[color]={**old,'occluded':True,'inferred':True}
            else:objects[color]={'name':color+'_cube','xy':None,'z_est':None,'level':None,'occluded':True,'inferred':True,'in':'unknown'}
        groups=[]
        for color,obj in objects.items():
            if obj['xy'] is None:continue
            # Same tower only if nearly coaxial AND at a different measured level: two 4 cm cubes side by side are
            # ~4.4 cm apart and, seen from the front camera, the farther one looks "higher" (report 015, G1-3).
            group=next((g for g in groups if all(np.linalg.norm(np.asarray(objects[c]['xy'])-obj['xy'])<.03 and objects[c]['level']!=obj['level'] for c in g)),None)
            if group is None:groups.append([color])
            else:group.append(color)
        towers=[];loose=[]
        for group in groups:
            def compare(a,b):
                votes=0
                for camera in ('front','side'):
                    visible={o['name']:o for o in found.get(camera,[])}
                    if a in visible and b in visible:
                        dy=visible[a]['center'][1]-visible[b]['center'][1]
                        if abs(dy)>2:votes+=1 if dy>0 else -1
                if votes:return -1 if votes>0 else 1
                return -1 if objects[a]['z_est']<objects[b]['z_est'] else 1
            ordered=sorted(group,key=cmp_to_key(compare))
            if len(ordered)>1:towers.append(ordered)
            else:loose+=ordered
            for i,color in enumerate(ordered):
                objects[color]['in']='table' if i==0 else 'on:'+ordered[i-1]+'_cube'
                objects[color]['z_est']=.02+.04*i;objects[color]['level']=i
        if held:
            objects[held]={**self.previous.get(held,{'name':held+'_cube','xy':None,'z_est':None}),'in':'gripper','occluded':True,'inferred':True}
        self.previous=objects
        return {'objects':list(objects.values()),'towers':towers,'loose':loose,'gripper':'holding:'+holding if holding else 'empty','detections':found.get('top',[])}
