import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InsideOutUiCliTests(unittest.TestCase):
    def test_auto_workcell_side_and_manual_ui_override_are_sent_to_solver(self):
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench, W, C
        from ananno_phase2.workcell_state import WorkcellState, transform
        app = W.QApplication.instance() or W.QApplication([])
        with tempfile.TemporaryDirectory() as td:
            scene = Path(td)/'scene.json'
            state = WorkcellState.create(ROOT, (2000, 1000, 1400))
            state.pallet_pose = transform((-3, -.5, 0))  # robot at pallet x=3m,y=.5m -> +X
            state.save(scene)
            window = RobotWorkbench(ROOT, restore_workcell=False)
            errors = []
            try:
                window.dimensions = ['2000', '1000', '1400']
                window.apply_workcell(scene)
                window.robot_check.setChecked(False)
                self.assertEqual(window._job_options()['approach_config'].outside_side, '+X')
                def choose_manual():
                    try:
                        dialog = app.activeModalWidget()
                        combo = dialog.findChild(W.QComboBox, 'outsideSideSelector')
                        combo.setCurrentIndex(combo.findData('-Y'))
                        dialog.accept()
                    except BaseException as exc:
                        errors.append(exc)
                        app.activeModalWidget().reject()
                C.QTimer.singleShot(0, choose_manual)
                window.show_settings()
                if errors: raise errors[0]
                self.assertEqual(window._job_options()['approach_config'].outside_side, '-Y')
                self.assertIn('手动', window.method_note.text())
                window.document = {'robot_diagnostics': {'passed': True, 'open_directions': ['+Z'],
                    'sequencing_policy': {'outside_side': '+X'}}}
                window._result_identity()
                self.assertIn('里外基准已改', window.mode_banner.text())
            finally:
                window.close(); window.deleteLater(); app.processEvents()

    def test_missing_workcell_does_not_invent_robot_side(self):
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench, W
        app = W.QApplication.instance() or W.QApplication([])
        window = RobotWorkbench(ROOT, restore_workcell=False)
        try:
            self.assertIsNone(window._job_options()['approach_config'].outside_side)
            self.assertIn('待配置', window._fill_description())
        finally:
            window.close(); window.deleteLater(); app.processEvents()

    def test_cli_manual_side_changes_final_sequence_and_saves_policy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root/'boxes.json'
            source.write_text(json.dumps({'pallet': {'length': 3, 'width': 1, 'height': 1},
                'boxes': [{'box_type': 'A', 'length': 1, 'width': 1, 'height': 1, 'target_num': 3}]}))
            output = root/'plan.json'
            env = dict(os.environ, PYTHONIOENCODING='utf-8')
            result = subprocess.run([sys.executable, str(ROOT/'main.py'), '--algorithm', 'robot2025',
                '--input-json', str(source), '--outside-side=-X', '--output-json', str(output),
                '--output-csv', str(root/'boxes.csv'), '--no-show'], capture_output=True,
                encoding='utf-8', env=env, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            doc = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual([p['position']['x'] for p in doc['pallets'][0]['packed_items']], [2, 1, 0])
            self.assertEqual(doc['robot_diagnostics']['sequencing_policy']['outside_side'], '-X')


if __name__ == '__main__': unittest.main()
