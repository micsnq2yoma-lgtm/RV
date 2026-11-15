"""Protocol v1.3 layout validation and independent goal-image rendering."""
import base64,io
import mujoco,numpy as np
from PIL import Image
COLORS=('red','green','blue','orange')

def truth_structure(objects):
    poses={o['name'].removesuffix('_cube'):np.asarray(o['pos']) for o in objects['objects'] if o['name'].removesuffix('_cube') in COLORS}
    support={}
    for color,p in poses.items():
        lower=[c for c,q in poses.items() if c!=color and abs(p[2]-q[2]-.04)<.01 and np.linalg.norm(p[:2]-q[:2])<.02]
        if lower:support[color]=min(lower,key=lambda c:np.linalg.norm(p-poses[c]))
    stacks=[]
    for base in poses:
        if base in support:continue
        stack=[base]
        while True:
            upper=[c for c,below in support.items() if below==stack[-1] and c not in stack]
            if len(upper)!=1:break
            stack.append(upper[0])
        stacks.append(stack)
    return {'towers':[s for s in stacks if len(s)>1],'loose':[s[0] for s in stacks if len(s)==1]}

def evaluate_goal(goal,objects):
    expected=goal.get('towers',[]);actual=truth_structure(objects);targets={c for s in expected for c in s}
    relevant=[s for s in actual['towers'] if set(s)&targets]
    return bool(expected) and sorted(map(tuple,relevant))==sorted(map(tuple,expected))

def towers(layout):
    if not isinstance(layout,dict) or set(layout)-{'towers','loose'}:raise ValueError('invalid layout')
    stacks=layout.get('towers');loose=layout.get('loose',[])
    if not isinstance(stacks,list) or not isinstance(loose,list) or len(stacks)>4:raise ValueError('invalid towers')
    if any(not isinstance(t,list) or not 1<=len(t)<=4 for t in stacks):raise ValueError('empty or oversized tower')
    flat=[c for t in stacks for c in t]+loose
    if any(not isinstance(c,str) or c not in COLORS for c in flat) or len(flat)!=len(set(flat)):raise ValueError('unknown or duplicate color')
    return [list(t) for t in stacks]+[[c] for c in loose]+[[c] for c in COLORS if c not in flat]

def arrange(model,data,stacks,positions):
    for stack,xy in zip(stacks,positions):
        for level,color in enumerate(stack):
            body=model.body(color+'_cube');joint=model.body_jntadr[body.id];adr=model.jnt_qposadr[joint]
            data.qpos[adr:adr+7]=[*xy,.0201+.04*level,1,0,0,0]

def render_goal(model,renderer,goal,style='front'):
    if style!='front':raise ValueError('goal style must be front')
    stacks=towers(goal);data=mujoco.MjData(model)
    positions=[(.6,(i-(len(stacks)-1)/2)*.13) for i in range(len(stacks))]
    arrange(model,data,stacks,positions);mujoco.mj_forward(model,data)
    active=renderer[(640,480)] if isinstance(renderer,dict) else renderer
    # Brighter, flatter light for the goal card (the live scene keeps its single overhead light); restored below.
    headlight=(model.vis.headlight.ambient.copy(),model.vis.headlight.diffuse.copy())
    model.vis.headlight.ambient[:]=.55;model.vis.headlight.diffuse[:]=.65
    try:active.update_scene(data,camera='goal')
    finally:model.vis.headlight.ambient[:],model.vis.headlight.diffuse[:]=headlight
    cube_ids={model.body(c+'_cube').id for c in COLORS}
    for geom in active.scene.geoms[:active.scene.ngeom]:
        keep=False
        if geom.objtype==mujoco.mjtObj.mjOBJ_GEOM:
            body=model.geom_bodyid[geom.objid]
            keep=body in cube_ids or model.geom(geom.objid).name=='table'
        if not keep:geom.pos[:]=[100,100,-100];geom.rgba[3]=0
    image=io.BytesIO();Image.fromarray(active.render()).save(image,'JPEG',quality=90)
    return {'jpeg_b64':base64.b64encode(image.getvalue()).decode(),'w':640,'h':480}
