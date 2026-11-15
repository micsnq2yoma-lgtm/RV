"""Task definitions for the DexJoCo bimanual demo: tools the agent can call, how each runs, and what it observes.

Shared by the scripted skill test (PC) and the DeepSeek agent (PC or RV board). Everything here works from the
perceived scene (dex_perception) and the skill library; simulator state is never read.
"""
import math
import numpy as np
import dex_perception as P,dex_skills as S

class Episode:
    def __init__(self,link,lib,task,stop=lambda:False):
        self.link=link;self.task=task;self.L=lib[task];self.arms=S.Arms(link,stop)
        self.static=None;self.dims={};self.holding={};self.open_hand={}
        self.look()
    def look(self):
        o=self.link.call('observe');self.arms.sync(o);sc=P.scene(o)
        if self.static is None:   # fixtures and object sizes, measured once at the start
            self.static={n:v for n,v in sc.items() if n in S.STATIC}
            self.dims={n:{'h':v['top_z']-v['bottom_z'],'top0':v['top_z'],'size_xy':v['size_xy']} for n,v in sc.items()}
        self.obs=o;self.sc={**sc,**self.static};return o,self.sc
    def skill(self,name):
        sk=self.L['skills'].get(name)
        if sk is None:raise ValueError('没有技能 '+name)
        return sk
    def play(self,name,exclude=(),ref_name=None,offset=None):
        """Run a library skill at the references measured now; held objects get the closed-loop corrections.
        ref_name replaces the reference object (the press motion recorded at button 1, replayed at another button)."""
        o,sc=self.look();sk=self.skill(name)
        refs={a:S.ref_from_scene({**r,'name':ref_name} if ref_name else r,sc,exclude=tuple(r.get('exclude',()))+tuple(exclude),arms=o['arms']) for a,r in sk['ref'].items()}
        held={a:S.held_offset(o['arms'][a]['flange'],sc[ob]['center']) for a,ob in sk.get('held',{}).items() if ob in sc}
        def correct(skill,refs,j=0):
            _,sc2=self.look();return S.check_error(skill,refs,sc2,j)
        self.arms.play(sk,refs,held,correct=correct,offset=offset)
        return sk,refs
    def pick(self,obj):
        if obj in self.holding:raise ValueError('已经拿着 '+obj)
        _,sc=self.look()
        if obj not in sc:raise ValueError('看不到 '+obj)
        z0=sc[obj]['center'][2];sk,_=self.play('pick_'+obj);arm=list(sk['frames'])[0]
        self.open_hand[arm]=np.asarray(sk['frames'][arm][0][7:],float)
        if sk.get('squeeze'):self.arms.grip(arm)
        _,sc=self.look();dz=sc[obj]['center'][2]-z0 if obj in sc else 0
        ok=dz>.04
        if ok:self.holding[obj]=arm
        return {'ok':ok,'arm':arm,'lifted_m':round(float(dz),3),**({} if ok else {'error':'物体没有被抬起'})}
    def servo_place(self,obj,xy,z_align,z_release,spiral=0.):
        arm=self.holding.get(obj)
        if arm is None:raise ValueError('手里没有 '+obj)
        log=self.arms.servo_place(arm,self.look,obj,xy,z_align,z_release,self.open_hand.get(arm,self.arms.cmd[arm][7:]),spiral=spiral)
        self.holding.pop(obj,None)
        _,sc=self.look()
        return {'ok':True,'servo_error_m':log[-1] if log else None,'object_now':sc.get(obj,{}).get('center')}
    def home(self,arm):
        self.arms.send(self.arms.lead_in({arm:np.asarray(self.L['home'][arm],float)},speed=.3))

# ---------------- task: Tower of Hanoi ----------------
def hanoi_state(ep):
    _,sc=ep.look();held=set(ep.holding)
    st={p:S.stack_on(p,sc,exclude=held) for p in ('peg_A','peg_B','peg_C')}
    return {'pegs':st,'holding':{o:a for o,a in ep.holding.items()},
            'disks':{n:{'center':v['center'],'top_z':v['top_z']} for n,v in sc.items() if n.startswith('disk_')}}

