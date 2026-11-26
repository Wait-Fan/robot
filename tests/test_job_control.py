import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ananno_phase2.workbench_service import run_packing_job
from ananno_phase2.packer import PackingCancelled


class JobControlTests(unittest.TestCase):
    def test_timeout_is_distinct_from_cancel_and_writes_status_without_plan(self):
        from ananno_phase2.run_control import PackingTimedOut
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'boxes.csv';source.write_text('id,length,width,height\nA,1,1,1\n')
            def expensive(self,boxes,*,progress=None,cancelled=None,**kwargs):
                while True:
                    cancelled();time.sleep(.005)
            with patch('ananno_phase2.workbench_service.FixedSequencePacker.pack',expensive):
                with self.assertRaises(PackingTimedOut):
                    run_packing_job(source,'全部箱子',2,2,2,1,root/'out',max_seconds=.05)
            state=json.loads((root/'out/run_status.json').read_text(encoding='utf-8'))
            self.assertEqual(state['status'],'timed_out')
            self.assertFalse(state['completed'])
            self.assertEqual(list((root/'out').glob('*_plan.json')),[])
            self.assertIn('未完成',(root/'out/run.log').read_text(encoding='utf-8'))

    def test_success_persists_input_budget_and_completion(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'boxes.csv';source.write_text('id,length,width,height\nA,1,1,1\n')
            result=run_packing_job(source,'全部箱子',2,2,2,1,root/'out',max_seconds=60)
            state=json.loads((root/'out/run_status.json').read_text(encoding='utf-8'))
            self.assertEqual(state['status'],'completed');self.assertTrue(state['completed'])
            self.assertEqual(state['max_seconds'],60)
            self.assertEqual(Path(state['request']['dataset']),source)
            self.assertTrue(result['paths']['json'].exists())

    def test_cancel_and_failure_are_persisted_separately(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'boxes.csv';source.write_text('id,length,width,height\nA,1,1,1\n')
            for mode in ('cancelled','failed'):
                def fail(*args,**kwargs):
                    if mode=='cancelled':raise PackingCancelled('stop')
                    raise RuntimeError('probe error')
                with self.subTest(mode=mode),patch('ananno_phase2.workbench_service.FixedSequencePacker.pack',fail):
                    with self.assertRaises((PackingCancelled,RuntimeError)):
                        run_packing_job(source,'全部箱子',2,2,2,1,root/mode,max_seconds=60)
                    state=json.loads((root/mode/'run_status.json').read_text(encoding='utf-8'))
                    self.assertEqual(state['status'],mode)

    def test_heartbeat_persists_while_evaluation_is_waiting(self):
        from ananno_phase2.run_control import JobMonitor
        with tempfile.TemporaryDirectory() as td:
            with JobMonitor(td,max_seconds=2,heartbeat_seconds=.02) as monitor:
                monitor.log('GA 候选：1/100，开始')
                time.sleep(.07)
                state=json.loads((Path(td)/'run_status.json').read_text(encoding='utf-8'))
                self.assertEqual(state['status'],'running')
                self.assertGreater(state['elapsed_seconds'],.02)
                self.assertIn('GA 候选',state['last_event'])
            self.assertEqual(json.loads((Path(td)/'run_status.json').read_text(encoding='utf-8'))['status'],'completed')

    def test_ga_reports_candidate_before_entering_slow_evaluator(self):
        from dataclasses import replace
        from ananno_phase2.paper_ga import optimize_types,TypeEvaluation
        from ananno_phase2.paper_config import PaperConfig
        from ananno_phase2.models import Box
        messages=[];seen=[]
        def evaluator(sequence):
            seen.append(any('候选' in message and '开始' in message for message in messages))
            return TypeEvaluation(True,1.,1.,None)
        cfg=replace(PaperConfig(),population_size=2,mu=2,lambda_=2,generations=1,max_stagnation=1)
        optimize_types({'A':[Box('A',1,1,1)]},evaluator,cfg,log=messages.append)
        self.assertTrue(seen);self.assertTrue(all(seen))

    def test_total_deadline_interrupts_ga_initial_population(self):
        from dataclasses import replace
        from ananno_phase2.run_control import JobMonitor,PackingTimedOut
        from ananno_phase2.paper_ga import optimize_types,TypeEvaluation
        from ananno_phase2.paper_config import PaperConfig
        from ananno_phase2.models import Box
        evaluations=[]
        def evaluate(sequence):
            evaluations.append(sequence);time.sleep(.03);return TypeEvaluation(False,float('inf'),-1,None)
        cfg=replace(PaperConfig(),population_size=40,mu=10,lambda_=10,generations=10,max_stagnation=2)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(PackingTimedOut):
                with JobMonitor(td,max_seconds=.15) as monitor:
                    optimize_types({key:[Box(key,1,1,1,1,key)] for key in 'ABCD'},evaluate,cfg,
                        log=monitor.log,cancelled=monitor.cancelled)
            self.assertLess(len(evaluations),24)
            self.assertEqual(json.loads((Path(td)/'run_status.json').read_text(encoding='utf-8'))['status'],'timed_out')

    def test_gui_timeout_keeps_history_and_default_budget_is_sixty_minutes(self):
        from ananno_phase2.run_control import PackingTimedOut
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench,W
        app=W.QApplication.instance() or W.QApplication([])
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'boxes.csv';source.write_text('id,length,width,height\nA,1,1,1\n')
            old=run_packing_job(source,'全部箱子',2,2,2,1,root/'history')
            window=RobotWorkbench(root,restore_workcell=False)
            try:
                self.assertEqual(window._job_options()['max_seconds'],3600)
                window.load_result_file(old['paths']['json']);previous=window.document
                window.mode_combo.setCurrentText('基础模式');window.load_input_file(source)
                with patch('ananno_phase2.qt_workbench.run_packing_job',side_effect=PackingTimedOut('测试总时限：本次未完成')):
                    window.start_packing();deadline=time.monotonic()+5
                    while window.running and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
                    app.processEvents();self.assertFalse(window.running)
                self.assertEqual(window.status_label.text(),'已超时（未完成）')
                self.assertIs(window.document,previous)
                self.assertFalse(window._worker)
            finally:
                if window.running:window.stop_packing()
                window.close();window.deleteLater();app.processEvents()

    def test_wrong_evaluator_return_with_logging_preserves_type_error_contract(self):
        from dataclasses import replace
        from ananno_phase2.paper_ga import optimize_types
        from ananno_phase2.paper_config import PaperConfig
        from ananno_phase2.models import Box
        cfg=replace(PaperConfig(),population_size=1,mu=1,lambda_=1,generations=1,max_stagnation=1)
        with self.assertRaises(TypeError):
            optimize_types({'A':[Box('A',1,1,1)]},lambda sequence:object(),cfg,log=lambda message:None)

    def test_robot_failure_reason_is_written_to_progress_log(self):
        from tests.test_multiple_open_sides import fake_verifier
        from tests.test_robot_2025 import item
        from ananno_phase2.robot_approach import ApproachConfig
        from ananno_phase2.models import Pallet
        verifier=fake_verifier();messages=[];verifier.set_log_callback(messages.append)
        verifier._move=lambda *args,**kwargs:(None,'probe_ik_failed')
        report=verifier.verify([item('A')],Pallet(2,2,2),ApproachConfig())
        self.assertFalse(report['passed'])
        self.assertTrue(any('probe_ik_failed' in line for line in messages))

    def test_gui_budget_setting_is_passed_to_background_job(self):
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench,W,C
        from ananno_phase2.qt_workbench import PackingWorkbench
        app=W.QApplication.instance() or W.QApplication([])
        with tempfile.TemporaryDirectory() as td:
            window=RobotWorkbench(Path(td),restore_workcell=False);errors=[]
            def set_budget():
                dialog=app.activeModalWidget()
                try:
                    dialog.findChild(W.QDoubleSpinBox,'maxJobMinutes').setValue(2.5)
                    dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.Ok).click()
                except BaseException as exc:errors.append(exc);dialog.reject()
            try:
                C.QTimer.singleShot(0,set_budget);PackingWorkbench.show_settings(window)
                if errors:raise errors[0]
                self.assertEqual(window._job_options()['max_seconds'],150)
            finally:window.close();window.deleteLater();app.processEvents()

    def test_timeout_during_publication_restores_previous_complete_outputs(self):
        from ananno_phase2.run_control import PackingTimedOut
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'boxes.csv';source.write_text('id,length,width,height\nA,1,1,1\n')
            previous=run_packing_job(source,'全部箱子',2,2,2,1,root/'out')
            content={key:path.read_bytes() for key,path in previous['paths'].items()}
            source.write_text('id,length,width,height\nA,1,1,1\nB,1,1,1\n')
            expired=threading.Event();replace=Path.replace
            def publish_then_expire(path,target):
                value=replace(path,target)
                if path.parent.name.startswith('.packing_') and path.name.endswith('_plan.json'):expired.set()
                return value
            def guard():
                if expired.is_set():raise PackingTimedOut('test publication timeout')
                return False
            with patch.object(Path,'replace',publish_then_expire):
                with self.assertRaises(PackingTimedOut):
                    run_packing_job(source,'全部箱子',2,2,2,1,root/'out',cancelled=guard)
            self.assertEqual({key:path.read_bytes() for key,path in previous['paths'].items()},content)
            self.assertEqual(json.loads((root/'out/run_status.json').read_text(encoding='utf-8'))['status'],'timed_out')


if __name__=='__main__':unittest.main()
