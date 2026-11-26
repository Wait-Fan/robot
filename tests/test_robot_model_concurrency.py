from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
import numpy as np

from ananno_phase2 import ec66_model as module
from ananno_phase2.robot_profiles import profile_config,FANUC

ROOT=Path(__file__).resolve().parents[1]


class RobotModelConcurrencyTests(unittest.TestCase):
    def test_concurrent_different_robot_imports_do_not_mix_last_xml_templates(self):
        real=module.mj;ready=threading.Event();release=threading.Event();second_done=threading.Event()
        errors=[];models={};first_call=[True]
        def compile_model(*args,**kwargs):
            model=real.MjModel.from_xml_string(*args,**kwargs)
            # Force an interleaving between the first URDF import and XML export.
            if threading.current_thread().name=='first' and first_call[0]:
                first_call[0]=False;ready.set()
                if not release.wait(5):raise RuntimeError('test rendezvous timed out')
            return model
        class Proxy:
            MjModel=SimpleNamespace(from_xml_string=compile_model)
            def __getattr__(self,name):return getattr(real,name)
        def make(name,robot_id):
            try:
                cfg=profile_config(ROOT,robot_id)
                robot=module.EC66Model(cfg['urdf'],cfg['srdf'],tip=cfg['tip_link'],
                    tool_definition=cfg.get('tool_definition'),touch_links=cfg.get('touch_links'))
                models[name]=robot.fk(cfg['initial_joints_rad'])
            except Exception as exc:errors.append((name,str(exc)))
            finally:
                if name=='second':second_done.set()
        a=threading.Thread(target=make,args=('first','ec66'),name='first')
        b=threading.Thread(target=make,args=('second',FANUC),name='second')
        try:
            module.mj=Proxy();a.start();self.assertTrue(ready.wait(5));b.start()
            second_done.wait(.4);release.set();a.join(10);b.join(10)
            self.assertFalse(a.is_alive());self.assertFalse(b.is_alive())
            self.assertEqual(errors,[])
            self.assertEqual(set(models),{'first','second'})
            self.assertTrue(all(pose.shape==(4,4) and np.isfinite(pose).all() for pose in models.values()))
        finally:
            release.set()
            if a.ident:a.join(10)
            if b.ident:b.join(10)
            module.mj=real


if __name__=='__main__':unittest.main()
