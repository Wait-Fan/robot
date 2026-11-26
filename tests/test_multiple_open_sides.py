import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from types import SimpleNamespace

from ananno_phase2.robot_offline import OfflineRobotVerifier
from PyQt5 import QtCore as C, QtWidgets as W
from ananno_phase2.robot_approach import ApproachConfig, OpenDirectionModel, executable_sequence
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2.models import Pallet
from ananno_phase2.robot_pipeline import RobotTwoPhasePacker
from ananno_phase2.qt_workbench_2025 import RobotWorkbench
from tests.test_robot_2025 import item

ROOT = Path(__file__).resolve().parents[1]
APP = W.QApplication.instance() or W.QApplication([])


def fake_verifier():
    import numpy as np
    verifier = OfflineRobotVerifier.__new__(OfflineRobotVerifier)
    verifier.scale=.001; verifier.distance=.002; verifier.resolution=.035
    verifier.path_seconds=1.; verifier.path=ROOT/'examples/ec66_scene_demo.json'
    verifier.base_pallet=np.eye(4); verifier.pick=np.eye(4); verifier.grasp_rotation=np.eye(3)
    verifier.tcp_offset=np.zeros(3); verifier.initial=np.zeros(6); verifier.acceleration=np.ones(6)
    verifier.obstacles=[]; verifier.config={'sequence_budget_seconds':10}
    verifier.cache={}; verifier.calls=0; verifier.model_fingerprint='test'
    verifier.robot=SimpleNamespace(attachment=None, velocity=np.ones(6), names=list('abcdef'),
        valid=lambda q:True, fk=lambda q:np.eye(4), set_obstacles=lambda boxes:None)
    verifier.robot.obstacles=[]
    verifier.robot.set_obstacles=lambda boxes:setattr(verifier.robot,"obstacles",list(boxes))
    return verifier


