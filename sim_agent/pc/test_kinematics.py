"""Independent MuJoCo oracle and strict IK failure tests."""
import sys
from pathlib import Path
import unittest
import numpy as np
import mujoco
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'board'/'agent'))
from kin import Kinematics,down,rotation_error
from sim_server import load_scene,export_kinematics,HOME


class KinematicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=load_scene();cls.kin=Kinematics(export_kinematics(cls.model))

    def test_fk_matches_independent_engine(self):
        rng=np.random.default_rng(111);d=mujoco.MjData(self.model)
        for _ in range(50):
            q=rng.uniform(self.kin.limits[:,0],self.kin.limits[:,1])
            d.qpos[:7]=q;mujoco.mj_forward(self.model,d)
            p,r=self.kin.fk(q)
            self.assertLess(np.linalg.norm(p-d.site('tcp').xpos),1e-10)
            self.assertLess(np.linalg.norm(rotation_error(r,d.site('tcp').xmat.reshape(3,3))),1e-10)

    def test_ik_returns_only_converged_solutions(self):
        for target in ([.68,-.12,.023],[.5,.3,.028],[.72,.23,.06]):
            q=self.kin.ik(target,down(),HOME);p,r=self.kin.fk(q)
            self.assertLess(np.linalg.norm(p-target),.001)
            self.assertLess(np.linalg.norm(rotation_error(down(),r)),np.pi/180)
            self.assertTrue(np.all(q>=self.kin.limits[:,0]) and np.all(q<=self.kin.limits[:,1]))
        with self.assertRaisesRegex(RuntimeError,'200 iterations'):
            self.kin.ik([5,5,5],down(),HOME)
        with self.assertRaises(ValueError):self.kin.ik([0,0,0],np.zeros((3,3)),HOME)


if __name__=='__main__':unittest.main()