def hanoi_place(ep,obj,peg):
    if peg not in ('peg_A','peg_B','peg_C'):raise ValueError('没有 '+peg)
    _,sc=ep.look()
    # The cameras look down steeply and see mostly a disk's top face, so its height is measured as its top surface minus
    # the base's top at the start of the episode (every disk starts resting on the base).
    h=ep.dims[obj]['top0']-ep.static['base']['top_z'] if 'base' in ep.static else ep.dims[obj]['h']
    top=S.ref_from_scene({'kind':'peg','name':peg},sc,exclude=[obj])['p'][2]
    # Servo target: where the held disk *appears* when it is truly over the peg. The hand hides part of a held disk, so its
    # measured centre is biased; the demo's placement (which dropped cleanly onto the peg) shows that bias just before
    # release, relative to the peg, measured by the same perception.
    arm=ep.holding.get(obj);rr=ep.L['skills'].get('place_'+obj,{}).get('release_rel',{}).get(arm,[0,0,0])
    xy=np.asarray(ep.static[peg]['center'][:2])   # (release_rel not used: the demo drops the disk from ~10 cm and pushes it down)
    return ep.servo_place(obj,xy,ep.static[peg]['top_z']+h/2+.04,top+h/2+.008)

TASKS={
 'bimanual_hanoi':{
   'tools':[('pick',{'object':['disk_small','disk_medium']},'用灵巧手抓起一个圆盘（小盘由左手抓，中盘由右手抓）。'),
            ('place_on_peg',{'object':['disk_small','disk_medium'],'peg':['peg_A','peg_B','peg_C']},'把手里的圆盘套到柱子上（视觉伺服对准后放下）。')],
   'run':{'pick':lambda ep,a:ep.pick(a['object']),'place_on_peg':lambda ep,a:hanoi_place(ep,a['object'],a['peg'])},
   'state':hanoi_state,
   'scripted':[('pick',{'object':'disk_medium'}),('place_on_peg',{'object':'disk_medium','peg':'peg_C'}),
               ('pick',{'object':'disk_small'}),('place_on_peg',{'object':'disk_small','peg':'peg_C'})]},
}

# ---------------- shared helpers ----------------
def held_summary(ep):return {o:a for o,a in ep.holding.items()}
def objs(sc,names):return {n:{'center':sc[n]['center'],'top_z':sc[n]['top_z'],'size_xy':sc[n]['size_xy']} for n in names if n in sc}
def carry(ep,name,obj=None,release=False):
    """Play a skill that moves (or releases) a held object; obj must be held."""
    if obj and obj not in ep.holding:raise ValueError('手里没有 '+obj)
    ep.play(name)
    if release and obj:ep.holding.pop(obj,None)
    _,sc=ep.look();return {'ok':True,**({'object_now':sc[obj]['center']} if obj in sc else {})}

# ---------------- task: microwave ----------------
def mw_state(ep):
    _,sc=ep.look();mw=ep.static.get('microwave');d=sc.get('door');hd=sc.get('hot_dog');out={'holding':held_summary(ep)}
    if d:out['door']={'center':d['center'],'size_x':d['size_xy'][0],'looks_open':d['size_xy'][0]>.12}
    if hd:
        out['hot_dog']={'center':hd['center']}
        if mw:
            lo=np.asarray(mw['center'][:2])-np.asarray(mw['size_xy'])/2;hi=np.asarray(mw['center'][:2])+np.asarray(mw['size_xy'])/2
            out['hot_dog']['inside_microwave_footprint']=bool(np.all(np.asarray(hd['center'][:2])>lo) and np.all(np.asarray(hd['center'][:2])<hi))
    if mw:out['microwave']={'center':mw['center'],'size_xy':mw['size_xy']}
    return out
def mw_open(ep):
    ep.play('open_door');s=mw_state(ep);return {'ok':bool(s.get('door',{}).get('looks_open')),'door':s.get('door')}
def mw_close(ep):
    ep.play('close_door_and_start');s=mw_state(ep);return {'ok':not s.get('door',{}).get('looks_open',True),'door':s.get('door')}

# ---------------- task: assembly ----------------
def asm_state(ep):
    _,sc=ep.look();out={'holding':held_summary(ep),**objs(sc,['peg','socket'])}
    if 'peg' in sc and 'socket' in sc:out['peg_to_socket_m']=round(float(np.linalg.norm(np.asarray(sc['peg']['center'])-np.asarray(sc['socket']['center']))),3)
    return out
def asm_insert(ep):
    if not {'peg','socket'}<=set(ep.holding):raise ValueError('需要两只手分别拿着 peg 和 socket')
    ep.play('insert_peg');return {**asm_state(ep),'ok':True}

# ---------------- task: photograph ----------------
def photo_shoot(ep):
    """Aim: the left hand's demo motion relative to the logo (measured now). Shoot: the right index finger's demo motion
    relative to the camera's top face (where the shutter is), as the camera now hangs in the left hand."""
    r=carry(ep,'aim_and_shoot','camera')
    import os;push=float(os.environ.get('SHUTTER_PUSH','0.0'))
    sk=ep.skill('shoot');F=np.asarray(sk['frames']['right']);v=F[-12,:3]-F[-1,:3];v=v/max(np.linalg.norm(v),1e-6)
    ep.play('shoot',offset={'right':-push*v});ep.arms.send([{}]*10);ep.arms.move_rel('right',.06*v,steps=15)
    return {**r,'shutter':'pressed'}