class MultipleSideTests(unittest.TestCase):
    def test_configuration_validates_nonempty_alternatives(self):
        cfg = ApproachConfig(open_directions=['-X', '+X', '-X'])
        self.assertEqual(cfg.open_directions, ('-X', '+X'))
        self.assertEqual(ApproachConfig('-X').open_directions, ('-X',))
        for invalid in ([], ['-Z'], ['+Z', 'bad']):
            with self.assertRaises(ValueError):
                ApproachConfig(open_directions=invalid)

    def test_available_sides_are_alternatives_not_a_union_of_blockers(self):
        model = OpenDirectionModel(ApproachConfig(open_directions=['+X', '-X']))
        a = item('A', x=1)
        self.assertEqual(model.available_directions(a, [item('R', x=2)]), ['-X'])
        self.assertEqual(model.available_directions(a, [item('L'), item('R', x=2)]), [])

    def test_sequence_can_use_a_different_side_for_each_box(self):
        cfg = ApproachConfig(open_directions=['-X', '+X'])
        ordered, audit = executable_sequence([item('A'), item('B', x=1, order=2)],
                                              Pallet(3, 1, 1), PaperConfig(), cfg)
        self.assertIsNotNone(ordered)
        self.assertTrue(audit['passed'])
        self.assertEqual(audit['open_directions'], ['-X', '+X'])
        self.assertEqual([c['open_direction'] for c in audit['checks']], ['-X', '+X'])

    def test_ga_accepts_layout_rejected_by_a_single_side(self):
        boxes = [item('A').box, item('B').box]
        config = replace(PaperConfig(), population_size=4, mu=4, lambda_=4,
                         generations=2, max_stagnation=1, max_pallets=1)
        packer = RobotTwoPhasePacker(Pallet(3, 1, 1), config,
                                    ApproachConfig(open_directions=['-X', '+X']))
        self.assertEqual(packer.pack(boxes).pallet_count, 1)
        self.assertEqual(len(packer.robot_diagnostics['checks']), 2)

    def test_sequence_backtracks_when_outer_boxes_block_the_middle(self):
        ordered,audit=executable_sequence([item('A'),item('C',x=2,order=2),item('B',x=1,order=3)],
            Pallet(3,1,1),PaperConfig(),ApproachConfig(open_directions=['-X','+X']))
        self.assertTrue(audit['passed'],audit)
        self.assertEqual([p.box.id for p in ordered],['A','B','C'])
        self.assertGreater(audit['search_states'],3)

    def test_cancel_and_old_result_identity(self):
        from ananno_phase2.packer import PackingCancelled
        with self.assertRaises(PackingCancelled):
            executable_sequence([item('A')],Pallet(1,1,1),PaperConfig(),
                ApproachConfig(open_directions=['+Z','-X']),cancelled=lambda:True)
        window=RobotWorkbench(ROOT,restore_workcell=False)
        try:
            window.approach_direction='-X'
            window.document={'robot_diagnostics':{'passed':True,'open_direction':'-X'}}
            window._result_identity()
            self.assertNotIn('来向已改',window.mode_banner.text())
            window.approach_directions=('-X','+Z');window._mode_changed()
            self.assertIn('来向已改',window.mode_banner.text())
            C.QTimer.singleShot(0,lambda:APP.activeModalWidget().reject())
            window.show_settings()
            self.assertEqual(window.approach_directions,('-X','+Z'))
        finally:
            window.close();window.deleteLater();APP.processEvents()

    def test_settings_use_checkboxes_and_require_at_least_one(self):
        window = RobotWorkbench(ROOT,restore_workcell=False)
        failures = []
        def interact():
            try:
                dialog = APP.activeModalWidget()
                checkboxes = {b.property('direction'): b for b in dialog.findChildren(W.QCheckBox)
                              if b.property('direction')}
                self.assertEqual(set(checkboxes), {'+Z', '+X', '-X', '+Y', '-Y'})
                controls = dialog.findChild(W.QDialogButtonBox)
                for b in checkboxes.values(): b.setChecked(False)
                self.assertFalse(controls.button(W.QDialogButtonBox.Ok).isEnabled())
                checkboxes['-X'].setChecked(True); checkboxes['+Y'].setChecked(True)
                self.assertTrue(controls.button(W.QDialogButtonBox.Ok).isEnabled())
                controls.button(W.QDialogButtonBox.Ok).click()
            except BaseException as exc:
                failures.append(exc)
                if APP.activeModalWidget(): APP.activeModalWidget().reject()
        try:
            C.QTimer.singleShot(0, interact)
            window.show_settings()
            if failures: raise failures[0]
            self.assertEqual(set(window._job_options()['approach_config'].open_directions), {'-X', '+Y'})
            self.assertIn('-X', window.method_note.text())
            self.assertIn('+Y', window.method_note.text())
        finally:
            window.close(); window.deleteLater(); APP.processEvents()

    def test_cli_accepts_repeated_direction_arguments(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'plan.json'
            result = subprocess.run([sys.executable, str(ROOT/'main.py'), '--algorithm', 'robot2025',
                '--open-direction=-X', '--open-direction=+X', '--input-json', str(ROOT/'examples/paper_two_phase.json'),
                '--output-json', str(path), '--output-csv', str(Path(td)/'positions.csv'), '--no-show'],
                capture_output=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stderr)
            audit = json.loads(path.read_text(encoding='utf-8'))['robot_diagnostics']
            self.assertEqual(audit['open_directions'], ['-X', '+X'])

    def test_offline_retries_after_failed_place_and_restores_state(self):
        import numpy as np
        from ananno_phase2.robot_offline import OfflineRobotVerifier
        verifier=fake_verifier()
        second_side_starts=[]
        def move(start,target,*,linear=False,cancelled=None):
            end=np.asarray(start).copy()
            if not linear and np.isclose(target[2,3],.012): end[0]=.01
            if linear and np.isclose(target[2,3],.01) and start[0]>.005:
                return None, 'first_side_place_failed'
            if not linear and np.isclose(target[0,3],.003):
                second_side_starts.append(float(start[0]))
            return [list(start),end.tolist()], ''
        verifier._move=move
        single=verifier.verify([item('A',l=10,w=10,h=10)],Pallet(10,10,10),ApproachConfig('+Z'))
        self.assertFalse(single['passed'])
        audit=verifier.verify([item('A',l=10,w=10,h=10)],Pallet(10,10,10),
                             ApproachConfig(open_directions=['+Z','-X']))
        self.assertTrue(audit['passed'],audit)
        self.assertEqual(second_side_starts,[0.])
        self.assertEqual(len(audit['stages']),6)
        self.assertEqual(audit['directions_by_box'][0]['open_direction'],'-X')
        self.assertFalse(audit['hardware_verified'])
        self.assertEqual(verifier.calls,2)


    def test_offline_retries_after_detach_and_failed_retreat(self):
        import numpy as np
        verifier=fake_verifier();second_side_starts=[]
        def move(start,target,*,linear=False,cancelled=None):
            end=np.asarray(start).copy()
            if not linear and np.isclose(target[2,3],.012):end[0]=.01
            if linear and np.isclose(target[2,3],.012) and start[0]>.005:
                self.assertIsNone(verifier.robot.attachment)
                self.assertIn('placed_A',[o['id'] for o in verifier.robot.obstacles])
                return None,'first_side_retreat_failed'
            if not linear and np.isclose(target[0,3],.003):
                second_side_starts.append(float(start[0]))
                self.assertNotIn('placed_A',[o['id'] for o in verifier.robot.obstacles])
                self.assertIsNotNone(verifier.robot.attachment)
            return [list(start),end.tolist()],''
        verifier._move=move
        audit=verifier.verify([item('A',l=10,w=10,h=10)],Pallet(10,10,10),
            ApproachConfig(open_directions=['+Z','-X']))
        self.assertTrue(audit['passed'],audit)
        self.assertEqual(second_side_starts,[0.])
        self.assertEqual(len(audit['stages']),6)
        self.assertEqual([o['id'] for o in verifier.robot.obstacles],['pallet','placed_A'])
        self.assertEqual(audit['directions_by_box'][0]['attempts'][0]['reason'],'first_side_retreat_failed')
        self.assertEqual(audit['directions_by_box'][0]['open_direction'],'-X')


if __name__ == '__main__': unittest.main()
