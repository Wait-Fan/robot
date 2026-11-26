"""Deterministic recovery regressions, no full packing or robot trial."""
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import patch
import numpy as np


class OriginalPathRecoveryTests(unittest.TestCase):
    def test_recover_original_route_when_shortcut_violates_corridor(self):
        from ananno_phase2.joint_trajectory import smooth_trajectory,evaluate_segment
        path=[[0,0],[0,1],[1,1]];details={}
        corridor=lambda q,a,b:abs(a[0]-b[0])<1e-9 or abs(a[1]-b[1])<1e-9
        points=smooth_trajectory(path,np.ones(2),np.ones(2),lambda q:True,
            lower=-np.ones(2),upper=np.ones(2)*2,segment_valid=corridor,diagnostics=details)
        self.assertTrue(details['fallback_used']);self.assertEqual(details['path_source'],'original')
        self.assertEqual(len(points),3)
        for a,b in zip(points,points[1:]):
            for u in np.linspace(0,1,25):self.assertTrue(corridor(evaluate_segment(a,b,u)[0],np.array(a['positions']),np.array(b['positions'])))

    def test_no_unsafe_original_fallback_and_failure_is_categorized(self):
        from ananno_phase2.joint_trajectory import smooth_trajectory,TrajectoryValidationError
        with self.assertRaises(TrajectoryValidationError) as caught:
            smooth_trajectory([[0,0],[1,1]],np.ones(2),np.ones(2),lambda q:not(.3<q[0]<.7),
                              lower=-np.ones(2),upper=np.ones(2)*2)
        self.assertIn('collision',{d['category'] for d in caught.exception.details['failures']})


