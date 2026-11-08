"""Perception and tool boundaries use independent images and invalid model outputs."""
import sys,json,unittest,base64
from pathlib import Path
import mujoco,numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'board'/'agent'))
from agent import validate_call,tray_slot
from perception import Perception,project
from sim_server import Simulator
class AgentBoundaries(unittest.TestCase):
    def test_occluded_placements_keep_distinct_slots(self):
        reserved=[]
        for expected in (.445,.5,.555):
            selected=tray_slot(.5,[],reserved);self.assertAlmostEqual(selected,expected);reserved.append(selected)
        with self.assertRaises(ValueError):tray_slot(.5,[],reserved)
        self.assertAlmostEqual(tray_slot(.5,[.445],[]),.5)
    def call(self,name,args):return {'function':{'name':name,'arguments':json.dumps(args)}}
    def test_reject_coordinates_unknown_objects_and_wrong_types(self):
        for name,args in [('pick',{'object':'red_cube','x':.4}),('pick',{'object':'secret'}),('shell',{'command':'id'}),('finish',{'success':'yes','summary':'ok'})]:
            with self.assertRaises(ValueError):validate_call(self.call(name,args))
        self.assertEqual(validate_call(self.call('pick',{'object':'blue_cube'})),('pick',{'object':'blue_cube'}))
    def test_twenty_seed_perception_and_occlusion(self):
        sim=Simulator('127.0.0.1');snapshot=mujoco.MjData(sim.model);errors=[]
        with mujoco.Renderer(sim.model,height=480,width=640) as renderer:
            for seed in range(20):
                sim.reset(1400+seed)
                for _ in range(300):mujoco.mj_step(sim.model,sim.data)
                image=sim.service({'op':'render','camera':'top','w':640,'h':480},renderer,snapshot)
                vision=Perception();scene=vision.observe(image)
                truth={o['name']:o['pos'] for o in sim.service({'op':'objects'},renderer,snapshot)['objects']}
                for obj in scene['objects']:
                    self.assertFalse(obj['occluded']);errors.append(np.linalg.norm(np.array(obj['xy'])-truth[obj['name']][:2]))
                occluded=vision.observe(image,holding='red_cube')['objects'][0]
                self.assertTrue(occluded['occluded']);self.assertEqual(occluded['xy'],scene['objects'][0]['xy'])
        self.assertLess(np.mean(errors),.01);self.assertLess(max(errors),.02)
    def test_multiview_dimensions_and_bad_requests(self):
        sim=Simulator('127.0.0.1');snapshot=mujoco.MjData(sim.model)
        with mujoco.Renderer(sim.model,height=240,width=320) as r:
            result=sim.service({'op':'render_multi','cameras':['top','front','side','wrist'],'w':320,'h':240},{(320,240):r},snapshot)
            self.assertEqual(set(result['images']),{'top','front','side','wrist'})
            for image in result['images'].values():self.assertEqual((image['w'],image['h']),(320,240));self.assertTrue(base64.b64decode(image['jpeg_b64']).startswith(b'\xff\xd8'))
            for cameras in [[],['bad'],['top','top']]:
                with self.assertRaises(ValueError):sim.service({'op':'render_multi','cameras':cameras,'w':320,'h':240},r,snapshot)
if __name__=='__main__':unittest.main()
