"""Exercise the GUI startup in a fresh process, without pre-importing MuJoCo."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkcellStartupTests(unittest.TestCase):
    def test_workcell_button_opens_editor_in_fresh_gui_process(self):
        code = textwrap.dedent('''
            from pathlib import Path
            from unittest.mock import patch
            from ananno_phase2.qt_workbench_2025 import RobotWorkbench, W
            root = Path.cwd()
            app = W.QApplication.instance() or W.QApplication([])
            warnings = []
            opened = []
            def inspect_editor(editor):
                opened.append(editor.state.config['robot_id'])
                editor.show()
                app.processEvents()
                assert editor.canvas.isVisible()
                editor.reject()
                return W.QDialog.Rejected
            window = RobotWorkbench(root, restore_workcell=False)
            try:
                with patch.object(W.QMessageBox, 'warning', side_effect=lambda *args: warnings.append(args[-1])):
                    with patch.object(W.QDialog, 'exec_', inspect_editor):
                        window.workcell_button.click()
                assert not warnings, warnings
                assert opened == ['ec66'], opened
                print('WORKCELL_OPENED')
            finally:
                window.close()
        ''')
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONIOENCODING='utf-8')
        env['PYTHONPATH'] = str(ROOT/'src')
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('WORKCELL_OPENED', result.stdout)


if __name__ == '__main__':
    unittest.main()
