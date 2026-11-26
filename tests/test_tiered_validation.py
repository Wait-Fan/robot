from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ananno_phase2.paper_ga import TypeEvaluation,optimize_types
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2.models import Box,Pallet
from ananno_phase2.robot_pipeline import RobotTwoPhasePacker


class TieredValidationTests(unittest.TestCase):
    def test_ranked_candidates_are_fully_checked_until_verified(self):
        groups={name:[Box(name,1,1,1,1,name)] for name in 'ABC'}
        cfg=replace(PaperConfig(),population_size=10,mu=10,lambda_=2,generations=1)
        checked=[]
        def evaluator(sequence):return TypeEvaluation(True,1,10 if sequence==['A','B','C'] else 1,sequence)
        def validator(evaluation):
            checked.append(evaluation.payload)
            return replace(evaluation,feasible=evaluation.payload!=['A','B','C'])
        result=optimize_types(groups,evaluator,cfg,validate_candidate=validator,validation_batch_size=1)
        self.assertEqual(checked[0],['A','B','C']);self.assertGreaterEqual(len(checked),2)
        self.assertTrue(result.best.feasible);self.assertNotEqual(result.best.payload,['A','B','C'])

    def test_no_screened_result_is_published_when_every_finalist_fails(self):
        cfg=replace(PaperConfig(),population_size=2,mu=2,lambda_=2,generations=1)
        result=optimize_types({'A':[Box('A',1,1,1)]},lambda _:TypeEvaluation(True,1,1),cfg,
            validate_candidate=lambda _:TypeEvaluation(False,float('inf'),-1))
        self.assertIsNone(result.best)

    def test_real_endpoint_screen_never_claims_joint_path_verified(self):
        from tests.test_ec66_sequence import scene_config
        from tests.test_robot_2025 import item
        from ananno_phase2.robot_offline import OfflineRobotVerifier
        from ananno_phase2.robot_approach import ApproachConfig
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scene.json';path.write_text(json.dumps(scene_config()),encoding='utf-8')
            verifier=OfflineRobotVerifier(path)
            with patch.object(verifier,'_move',side_effect=AssertionError('screen must not plan paths')):
                audit=verifier.screen([item('A',l=10,w=10,h=10)],Pallet(10,10,10),ApproachConfig())
            self.assertEqual(audit['status'],'screened');self.assertFalse(audit['joint_path_verified'])
            self.assertTrue(audit['requires_full_validation']);self.assertFalse(verifier.cache)

    def test_uncertain_ik_is_kept_pending_not_rejected_by_screen(self):
        from tests.test_ec66_sequence import scene_config
        from tests.test_robot_2025 import item
        from ananno_phase2.robot_offline import OfflineRobotVerifier
        from ananno_phase2.robot_approach import ApproachConfig
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scene.json';path.write_text(json.dumps(scene_config()),encoding='utf-8')
            verifier=OfflineRobotVerifier(path)
            with patch.object(verifier.robot,'ik',return_value=None):
                audit=verifier.screen([item('A',l=10,w=10,h=10)],Pallet(10,10,10),ApproachConfig())
            self.assertTrue(audit['passed']);self.assertEqual(audit['pending_boxes'],1)

    def test_ga_screen_and_final_verifier_are_separate(self):
        class Verifier:
            tiered_validation=True;config={'robot_name':'fake','full_validation_batch_size':1}
            def __init__(self):self.screens=0;self.full=0
            def screen(self,*a,**kw):self.screens+=1;return {'passed':True,'status':'screened'}
            def verify(self,*a,**kw):self.full+=1;return {'passed':True,'status':'verified','assumptions':[]}
        v=Verifier();cfg=replace(PaperConfig(),population_size=2,mu=2,lambda_=2,generations=1,max_pallets=1)
        packer=RobotTwoPhasePacker(Pallet(3,1,1),cfg,robot_verifier=v)
        result=packer.pack([Box('A',1,1,1),Box('B',1,1,1)])
        self.assertEqual(len(result.placements),2);self.assertGreater(v.screens,0)
        self.assertGreater(v.full,0);self.assertTrue(packer.robot_diagnostics['ik_verified'])

if __name__=='__main__':unittest.main()

