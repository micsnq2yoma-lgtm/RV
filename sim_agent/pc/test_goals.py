import sys,json,unittest
from pathlib import Path
import mujoco,numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'board'/'agent'))
from goal_perception import recognize
from layouts import towers,render_goal,COLORS
from sim_server import Simulator

class GoalTests(unittest.TestCase):
    def test_presets(self):
        for path in (Path(__file__).resolve().parents[1]/'goals').glob('*.json'):
            with self.subTest(preset=path.stem):
                expected=json.loads(path.read_text())['goal']['towers'];actual=recognize(path.with_suffix('.jpg').read_bytes())
                self.assertEqual(sorted(map(tuple,actual['towers'])),sorted(map(tuple,expected)))
                used={c for t in expected for c in t};self.assertEqual(set(actual['loose']),set(COLORS)-used)
                self.assertGreaterEqual(actual['confidence'],.8)
    def test_goal_render_does_not_mutate_live_state_or_model(self):
        sim=Simulator('127.0.0.2');q=sim.data.qpos.copy();v=sim.data.qvel.copy();rgba=sim.model.geom_rgba.copy()
        with mujoco.Renderer(sim.model,height=480,width=640) as r:
            render_goal(sim.model,r,{'towers':[['red','orange'],['green','blue']]})
        np.testing.assert_array_equal(q,sim.data.qpos);np.testing.assert_array_equal(v,sim.data.qvel);np.testing.assert_array_equal(rgba,sim.model.geom_rgba)
    def test_layout_validation_and_height(self):
        sim=Simulator('127.0.0.2');sim.reset(4,{'towers':[['green','blue'],['red'],['orange']]})
        self.assertAlmostEqual(sim.data.body('blue_cube').xpos[2]-sim.data.body('green_cube').xpos[2],.04)
        before=sim.data.qpos.copy()
        for layout in ({'towers':[['red','red']]},{'towers':[['unknown']]},{'towers':[[]]}):
            with self.assertRaises(ValueError):sim.reset(0,layout)
            np.testing.assert_array_equal(before,sim.data.qpos)

if __name__=='__main__':unittest.main()
