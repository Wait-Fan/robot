from dataclasses import replace
import unittest
from unittest.mock import patch
import numpy as np
from tests.test_multiple_open_sides import fake_verifier
from tests.test_side_direct_approach import pose_robot,config
from tests.test_robot_2025 import item
from ananno_phase2.models import Pallet
from ananno_phase2.robot_pipeline import _validated_sequence
from ananno_phase2.paper_config import PaperConfig


class ValidationAccelerationTests(unittest.TestCase):
    def setUp(self):
        self.v=fake_verifier();self.calls,self.original=pose_robot(self.v)
        self.pallet=Pallet(30,10,10);self.approach=config(('+Z',))
        self.a=item('A',l=10,w=10,h=10)
        self.b=item('B',x=15,l=10,w=10,h=10,order=2)

    def test_legacy_thirty_second_budget_is_per_box_not_entire_pallet(self):
        clock=[0.];self.v.config['sequence_budget_seconds']=7
        def move(*args,**kwargs):
            clock[0]+=1
            return self.original(*args,**kwargs)
        self.v._move=move
        with patch('ananno_phase2.robot_offline.time.monotonic',side_effect=lambda:clock[0]):
            result=self.v.verify([self.a,self.b],self.pallet,self.approach)
        self.assertTrue(result['passed'],result['reason'])
        self.assertEqual(result['budget_scope'],'per_box')

    def test_extending_sequence_reuses_only_complete_verified_prefix(self):
        self.assertTrue(self.v.verify([self.a],self.pallet,self.approach)['passed'])
        self.calls.clear()
        result=self.v.verify([self.a,self.b],self.pallet,self.approach)
        self.assertTrue(result['passed']);self.assertEqual(len(self.calls),6)
        self.assertEqual(result['reused_prefix_boxes'],1)
        self.assertEqual(len(result['stages']),12)
        np.testing.assert_allclose(result['stages'][6]['trajectory'][0]['positions'],result['stages'][5]['trajectory'][-1]['positions'])
        self.assertEqual([o['id'] for o in self.v.robot.obstacles],['pallet','placed_A','placed_B'])

    def test_replanned_prefix_with_different_joint_branch_invalidates_later_cache(self):
        self.v.verify([self.a,self.b],self.pallet,self.approach)
        self.v.cache.clear();self.v.pallet_cache.clear();self.v.prefix_cache.popitem(last=False);self.calls.clear()
        def changed(start,target,**kwargs):
            path,reason=self.original(start,target,**kwargs)
            path[-1][3]+=.01
            return path,reason
        self.v._move=changed
        result=self.v.verify([self.a,self.b],self.pallet,self.approach)
        self.assertEqual(result['reused_prefix_boxes'],0);self.assertEqual(len(self.calls),12)
        np.testing.assert_allclose(result['stages'][6]['trajectory'][0]['positions'],result['stages'][5]['trajectory'][-1]['positions'])

    def test_success_reports_are_not_mutable_cache_entries(self):
        first=self.v.verify([self.a],self.pallet,self.approach)
        first['stages'].clear()
        second=self.v.verify([self.a],self.pallet,self.approach)
        self.assertTrue(second['passed']);self.assertEqual(len(second['stages']),6)

    def test_changed_geometry_or_scene_invalidates_prefix(self):
        self.v.verify([self.a],self.pallet,self.approach)
        self.calls.clear()
        changed=replace(self.a,point=replace(self.a.point,x=1))
        self.v.verify([changed,self.b],self.pallet,self.approach)
        self.assertEqual(len(self.calls),12)
        self.calls.clear();self.v.base_pallet[2,3]=.1
        self.v.verify([self.a,self.b],self.pallet,self.approach)
        self.assertEqual(len(self.calls),12)

    def test_budget_expiry_is_not_negative_cached_and_keeps_prefix(self):
        clock=[0.];self.v.config['box_budget_seconds']=7
        def slow(start,target,**kwargs):
            clock[0]+=1 if len(self.calls)<6 else 4
            return self.original(start,target,**kwargs)
        self.v._move=slow
        with patch('ananno_phase2.robot_offline.time.monotonic',side_effect=lambda:clock[0]):
            first=self.v.verify([self.a,self.b],self.pallet,self.approach)
        self.assertFalse(first['passed']);self.assertEqual(first['status'],'unverified')
        self.assertEqual(first['reason'],'box_validation_budget_exhausted')
        self.v._move=self.original;self.calls.clear()
        second=self.v.verify([self.a,self.b],self.pallet,self.approach)
        self.assertTrue(second['passed']);self.assertEqual(len(self.calls),6)

    def test_budget_incomplete_is_not_treated_as_rejected_layout(self):
        from ananno_phase2.run_control import RobotPlanningIncomplete
        class BudgetVerifier:
            def verify(self,*a,**kw):return {'passed':False,'status':'unverified','reason':'box_validation_budget_exhausted','box_id':'A'}
        with self.assertRaisesRegex(RobotPlanningIncomplete,'尚未通过'):
            _validated_sequence([self.a],self.pallet,PaperConfig(),self.approach,BudgetVerifier())

    def test_path_budget_is_shared_between_ik_and_rrt(self):
        from types import SimpleNamespace
        from ananno_phase2.robot_offline import OfflineRobotVerifier
        verifier=OfflineRobotVerifier.__new__(OfflineRobotVerifier);verifier.path_seconds=1.;verifier.resolution=.035
        clock=[0.]
        def ik(*args,**kwargs):clock[0]+=.8;return np.ones(6)
        verifier.robot=SimpleNamespace(valid=lambda q:True,ik=ik,lower=-np.ones(6),upper=np.ones(6))
        def rrt(*args,**kwargs):
            self.assertAlmostEqual(kwargs['seconds'],.2)
            return [np.zeros(6).tolist(),np.ones(6).tolist()]
        with patch('ananno_phase2.robot_offline.time.monotonic',side_effect=lambda:clock[0]),patch('ananno_phase2.robot_offline.rrt_connect',side_effect=rrt):
            path,reason=verifier._move(np.zeros(6),np.eye(4))
        self.assertIsNotNone(path)

    def test_cancelled_verification_never_uses_cached_success(self):
        self.v.verify([self.a],self.pallet,self.approach)
        with self.assertRaises(InterruptedError):
            self.v.verify([self.a],self.pallet,self.approach,cancelled=lambda:True)

if __name__=='__main__':unittest.main()
