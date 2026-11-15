"""RAM-only goal image recognition and bounded cache; no API credentials."""
import base64,hashlib,json,re,threading
from pathlib import Path

class GoalStore:
    def __init__(self,root):
        self.root=Path(root);self.cache=self.root/'goal-images';self.cache.mkdir(exist_ok=True);self.items={};self.lock=threading.Lock()
    def catalog(self):
        return [{'id':p.stem,'name':p.stem} for p in sorted((self.root/'goals').glob('*.json')) if re.fullmatch('[a-z0-9-]+',p.stem)]
    def recognize(self,preset=None,image_b64=None,truth=None):
        if bool(preset)==bool(image_b64):raise ValueError('choose one preset or uploaded image')
        if preset:
            if not re.fullmatch('[a-z0-9-]+',preset):raise ValueError('invalid preset')
            data=(self.root/'goals'/(preset+'.jpg')).read_bytes()
            truth=json.loads((self.root/'goals'/(preset+'.json')).read_text())['goal']
        else:
            if len(image_b64)>6*1024*1024:raise ValueError('image exceeds size limit')
            data=base64.b64decode(image_b64,validate=True)
        from goal_perception import recognize
        with self.lock:
            result=recognize(data);key=hashlib.sha256(data).hexdigest()[:32]
            (self.cache/(key+'.jpg')).write_bytes(data)
            item={'id':key,'image_url':'/goal-images/'+key+'.jpg','recognition':result}
            self.items[key]={**item,'truth_goal':truth or {'towers':result['towers']}}
            while len(self.items)>16:
                old=next(iter(self.items));self.items.pop(old);(self.cache/(old+'.jpg')).unlink(missing_ok=True)
        return item
    def get(self,key):
        if key not in self.items:raise ValueError('goal expired; select image again')
        return self.items[key]

def evaluate_goal(goal,objects):
    poses={o['name'].removesuffix('_cube'):o['pos'] for o in objects['objects'] if o['name'].endswith('_cube')}
    wanted=goal.get('towers',[])
    if not wanted:return False
    used=set()
    for tower in wanted:
        if not tower or any(c not in poses or c in used for c in tower):return False
        used.update(tower)
        for bottom,top in zip(tower,tower[1:]):
            p,q=poses[bottom],poses[top]
            if ((p[0]-q[0])**2+(p[1]-q[1])**2)**.5>=.02 or abs(q[2]-p[2]-.04)>=.01:return False
        base=poses[tower[0]]
        if abs(base[2]-.02)>=.015:return False
        for extra,p in poses.items():
            if extra in tower:continue
            for color in tower:
                q=poses[color]
                if abs(p[2]-q[2]-.04)<.01 and ((p[0]-q[0])**2+(p[1]-q[1])**2)**.5<.02:return False
    return True