class LocalRetryTests(unittest.TestCase):
    def fixture(self):
        from tests.test_multiple_open_sides import fake_verifier
        from tests.test_side_direct_approach import pose_robot
        from tests.test_robot_2025 import item
        from ananno_phase2.robot_approach import ApproachConfig
        from ananno_phase2.models import Pallet
        v=fake_verifier();calls,original=pose_robot(v);v.config['local_motion_retries']=2
        return v,calls,original,[item('A',l=10,w=10,h=10)],Pallet(10,10,10),ApproachConfig('+Z')

    def test_retry_current_stage_from_same_start_before_returning_pallet(self):
        v,calls,original,items,pallet,approach=self.fixture();starts=[]
        def flaky(start,target,**kw):
            starts.append(np.asarray(start).copy())
            if len(starts)==1:return None,'path_budget_exhausted'
            return original(start,target,**kw)
        v._move=flaky
        report=v.verify(items,pallet,approach)
        self.assertTrue(report['passed'],report)
        self.assertEqual(len(report['stages']),6)
        np.testing.assert_array_equal(starts[0],starts[1])
        self.assertEqual(len(report['stages'][0]['planning_attempts']),2)

    def test_failed_smoothing_replans_locally_without_duplicating_stage(self):
        v,calls,original,items,pallet,approach=self.fixture();timed=v._timed;count=[0]
        def timing(path,**kw):
            count[0]+=1
            if count[0]==1:raise ValueError('test_curve_failure')
            return timed(path,**kw)
        v._timed=timing
        report=v.verify(items,pallet,approach)
        self.assertTrue(report['passed']);self.assertEqual(len(report['stages']),6)
        self.assertEqual(len(calls),7)

    def test_exhausted_retries_write_pending_diagnostic_not_success(self):
        v,calls,original,items,pallet,approach=self.fixture();count=[0]
        def blocked(start,target,**kw):
            count[0]+=1;return None,'path_budget_exhausted'
        v._move=blocked
        with tempfile.TemporaryDirectory() as folder:
            v.diagnostics_dir=Path(folder)
            report=v.verify(items,pallet,approach)
            self.assertFalse(report['passed']);self.assertEqual(report['status'],'unverified');self.assertEqual(count[0],3)
            saved=json.loads(Path(report['diagnostic_file']).read_text(encoding='utf-8'))
            self.assertFalse(saved['passed']);self.assertEqual(saved['failed_operation'],'approach_pick')
            self.assertEqual(len(saved['failure_diagnostics']['attempts']),3)
            self.assertFalse(v.cache);self.assertFalse(v.pallet_cache)

    def test_retry_changes_ik_and_rrt_seed_and_excludes_failed_goal_branch(self):
        v,calls,original,items,pallet,approach=self.fixture()
        from ananno_phase2.robot_offline import OfflineRobotVerifier
        del v._move
        v.robot.lower=-np.ones(6)*3;v.robot.upper=np.ones(6)*3;seen=[];seeds=[]
        def ik(target,seed,**kw):
            seen.append(kw);return np.ones(6)*(.1 if len(seen)==1 else .2)
        v.robot.ik=ik
        def rrt(start,goal,*args,**kw):
            seeds.append(kw['seed']);return None if len(seeds)==1 else [list(start),list(goal)]
        with patch('ananno_phase2.robot_offline.rrt_connect',side_effect=rrt):
            path,trajectory,reason,details=v._plan_stage(np.zeros(6),np.eye(4),linear=False,cancelled=None)
        self.assertIsNotNone(path,reason);self.assertEqual(len(seeds),2);self.assertNotEqual(seeds[0],seeds[1])
        self.assertEqual(len(seen[1]['exclude_solutions']),1)

    def test_only_usable_ik_branch_can_be_retried_with_new_rrt_seed(self):
        v,calls,original,items,pallet,approach=self.fixture();del v._move
        v.robot.lower=-np.ones(6)*3;v.robot.upper=np.ones(6)*3
        v.robot.ik=lambda target,seed,**kw:None if kw.get('exclude_solutions') else np.ones(6)*.1
        seeds=[]
        def rrt(start,goal,*a,**kw):
            seeds.append(kw['seed']);return None if len(seeds)==1 else [list(start),list(goal)]
        with patch('ananno_phase2.robot_offline.rrt_connect',side_effect=rrt):
            path,trajectory,reason,details=v._plan_stage(np.zeros(6),np.eye(4))
        self.assertIsNotNone(trajectory,reason);self.assertEqual(seeds,[1,2])
        self.assertEqual(details['attempts'][1]['planning']['goal_source'],'retained_verified_ik_branch')

    def test_later_ik_failure_does_not_erase_earlier_unsmoothed_path(self):
        v,calls,original,items,pallet,approach=self.fixture();count=[0]
        candidate=[[0.]*6,[.1]*6]
        def motion(*a,**kw):
            count[0]+=1;return (candidate,'') if count[0]==1 else (None,'ik_search_exhausted')
        v._move=motion;v._timed=lambda *a,**kw:(_ for _ in ()).throw(ValueError('curve_collision'))
        path,trajectory,reason,details=v._plan_stage(np.zeros(6),np.eye(4))
        self.assertIsNone(trajectory);self.assertEqual(details['attempts'][0]['candidate_path'],candidate)

    def test_console_summary_does_not_render_entire_candidate_path(self):
        v,calls,original,items,pallet,approach=self.fixture();messages=[];v.set_log_callback(messages.append)
        v._move=lambda *a,**kw:([[0.]*6]*1000,'')
        v._timed=lambda *a,**kw:(_ for _ in ()).throw(ValueError('curve_collision'))
        v._plan_stage(np.zeros(6),np.eye(4))
        self.assertTrue(messages);self.assertTrue(all('candidate_path' not in line and len(line)<1000 for line in messages))

    def test_cancel_or_box_budget_interrupts_retry_loop(self):
        v,calls,original,items,pallet,approach=self.fixture();count=[0]
        def cancel():count[0]+=1;return count[0]>1
        v._move=lambda *a,**kw:(None,'path_budget_exhausted')
        with self.assertRaises(InterruptedError):v._plan_stage(np.zeros(6),np.eye(4),linear=False,cancelled=cancel)


