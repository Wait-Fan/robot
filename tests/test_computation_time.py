import contextlib
import io
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ananno_phase2 import workbench_service as service
import main

class ComputationTimeTests(unittest.TestCase):
    def test_solver_time_excludes_input_and_export_and_survives_reload(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root/'boxes.csv'
            source.write_text('id,length,width,height\nA,1,1,1\n')
            for algorithm in ('basic', 'paper', 'robot2025'):
                with self.subTest(algorithm=algorithm):
                    clock = SimpleNamespace(perf_counter=Mock(side_effect=[100, 110, 112.5, 120]))
                    with patch.object(service, 'time', clock):
                        result = service.run_packing_job(source, '全部箱子', 2, 2, 2, 1,
                                                         root/algorithm, algorithm=algorithm)
                    self.assertEqual(result['algorithm_seconds'], 2.5)
                    self.assertEqual(result['elapsed_seconds'], 20)
                    saved = json.loads(result['paths']['json'].read_text(encoding='utf-8'))
                    self.assertEqual(saved['timing']['algorithm_seconds'], 2.5)
                    self.assertEqual(service.load_result(result['paths']['json'])['timing'], saved['timing'])

    def test_robot_window_shows_saved_time_and_handles_legacy_result(self):
        from PyQt5 import QtWidgets as W
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench
        app = W.QApplication.instance() or W.QApplication([])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root/'boxes.csv'
            source.write_text('id,length,width,height\nA,1,1,1\n')
            result = service.run_packing_job(source, '全部箱子', 2, 2, 2, 1, root/'out')
            doc = result['document']
            doc['timing'] = {'algorithm_seconds': 12.345}
            window = RobotWorkbench(root, restore_workcell=False)
            try:
                window.display_document(doc)
                self.assertIn('12.345', window.computation_time.text())
                doc.pop('timing')
                window.display_document(doc)
                self.assertIn('未记录', window.computation_time.text())
            finally:
                window.close()
                window.deleteLater()
                app.processEvents()

    def test_cli_reports_and_saves_solver_time(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for algorithm in ('basic', 'paper', 'robot2025'):
                with self.subTest(algorithm=algorithm):
                    output = root/f'{algorithm}.json'
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        code = main.main(['--algorithm', algorithm, '--no-show',
                                          '--output-json', str(output), '--output-csv', str(root/'boxes.csv')])
                    self.assertEqual(code, 0)
                    self.assertIn('算法计算时间', stdout.getvalue())
                    seconds = json.loads(output.read_text(encoding='utf-8'))['timing']['algorithm_seconds']
                    self.assertGreaterEqual(seconds, 0)
                    self.assertLess(seconds, float('inf'))


if __name__ == '__main__':
    unittest.main()
