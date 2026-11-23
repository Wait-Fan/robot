import json
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

from ananno_phase2.tk_workbench import PackingWorkbench
from ananno_phase2.workbench_service import run_packing_job
from ananno_phase2.ui_widgets import ActionButton


class NativeWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.window = PackingWorkbench(self.root, self.folder,default_algorithm="基础模式")
        self.source = self.folder / "boxes.csv"
        self.source.write_text("id,length,width,height\nA,2,2,1\nB,2,2,1\nC,2,2,1\nX,9,9,9\n")

    def tearDown(self):
        if self.window.worker:
            self.window.stop_packing()
            self.wait_finished()
        self.window.destroy()
        self.temp.cleanup()

    def wait_finished(self):
        deadline = time.monotonic() + 15
        while self.window.worker is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertIsNone(self.window.worker)

    def test_plain_input_computes_tables_and_filters_without_order(self):
        self.window.load_input_file(self.source)
        self.assertTrue(self.window.order_combo.instate(["disabled"]))
        for var, value in zip(self.window.dimensions, (2, 2, 2)):
            var.set(str(value))
        self.window.start_packing()
        self.wait_finished()
        self.assertEqual(self.window.document["summary"]["pallet_count"], 2)
        self.assertEqual(len(self.window.box_table.get_children()), 3)
        self.assertEqual(len(self.window.unplaced_table.get_children()), 1)
        self.window.pallet_filter.set("托盘 2")
        self.window.filter_changed()
        self.assertEqual(len(self.window.box_table.get_children()), 1)
        self.assertEqual(self.window.current_pallet()["pallet_index"], 2)
        self.assertEqual(self.window.status.get(), "已完成")

    def test_animation_steps_stop_at_final_and_preserve_rotation(self):
        output = run_packing_job(self.source, "全部箱子", 2, 2, 4, 1, self.folder / "out")
        self.window.load_result_file(output["paths"]["json"])
        self.window.reset_animation()
        self.window.next_step()
        self.assertEqual(self.window.step, 1)
        self.window.previous_step()
        self.assertEqual(self.window.step, 0)
        self.window.play_animation()
        for _ in range(5):
            self.window.next_step()
        self.assertEqual(self.window.step, 3)
        self.assertFalse(self.window.playing)

    def test_styled_button_does_not_invoke_disabled_actions(self):
        calls = []
        button = ActionButton(self.root,text="开始装箱",command=lambda:calls.append("started"),style="Blue.TButton")
        button.invoke()
        button.configure(state="disabled")
        button.invoke()
        self.assertEqual(calls,["started"])
        button.configure(state="normal",text="重新计算")
        button.invoke()
        self.assertEqual(calls,["started","started"])
        button.destroy()

    def test_paper_mode_runs_both_phases_and_exposes_audit(self):
        source=self.folder/"two_phase.json"
        source.write_text(json.dumps({"pallet":{"length":4,"width":4,"height":6},"boxes":[
            {"box_type":"A","length":2,"width":2,"height":2,"target_num":8,"weight":1},
            {"box_type":"B","length":1,"width":1,"height":1,"target_num":1,"weight":1}]}))
        self.window.load_input_file(source)
        self.window.algorithm.set("论文两阶段")
        self.window.algorithm_changed()
        self.window.start_packing()
        self.wait_finished()
        self.assertEqual(self.window.document["summary"]["packed_box_count"],9)
        self.assertTrue(self.window.document["paper_diagnostics"]["all_hard_constraints_pass"])
        self.assertIn("研究实现",self.window.method_note.get())
        self.assertIn("all_hard_constraints_pass",self.window.audit_box.get("1.0","end"))
        self.assertTrue(self.window.mode_combo.instate(["readonly"]))
        self.assertIn("层/块 8 箱",self.window.result_summary.get())
        self.assertIn("GA 剩余箱 1 箱",self.window.result_summary.get())
        self.assertIn("当前结果：论文两阶段",self.window.mode_banner.get())

    def test_default_is_paper_and_old_basic_result_is_clearly_identified(self):
        self.window.destroy()
        self.root=tk.Tk()
        self.root.withdraw()
        self.window=PackingWorkbench(self.root,self.folder)
        self.assertEqual(self.window.algorithm.get(),"论文两阶段")
        self.assertIn("当前计算：论文两阶段",self.window.mode_banner.get())
        self.assertIn("v0.3.2",self.root.title())
        output=run_packing_job(self.source,"全部箱子",2,2,4,1,self.folder/"old")
        self.window.load_result_file(output["paths"]["json"])
        self.assertEqual(self.window.algorithm.get(),"论文两阶段")
        self.assertIn("当前结果：基础模式",self.window.mode_banner.get())
        self.assertIn("需重新计算",self.window.mode_banner.get())
        self.assertIn("未执行层/块与 GA",self.window.result_summary.get())
        self.window.algorithm.set("基础模式")
        self.assertNotIn("需重新计算",self.window.mode_banner.get())

    def test_original_wcs_json_uses_settings_and_runs_paper_mode(self):
        path=self.folder/"wcs.json"
        path.write_text(json.dumps({"code":200,"msg":"ok","data":[
            {"box_type":"A","length":2,"width":2,"height":1,"target_num":2,"weight":1,"case_type":"MH423C"},
            {"box_type":"B","length":1,"width":1,"height":1,"target_num":1,"weight":1,"case_type":"WR246"}]}))
        for var,value in zip(self.window.dimensions,(2,2,3)): var.set(str(value))
        self.window.load_input_file(path)
        self.assertEqual(self.window.input_info["kind"],"wcs_json")
        self.assertIn("全部读取",self.window.input_summary.get())
        self.assertEqual([float(v.get()) for v in self.window.dimensions],[2,2,3])
        self.window.algorithm.set("论文两阶段")
        self.window.start_packing()
        self.wait_finished()
        self.assertEqual(self.window.document["summary"]["packed_box_count"],3)
        self.assertTrue(self.window.document["paper_diagnostics"]["all_hard_constraints_pass"])

    def test_four_card_pages_search_and_independent_playback(self):
        source = self.folder / "nine.csv"
        source.write_text("id,length,width,height\n" + "".join(f"B{i},1,1,1\n" for i in range(9)))
        output = run_packing_job(source, "全部箱子", 1, 1, 1, 1, self.folder / "nine")
        self.window.load_result_file(output["paths"]["json"])
        self.assertEqual(len(self.window.overview_cards), 4)
        self.assertEqual(self.window.page_text.get(), "1 / 3")
        first, second = self.window.overview_cards[:2]
        first.reset()
        second.reset()
        first.play()
        self.assertTrue(first.playing)
        self.assertFalse(second.playing)
        first.tick()
        self.assertEqual(first.step, 1)
        self.assertEqual(second.step, 0)
        second.select()
        self.assertEqual(self.window.current_pallet()["pallet_index"], 2)
        self.window.change_page(1)
        self.assertFalse(first.playing)
        self.assertIsNone(first.timer)
        self.assertEqual(self.window.page_text.get(), "2 / 3")
        self.window.search.set("B8")
        self.window.change_page(1)
        self.assertEqual(self.window.page_text.get(), "3 / 3")
        self.assertEqual(len(self.window.box_table.get_children()), 9)
        self.window.filter_changed()
        self.assertEqual(len(self.window.overview_cards), 1)
        self.assertEqual(len(self.window.box_table.get_children()), 1)
        self.assertEqual(self.window.overview_cards[0].pallet["pallet_index"], 9)
        self.assertEqual(tuple(self.window.pallet_combo.cget("values")), ("托盘 9",))
        self.window.search.set("找不到")
        self.window.filter_changed()
        self.assertEqual(self.window.overview_cards, [])
        self.assertEqual(self.window.page_text.get(), "0 / 0")

    def test_json_preserves_precision_and_invalid_result_keeps_current_plan(self):
        source = self.folder / "boxes.json"
        source.write_text(json.dumps({"pallet": {"length": 1.205, "width": 1, "height": 1},
            "boxes": [{"length": .604, "width": 1, "height": 1, "target_num": 2}]}))
        self.window.load_input_file(source)
        self.assertEqual(float(self.window.dimensions[0].get()), 1.205)
        self.window.start_packing()
        self.wait_finished()
        self.assertEqual(self.window.document["summary"]["pallet_count"], 2)
        previous = self.window.document
        invalid = self.folder / "invalid.json"
        invalid.write_text('{"boxes": []}')
        with self.assertRaises(ValueError):
            self.window.load_result_file(invalid)
        self.assertIs(self.window.document, previous)

    def test_cancellation_and_close_leave_no_partial_plan(self):
        self.window.load_input_file(self.source)
        self.window.start_packing()
        self.window.stop_packing()
        self.wait_finished()
        self.assertEqual(self.window.status.get(), "已停止")
        self.assertIsNone(self.window.document)

    def test_more_than_six_pallets_paginate_and_all_oversized_disables_playback(self):
        self.source.write_text("id,length,width,height\n" + "".join(f"B{i},1,1,1\n" for i in range(7)))
        output = run_packing_job(self.source, "全部箱子", 1, 1, 1, 1, self.folder / "out")
        self.window.load_result_file(output["paths"]["json"])
        self.assertEqual(self.window.page_text.get(), "1 / 2")
        self.window.change_page(1)
        self.assertEqual(self.window.page_text.get(), "2 / 2")
        self.source.write_text("id,length,width,height\nX,9,9,9\n")
        output = run_packing_job(self.source, "全部箱子", 1, 1, 1, 1, self.folder / "other")
        self.window.load_result_file(output["paths"]["json"])
        self.assertIsNone(self.window.current_pallet())
        self.assertEqual(len(self.window.unplaced_table.get_children()), 1)

    def test_legacy_tk_window_never_imports_third_party_graphics(self):
        script = '''
import importlib.abc,sys,tkinter
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'PyQt5','matplotlib','numpy','PIL'}:
            raise AssertionError('Unwanted dependency: '+fullname)
sys.meta_path.insert(0,Block())
from ananno_phase2.tk_workbench import PackingWorkbench
root=tkinter.Tk();root.withdraw();window=PackingWorkbench(root);root.update();window.destroy()
print('STANDARD_LIBRARY_STARTUP_OK')
'''
        output = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertIn("STANDARD_LIBRARY_STARTUP_OK", output.stdout)