class PendingPlanningTests(unittest.TestCase):
    def test_pending_checkpoint_keeps_prior_verified_pallet_and_unvisited_cache_hit(self):
        from tests.test_multiple_open_sides import fake_verifier
        from tests.test_side_direct_approach import pose_robot
        from tests.test_robot_2025 import item
        from ananno_phase2.robot_approach import ApproachConfig
        from ananno_phase2.models import Pallet
        from dataclasses import replace
        v=fake_verifier();calls,original=pose_robot(v);pallet=Pallet(10,10,10);approach=ApproachConfig()
        a=item('A',l=10,w=10,h=10);b=replace(item('B',l=10,w=10,h=10),pallet_index=1)
        with tempfile.TemporaryDirectory() as folder:
            v.diagnostics_dir=Path(folder);self.assertTrue(v.verify([a],pallet,approach)['passed'])
            v._move=lambda *args,**kw:(None,'path_budget_exhausted')
            report=v.verify([a,b],pallet,approach)
            self.assertFalse(report['passed']);self.assertEqual(report['current_candidate_verified_pallets'],[1])
            self.assertEqual(len(report['verified_pallet_checkpoints']),1)
            checkpoint=json.loads(Path(report['verified_pallet_checkpoints'][0]).read_text(encoding='utf-8'))
            self.assertFalse(checkpoint['packing_completed']);self.assertTrue(checkpoint['motion_verification']['passed'])
            self.assertEqual([p['box_id'] for p in checkpoint['placements']],['A'])
            saved=json.loads(Path(report['diagnostic_file']).read_text(encoding='utf-8'))
            self.assertEqual(saved['verified_pallet_checkpoints'],report['verified_pallet_checkpoints'])

    def test_worker_emits_pending_instead_of_failure_or_completed_result(self):
        import threading
        from ananno_phase2.qt_workbench_2025 import W
        from ananno_phase2.qt_workbench import PackingWorker
        from ananno_phase2.run_control import RobotPlanningIncomplete
        app=W.QApplication.instance() or W.QApplication([])
        worker=PackingWorker((),{},threading.Event());pending=[];fail=[];results=[]
        worker.pending.connect(pending.append);worker.failed.connect(fail.append);worker.result.connect(results.append)
        with patch('ananno_phase2.qt_workbench.run_packing_job',side_effect=RobotPlanningIncomplete('test local pending')):worker.run()
        self.assertEqual(pending,['test local pending']);self.assertEqual(fail,[]);self.assertEqual(results,[]);self.assertFalse(worker.completed.is_set())

    def test_retry_control_defaults_and_saves(self):
        from ananno_phase2.qt_workbench_2025 import W
        from ananno_phase2.workcell_editor import WorkcellEditor
        app=W.QApplication.instance() or W.QApplication([])
        editor=WorkcellEditor(Path(__file__).resolve().parents[1])
        try:
            self.assertEqual(editor.local_retries.value(),2);editor.local_retries.setValue(1)
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'scene.json';editor.save_scene(path)
                self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['local_motion_retries'],1)
        finally:editor.close();editor.deleteLater();app.processEvents()

    def test_unverified_path_is_not_returned_as_rejected_ga_candidate(self):
        from ananno_phase2.robot_pipeline import _validated_sequence
        from ananno_phase2.run_control import RobotPlanningIncomplete
        from ananno_phase2.models import Pallet
        from ananno_phase2.paper_config import PaperConfig
        from ananno_phase2.robot_approach import ApproachConfig
        from tests.test_robot_2025 import item
        v=SimpleNamespace(verify=lambda *a,**kw:{'passed':False,'status':'unverified','reason':'path_budget_exhausted','box_id':'A'})
        with self.assertRaises(RobotPlanningIncomplete):
            _validated_sequence([item('A')],Pallet(1,1,1),PaperConfig(),ApproachConfig(),v)

    def test_monitor_records_pending_separately_from_timeout_and_complete(self):
        from ananno_phase2.run_control import JobMonitor,RobotPlanningIncomplete
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RobotPlanningIncomplete):
                with JobMonitor(folder) as monitor:
                    monitor.log('test');raise RobotPlanningIncomplete('local search unknown')
            status=json.loads((Path(folder)/'run_status.json').read_text(encoding='utf-8'))
            self.assertEqual(status['status'],'validation_pending');self.assertFalse(status['completed'])


class IKDiagnosisTests(unittest.TestCase):
    def robot(self):
        from ananno_phase2.ec66_model import EC66Model
        v=EC66Model.__new__(EC66Model);v.lower=-np.ones(6);v.upper=np.ones(6)
        v._ik_cache=OrderedDict();v.ik_cache_hits=0;v.fk=lambda q:np.eye(4)
        v.collisions=lambda q:[['tool','neighbor']];v.valid=lambda q:False
        return v

    def test_converged_but_colliding_is_distinct_from_no_ik_solution_found(self):
        v=self.robot();self.assertIsNone(v.ik(np.eye(4),np.zeros(6),restarts=0))
        self.assertEqual(v.last_ik_diagnostics['status'],'converged_in_collision')
        self.assertEqual(v.last_ik_diagnostics['collision_pairs'],[['tool','neighbor']])
        self.assertIsNone(v.ik(np.eye(4),np.zeros(6),iterations=0,restarts=0))
        self.assertEqual(v.last_ik_diagnostics['status'],'search_exhausted')

if __name__=='__main__':unittest.main()
