import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ananno_phase2.workbench_service import run_packing_job,PackingCancelled

ROOT=Path(__file__).resolve().parents[1]
APP=None


class BrowseWhilePackingTests(unittest.TestCase):
    def setUp(self):
        global APP
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench,W
        self.W=W;APP=W.QApplication.instance() or W.QApplication([]);self.app=APP
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        old=self.folder/'old.csv';old.write_text('id,length,width,height\nOLD-A,2,2,1\nOLD-B,2,2,1\n')
        self.history_result=run_packing_job(old,'全部箱子',2,2,1,1,self.folder/'history')
        self.source=self.folder/'new.csv';self.source.write_text('id,length,width,height\nNEW-A,2,2,1\n')
        self.window=RobotWorkbench(ROOT,restore_workcell=False);self.window.output_dir=self.folder/'new_results'
        self.window.mode_combo.setCurrentText('基础模式');self.window.load_input_file(self.source)
        self.window.dimensions=['2','2','1']
        self.started=threading.Event();self.release=threading.Event();self.captured=[]
        def controlled_job(*args,**options):
            self.captured.append((args,options.copy()));self.started.set()
            options['progress'](1,4)
            while not self.release.wait(.01):
                if options['cancelled']():raise PackingCancelled()
            return run_packing_job(*args,**options)
        self.patcher=patch('ananno_phase2.qt_workbench.run_packing_job',controlled_job);self.patcher.start()

    def wait_for(self,predicate,seconds=8):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
        self.app.processEvents();self.assertTrue(predicate())

    def start(self):
        self.window.start_packing();self.assertTrue(self.started.wait(2))
        self.wait_for(lambda:self.window.progress_bar.value()==25)

    def tearDown(self):
        self.release.set()
        if self.window.running:self.window.stop_packing();self.wait_for(lambda:not self.window.running)
        self.patcher.stop();self.window.close();self.window.deleteLater();self.app.processEvents();self.temp.cleanup()

    def test_read_only_controls_enabled_and_historical_view_preserves_job_progress(self):
        self.start();window=self.window
        self.assertTrue(window.history.isEnabled());self.assertTrue(window.open_button.isEnabled())
        for control in (window.input_button,window.start_button,window.settings_button,window.mode_combo,window.workcell_button,window.robot_check):
            self.assertFalse(control.isEnabled())
        window.load_result_file(self.history_result['paths']['json'])
        self.assertTrue(window.running);self.assertEqual(window.status_label.text(),'计算中')
        self.assertEqual(window.progress_bar.value(),25)
        self.assertNotIn('未重新计算',window.progress_text.text())
        window.select_pallet(2);self.assertEqual(window.box_table.item(0,2).text(),'OLD-B')
        window.overview_cards[0].play();self.assertTrue(window.overview_cards[0].timer.isActive())
        self.assertEqual(self.captured[0][0][0],self.source)
        self.assertEqual(self.captured[0][0][2:5],(2.,2.,1.))

    def test_completion_keeps_browsed_history_and_offers_new_result(self):
        self.start();window=self.window
        window.load_result_file(self.history_result['paths']['json']);old_document=window.document
        self.release.set();self.wait_for(lambda:not window.running)
        self.assertIs(window.document,old_document)
        self.assertEqual(window.status_label.text(),'已完成')
        self.assertFalse(window.latest_result_button.isHidden())
        window.latest_result_button.click()
        self.assertEqual(window.document['pallets'][0]['packed_items'][0]['id'],'NEW-A')
        self.assertTrue(window.latest_result_button.isHidden())

    def test_no_history_switch_still_automatically_displays_new_result(self):
        self.start();self.release.set();self.wait_for(lambda:not self.window.running)
        self.assertEqual(self.window.document['pallets'][0]['packed_items'][0]['id'],'NEW-A')

    def test_invalid_history_does_not_mark_active_job_failed(self):
        self.start();window=self.window
        invalid=self.folder/'bad.json';invalid.write_text('{}')
        messages=[]
        with patch.object(self.W.QFileDialog,'getOpenFileName',return_value=(str(invalid),'')):
            with patch.object(self.W.QMessageBox,'warning',side_effect=lambda *args:messages.append(args[-1])):
                with patch.object(self.W.QMessageBox,'critical',side_effect=lambda *args:messages.append(args[-1])):
                    window.choose_result()
        self.assertTrue(messages)
        self.assertEqual(window.status_label.text(),'计算中');self.assertEqual(window.progress_bar.value(),25)
        self.assertFalse(window.cancel_event.is_set())

    def test_stop_remains_available_while_viewing_history(self):
        self.start();self.window.load_result_file(self.history_result['paths']['json']);old=self.window.document
        self.window.stop_button.click();self.wait_for(lambda:not self.window.running)
        self.assertEqual(self.window.status_label.text(),'已停止');self.assertIs(self.window.document,old)


if __name__=='__main__':unittest.main()
