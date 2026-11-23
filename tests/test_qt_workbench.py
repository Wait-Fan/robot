import json
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import tempfile
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt5 import QtWidgets as W
from ananno_phase2.qt_workbench import PackingWorkbench
from ananno_phase2.workbench_service import run_packing_job
from ananno_phase2.packer import PackingCancelled

APP=W.QApplication.instance() or W.QApplication([])


class QtWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.window=PackingWorkbench(self.folder)
        self.source=self.folder/"boxes.csv"
        self.source.write_text("id,length,width,height\na,2,2,1\nb,2,2,1\nc,2,2,1\nx,9,9,9\n")

    def tearDown(self):
        if self.window.running:
            self.window.stop_packing()
            self.wait_finished()
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def wait_finished(self):
        deadline=time.monotonic()+15
        while self.window.running and time.monotonic()<deadline:
            APP.processEvents()
            time.sleep(.01)
        APP.processEvents()
        self.assertFalse(self.window.running)

    def test_actual_qt_default_and_basic_worker_output(self):
        self.assertIsInstance(self.window,W.QMainWindow)
        self.assertIn("PyQt5",self.window.windowTitle())
        self.assertEqual(self.window.mode_combo.currentText(),"论文两阶段")
        self.window.mode_combo.setCurrentText("基础模式")
        self.window.dimensions=["2","2","2"]
        self.window.load_input_file(self.source)
        self.window.start_packing()
        self.wait_finished()
        self.assertEqual(self.window.document["summary"]["pallet_count"],2)
        self.assertEqual(self.window.box_table.rowCount(),3)
        self.assertEqual(self.window.unplaced_table.rowCount(),1)
        self.assertEqual(self.window.status_label.text(),"已完成")
        self.window.pallet_filter.setCurrentText("托盘 2")
        self.assertEqual(self.window.box_table.rowCount(),1)
        self.assertEqual(self.window.current_pallet()["pallet_index"],2)

    def test_raw_wcs_runs_paper_with_explicit_settings(self):
        source=self.folder/"raw.json"
        source.write_text(json.dumps({"code":200,"data":[
            {"box_type":"A","length":2,"width":2,"height":1,"weight":1,"target_num":2,"case_type":"MH423C"},
            {"box_type":"B","length":1,"width":1,"height":1,"weight":1,"target_num":1,"case_type":"WR246"}]}))
        self.window.dimensions=["2","2","3"]
        self.window.load_input_file(source)
        self.assertIn("全部读取",self.window.input_summary.text())
        self.window.start_packing()
        self.wait_finished()
        self.assertEqual(self.window.document["summary"]["packed_box_count"],3)
        self.assertTrue(self.window.document["paper_diagnostics"]["all_hard_constraints_pass"])
        self.assertIn("论文两阶段",self.window.result_summary.text())
        self.assertIn("当前结果：论文两阶段",self.window.mode_banner.text())

    def test_choose_excel_autofills_dimensions_and_runs_paper_worker(self):
        from openpyxl import Workbook
        source=self.folder/"boxes.xlsx"
        book=Workbook();sheet=book.active;sheet.title="最终挑选结果"
        sheet.append(["箱子序号","Box类型","实际包装数量","箱子长","箱子宽","箱子高","总重量","托盘长","托盘宽","托盘高"])
        sheet.append([1,"A",92,2,2,1,1,2,2,3])
        sheet.append([2,"A",92,2,2,1,1,2,2,3])
        sheet.append([3,"B",92,1,1,1,1,2,2,3])
        book.save(source);book.close()
        with patch.object(W.QFileDialog,"getOpenFileName",return_value=(str(source),"")) as chooser:
            self.window.choose_input()
        self.assertIn("*.xlsx",chooser.call_args.args[3])
        self.assertEqual(self.window.dimensions,["2.0","2.0","3.0"])
        self.assertFalse(self.window.order_combo.isEnabled())
        self.assertIn("3 箱",self.window.input_summary.text())
        self.window.start_packing();self.wait_finished()
        self.assertEqual(self.window.document["summary"]["packed_box_count"],3)
        self.assertEqual(self.window.document["input_import"]["source_rows"],3)
        self.assertTrue(self.window.document["paper_diagnostics"]["all_hard_constraints_pass"])

    def test_four_per_page_search_and_result_identity(self):
        self.source.write_text("id,length,width,height\n"+"".join(f"B{i},1,1,1\n" for i in range(9)))
        output=run_packing_job(self.source,"全部箱子",1,1,1,1,self.folder/"nine")
        self.window.load_result_file(output["paths"]["json"])
        self.assertEqual(len(self.window.overview_cards),4)
        self.assertEqual(self.window.page_label.text(),"1 / 3")
        self.assertIn("未重新计算",self.window.progress_text.text())
        self.assertIn("需重新计算",self.window.mode_banner.text())
        first=self.window.overview_cards[0]
        first.play()
        self.window.change_page(1)
        self.assertFalse(first.playing)
        self.window.search.setText("B8")
        self.window.apply_filter()
        self.assertEqual(len(self.window.overview_cards),1)
        self.assertEqual(self.window.box_table.rowCount(),1)
        self.assertEqual(self.window.current_pallet()["pallet_index"],9)
        self.window.search.setText("不存在")
        self.window.apply_filter()
        self.assertEqual(self.window.page_label.text(),"0 / 0")
        self.assertIsNone(self.window.current_pallet())

    def test_bad_import_keeps_result_and_cancel_does_not_publish(self):
        output=run_packing_job(self.source,"全部箱子",2,2,4,1,self.folder/"old")
        self.window.load_result_file(output["paths"]["json"])
        previous=self.window.document
        bad=self.folder/"bad.json";bad.write_text('{"bad":1}')
        with self.assertRaises(ValueError): self.window.load_result_file(bad)
        self.assertIs(self.window.document,previous)
        self.window.mode_combo.setCurrentText("基础模式")
        self.window.load_input_file(self.source)
        self.window.start_packing()
        self.window.stop_packing()
        self.wait_finished()
        self.assertIs(self.window.document,previous)
        self.assertEqual(self.window.status_label.text(),"已停止")

    def test_bad_metric_fields_do_not_replace_current_result(self):
        output=run_packing_job(self.source,"全部箱子",2,2,4,1,self.folder/"valid")
        self.window.load_result_file(output["paths"]["json"])
        previous=self.window.document
        previous_path=self.window.result_path
        for key,value in (("weight","bad"),("weight",-1),("box_type",["invalid"])):
            bad=json.loads(json.dumps(previous))
            bad["pallets"][0]["packed_items"][0][key]=value
            path=self.folder/f"bad_{key}.json"
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):self.window.load_result_file(path)
            self.assertIs(self.window.document,previous)
            self.assertEqual(self.window.result_path,previous_path)
            self.assertEqual(self.window.box_table.rowCount(),3)

    def test_close_during_worker_waits_for_cooperative_shutdown(self):
        started=threading.Event()
        def slow_job(*args,cancelled=None,**kwargs):
            started.set()
            while not cancelled():time.sleep(.005)
            raise PackingCancelled()
        self.window.load_input_file(self.source)
        self.window.show()
        with patch("ananno_phase2.qt_workbench.run_packing_job",slow_job):
            self.window.start_packing()
            self.assertTrue(started.wait(2))
            self.window.close()
            self.assertTrue(self.window.cancel_event.is_set())
            self.wait_finished()
        self.assertFalse(self.window.isVisible())
        self.assertEqual(self.window.status_label.text(),"已停止")

    def test_main_entry_opens_qt_and_never_imports_tk(self):
        entry=Path(__file__).resolve().parents[1]/"main.py"
        script=f'''
import sys,runpy,importlib.abc
class BlockTk(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {{'tkinter','matplotlib','PIL'}}:
            raise AssertionError('Wrong GUI dependency: '+fullname)
sys.meta_path.insert(0,BlockTk())
from PyQt5 import QtCore,QtWidgets
from ananno_phase2 import qt_workbench
Original=qt_workbench.PackingWorkbench
class AutoClose(Original):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        assert isinstance(self,QtWidgets.QMainWindow)
        assert 'PyQt5' in self.windowTitle()
        QtCore.QTimer.singleShot(100,self.close)
qt_workbench.PackingWorkbench=AutoClose
sys.argv=[{str(entry)!r}]
try:runpy.run_path({str(entry)!r},run_name='__main__')
except SystemExit as exc:assert exc.code==0,exc.code
print('REAL_QT_MAIN_OK')
'''
        process=subprocess.run([sys.executable,"-c",script],capture_output=True,timeout=15)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertIn(b"REAL_QT_MAIN_OK",process.stdout)