def photo_state(ep):
    _,sc=ep.look();return {'holding':held_summary(ep),**objs(sc,['camera','logo'])}

# ---------------- task: iPad ----------------
def ipad_state(ep):
    _,sc=ep.look();return {'holding':held_summary(ep),**objs(sc,['ipad']),'digits_pressed_so_far':getattr(ep,'pressed',[]),
                           'buttons_visible':sorted(n[7:] for n in sc if n.startswith('button_'))}
def ipad_press(ep,digit):
    d=str(digit)
    if 'ipad' not in ep.holding:raise ValueError('先拿起 iPad')
    _,sc=ep.look()
    if 'button_'+d not in sc:raise ValueError('看不到按键 '+d)
    # The demo's press of digit 1 (approach, touch, release), stored relative to that button and replayed at the
    # measured position of the requested button; then a straight retreat off the screen before any sideways move.
    # Only up to just after the touch: the demo's own release wiggles and can touch the button a second time.
    sk=ep.skill('press');F=np.asarray(sk['frames']['right']);mi=sk.get('mark_index',len(F)//2)
    v=F[0,:3]-F[mi,:3];v=v/max(np.linalg.norm(v),1e-6)
    cut=int(__import__('os').environ.get('PRESS_CUT','4'))
    ep.arms.play({**sk,'frames':{'right':F[:mi+cut].tolist()}},{'right':S.ref_from_scene({**sk['ref']['right'],'name':'button_'+d},sc)})
    ep.arms.move_rel('right',.06*v,steps=12)
    ep.pressed=getattr(ep,'pressed',[])+[int(d)]
    return {'ok':True,'pressed':int(d),'digits_pressed_so_far':ep.pressed}

TASKS.update({
 'bimanual_microwave_cook':{
   'tools':[('open_door',{},'左手拉开微波炉门（并扶住）。'),
            ('pick',{'object':['hot_dog']},'右手抓起热狗。'),
            ('put_in_microwave',{},'右手把手里的热狗放进微波炉并松开。'),
            ('close_door_and_start',{},'左手关上门，同时按启动键。')],
   'run':{'open_door':lambda ep,a:mw_open(ep),'pick':lambda ep,a:ep.pick(a['object']),
          'put_in_microwave':lambda ep,a:carry(ep,'put_in_microwave','hot_dog',release=True),'close_door_and_start':lambda ep,a:mw_close(ep)},
   'state':mw_state,
   'scripted':[('open_door',{}),('pick',{'object':'hot_dog'}),('put_in_microwave',{}),('close_door_and_start',{})]},
 'bimanual_assembly':{
   'tools':[('pick',{'object':['socket','peg']},'抓起物体：socket 用左手，peg 用右手。'),
            ('present_socket',{},'左手把拿着的插座举到身前的装配位置。'),
            ('insert_peg',{},'右手把拿着的圆柱销插进左手拿着的插座。')],
   'run':{'pick':lambda ep,a:ep.pick(a['object']),'present_socket':lambda ep,a:carry(ep,'present_socket','socket'),'insert_peg':lambda ep,a:asm_insert(ep)},
   'state':asm_state,
   'scripted':[('pick',{'object':'socket'}),('pick',{'object':'peg'}),('present_socket',{}),('insert_peg',{})]},
 'bimanual_photograph':{
   'tools':[('pick',{'object':['camera']},'左手拿起相机。'),
            ('aim_and_shoot',{},'把手里的相机对准墙上的标志（按标志实测位置）并按快门。')],
   'run':{'pick':lambda ep,a:ep.pick(a['object']),'aim_and_shoot':lambda ep,a:photo_shoot(ep)},
   'state':photo_state,
   'scripted':[('pick',{'object':'camera'}),('aim_and_shoot',{})]},
 'bimanual_unlock_ipad':{
   'tools':[('pick',{'object':['ipad']},'左手把 iPad 从支架上拿起并举到身前。'),
            ('press',{'digit':[str(i) for i in range(10)]},'右手食指按一个数字键（按实测的按键位置）。')],
   'run':{'pick':lambda ep,a:ep.pick(a['object']),'press':lambda ep,a:ipad_press(ep,a['digit'])},
   'state':ipad_state,
   'scripted':None},
})

def password_for(seed):
    """Passcode for the iPad task: three different digits, fixed per seed (so runs are reproducible)."""
    rng=np.random.default_rng(1000+int(seed));return [int(x) for x in rng.choice(10,3,replace=False)]
