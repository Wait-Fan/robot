import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from PyQt5 import QtWidgets as W
from ananno_phase2.qt_workbench_2025 import RobotWorkbench

APP=W.QApplication.instance() or W.QApplication([])
ROOT=Path(__file__).resolve().parents[1]


class RobotUiCliTests(unittest.TestCase):
    def test_2025_window_runs_new_mode_and_identifies_old_results(self):
        with tempfile.TemporaryDirectory() as td:
            window=RobotWorkbench(ROOT);window.output_dir=Path(td)
            try:
                self.assertIn('2025',window.windowTitle())
                self.assertEqual(window.mode_combo.currentText(),'2025 可达性')
                window.approach_direction='-X'
                window.load_input_file(ROOT/'examples/paper_two_phase.json')
                window.start_packing()
                deadline=time.monotonic()+15
                while window.running and time.monotonic()<deadline:APP.processEvents();time.sleep(.01)
                self.assertFalse(window.running)
                self.assertIsNotNone(window.document)
                self.assertIn('2025',window.document['algorithm'])
                self.assertEqual(window.document['robot_diagnostics']['open_direction'],'-X')
                self.assertIn('2025',window.result_summary.text())
                self.assertIn('未验证',window.result_summary.text())
                window.approach_direction='+Z';window._mode_changed()
                self.assertIn('来向已改，需重新计算',window.mode_banner.text())
                window.mode_combo.setCurrentText('论文两阶段')
                self.assertIn('需重新计算',window.mode_banner.text())
            finally:
                if window.running:
                    window.stop_packing()
                    while window.running:APP.processEvents();time.sleep(.01)
                window.close();window.deleteLater();APP.processEvents()

    def test_cli_new_mode_and_open_direction(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'plan.json'
            result=subprocess.run([sys.executable,str(ROOT/'main.py'),'--algorithm','robot2025','--open-direction=-X',
                '--input-json',str(ROOT/'examples/paper_two_phase.json'),'--output-json',str(out),
                '--output-csv',str(Path(td)/'positions.csv'),'--no-show'],capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            doc=json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(doc['robot_diagnostics']['open_direction'],'-X')
            self.assertEqual(doc['summary']['packed_box_count'],9)


if __name__=='__main__':unittest.main()
