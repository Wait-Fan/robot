import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ananno_phase2.models import Box, Pallet, Placement, Point3D
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2.packer import PackingCancelled
from ananno_phase2.robot_approach import ApproachConfig, OpenDirectionModel, executable_sequence
from ananno_phase2.robot_pipeline import RobotTwoPhasePacker
from ananno_phase2.paper_pipeline import PaperTwoPhasePacker
from ananno_phase2.workbench_service import run_packing_job, load_result


def item(name,x=0,y=0,z=0,l=1,w=1,h=1,order=1):
    box=Box(name,l,w,h,1,name)
    return Placement(box,0,Point3D(x,y,z),box.orientations()[0],order)


class Robot2025Tests(unittest.TestCase):
    def setUp(self):
        self.cfg=replace(PaperConfig(),population_size=12,mu=6,lambda_=6,generations=3,max_stagnation=2)

    def test_open_side_blocker_contact_and_other_pallet(self):
        candidate=item('A');right=item('R',x=1);above=item('T',z=1);touch_side=item('Y',y=1)
        self.assertEqual(OpenDirectionModel(ApproachConfig('+X')).blockers(candidate,[right,above,touch_side]),['R'])
        self.assertEqual(OpenDirectionModel(ApproachConfig('+Z')).blockers(candidate,[right,above,touch_side]),['T'])
        self.assertEqual(OpenDirectionModel(ApproachConfig('-X')).blockers(candidate,[right]),[])
        self.assertEqual(OpenDirectionModel(ApproachConfig('+X')).blockers(candidate,[replace(right,pallet_index=1)]),[])
        with self.assertRaises(ValueError):ApproachConfig('-Z')

    def test_reorders_front_back_and_retains_support(self):
        a=item('A',order=1);b=item('B',x=1,order=2);top=item('T',x=1,z=1,order=3)
        ordered,audit=executable_sequence([a,b,top],Pallet(2,1,3),self.cfg,ApproachConfig('-X'))
        self.assertIsNotNone(ordered)
        ids=[p.box.id for p in ordered]
        self.assertLess(ids.index('B'),ids.index('A'))
        self.assertLess(ids.index('B'),ids.index('T'))
        self.assertEqual([p.order for p in ordered],[1,2,3])
        self.assertTrue(audit['passed'])

    def test_invalid_geometry_and_cancellation_are_not_reported_pass(self):
        result,audit=executable_sequence([item('A'),item('B')],Pallet(2,2,2),self.cfg,ApproachConfig())
        self.assertIsNone(result);self.assertFalse(audit['passed'])
        with self.assertRaises(PackingCancelled):
            executable_sequence([item('A')],Pallet(2,2,2),self.cfg,ApproachConfig(),cancelled=lambda:True)

    def test_full_phase1_and_residual_are_audited(self):
        boxes=[Box(f'a{i}',2,2,2,1,'A') for i in range(8)]+[Box('r',1,1,1,1,'B')]
        packer=RobotTwoPhasePacker(Pallet(4,4,6),self.cfg,ApproachConfig('-X'))
        result=packer.pack(boxes)
        self.assertEqual(len(result.placements),9)
        self.assertTrue(packer.robot_diagnostics['passed'])
        self.assertEqual(len(packer.robot_diagnostics['checks']),9)
        self.assertGreater(packer.diagnostics['phase1']['phase1_box_count'],0)
        self.assertGreater(packer.diagnostics['residual_box_count'],0)
        placed=[];model=OpenDirectionModel(ApproachConfig('-X'))
        for p in sorted(result.placements,key=lambda p:p.order):
            self.assertEqual(model.blockers(p,placed),[]);placed.append(p)

    def test_service_publishes_2025_identity_and_baseline_trace(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'boxes.csv';path.write_text('id,length,width,height\nA,1,1,1\nB,1,1,1\n')
            out=run_packing_job(path,'全部箱子',2,1,2,1,Path(td)/'out',algorithm='robot2025',
                                paper_config=self.cfg,approach_config=ApproachConfig('-X'))
            doc=load_result(out['paths']['json'])
            self.assertIn('2025',doc['algorithm'])
            self.assertFalse(doc['is_complete_reproduction'])
            self.assertEqual(doc['robot_diagnostics']['open_direction'],'-X')
            self.assertTrue(doc['robot_diagnostics']['passed'])
            self.assertEqual(doc['provenance']['baseline'],'Ananno2024 staged research implementation v0.4.1')
            self.assertEqual(len(doc['provenance']['manifest_sha256']),64)

    def test_blocked_candidate_is_rejected_inside_ga_before_publication(self):
        boxes=[Box('A',1,1,1,1,'A'),Box('B',1,1,1,1,'B')]
        pallet=Pallet(3,1,1)
        baseline=PaperTwoPhasePacker(pallet,self.cfg).pack(boxes)
        self.assertEqual(baseline.pallet_count,1)
        # 负X来向要求后方B先放，但B不能独立满足旧版角部对齐规则。
        # 本实现同时重放旧规则，因此1盘方案被拒绝；2盘各自角部放置可行。
        packer=RobotTwoPhasePacker(pallet,self.cfg,ApproachConfig('-X'))
        result=packer.pack(boxes)
        self.assertEqual(result.pallet_count,2)
        self.assertGreater(packer.robot_diagnostics['rejected_inside_ga'],0)
        self.assertFalse(packer.diagnostics['ga_attempts'][0]['feasible'])
        self.assertTrue(packer.diagnostics['ga_attempts'][-1]['feasible'])


if __name__=='__main__':unittest.main()
