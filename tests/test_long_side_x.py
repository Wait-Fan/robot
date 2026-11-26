import contextlib
import io
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
import time
import numpy as np
from ananno_phase2.robot_offline import OfflineRobotVerifier
from PyQt5 import QtWidgets as W,QtCore as C
from openpyxl import Workbook
from ananno_phase2.models import Pallet
from ananno_phase2.io import read_packing_json
from ananno_phase2.workbench_service import inspect_input,run_packing_job,load_result
from ananno_phase2.qt_workbench import PackingWorkbench
from ananno_phase2.qt_workbench_2025 import RobotWorkbench
from main import main

APP=W.QApplication.instance() or W.QApplication([])
ROOT=Path(__file__).resolve().parents[1]


class LongSideXTests(unittest.TestCase):
    def write_input(self,folder):
        path=Path(folder)/'boxes.json'
        path.write_text(json.dumps({'pallet':{'length':6,'width':10,'height':4},
            'boxes':[{'id':'A','box_type':'A','length':1,'width':2,'height':1,'target_num':1}]}),encoding='utf-8')
        return path

    def test_explicit_normalization_preserves_raw_pallet_and_box_axes(self):
        raw=Pallet(6,10,4);normalized=raw.with_long_side_x()
        self.assertEqual(normalized,Pallet(10,6,4))
        self.assertEqual(raw,Pallet(6,10,4))
        self.assertEqual(Pallet(6,6,4).with_long_side_x(),Pallet(6,6,4))
        for dims in [(float('nan'),1,1),(float('inf'),1,1)]:
            with self.assertRaises(ValueError):Pallet(*dims).with_long_side_x()

    def test_json_import_summary_uses_long_side_x_but_source_is_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            path=self.write_input(td);original=path.read_bytes();info=inspect_input(path)
            self.assertEqual(info['pallet'],(10,6,4))
            self.assertEqual(info['pallet_source_dimensions'],(6,10,4))
            self.assertTrue(info['pallet_axes_swapped'])
            raw,boxes=read_packing_json(path)
            self.assertEqual((boxes[0].length,boxes[0].width),(1,2))
            self.assertEqual(path.read_bytes(),original)

    def test_xlsx_import_summary_uses_the_same_convention(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'boxes.xlsx';book=Workbook();sheet=book.active
            sheet.append(['box_type','length','width','height','pallet_length','pallet_width','pallet_height'])
            sheet.append(['A',1,2,1,6,10,4]);book.save(path);book.close()
            self.assertEqual(inspect_input(path)['pallet'],(10,6,4))

    def test_service_normalizes_manual_dimensions_and_records_frame(self):
        with tempfile.TemporaryDirectory() as td:
            out=run_packing_job(self.write_input(td),'全部箱子',6,10,4,1,Path(td)/'output')
            doc=out['document']
            self.assertEqual(doc['pallet'],{'length':10,'width':6,'height':4})
            self.assertEqual(doc['coordinate_system']['pallet_axis_convention'],'long_side_x')
            self.assertEqual(doc['coordinate_system']['origin'],[0,0,0])
            self.assertEqual(load_result(out['paths']['json'])['pallet'],doc['pallet'])

    def test_cli_normalizes_file_and_explicit_override(self):
        with tempfile.TemporaryDirectory() as td:
            path=self.write_input(td)
            for extra,expected in [([],{'length':10,'width':6,'height':4}),
                (['--pallet','3','8','5'],{'length':8,'width':3,'height':5})]:
                out=Path(td)/'result.json'
                with contextlib.redirect_stdout(io.StringIO()):
                    code=main(['--input-json',str(path),'--output-json',str(out),
                        '--output-csv',str(Path(td)/'positions.csv'),'--no-show',*extra])
                self.assertEqual(code,0)
                self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['pallet'],expected)

    def test_gui_load_and_manual_settings_use_long_side_x(self):
        with tempfile.TemporaryDirectory() as td:
            window=RobotWorkbench(ROOT,restore_workcell=False);failures=[]
            try:
                window.load_input_file(self.write_input(td))
                self.assertEqual(list(map(float,window.dimensions)),[10,6,4])
                def edit():
                    dialog=APP.activeModalWidget()
                    try:
                        fields=dialog.findChildren(W.QLineEdit)
                        for entry,value in zip(fields[:3],('4','9','7')):entry.setText(value)
                        dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.Ok).click()
                    except BaseException as exc:failures.append(exc);dialog.reject()
                C.QTimer.singleShot(0,edit);PackingWorkbench.show_settings(window)
                if failures:raise failures[0]
                self.assertEqual(list(map(float,window.dimensions)),[9,4,7])
            finally:window.close();window.deleteLater();APP.processEvents()

    def test_loading_historical_result_preserves_old_coordinates(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'old.json'
            doc={'pallet':{'length':6,'width':10,'height':4},'unplaced_items':[],
                'pallets':[{'pallet_index':1,'pallet':{'length':6,'width':10,'height':4},
                'packed_items':[{'id':'A','sequence':1,'orientation':'Z0','position':{'x':0,'y':8,'z':0},
                                'placed_size':{'length':1,'width':2,'height':1}}]}]}
            path.write_text(json.dumps(doc),encoding='utf-8')
            loaded=load_result(path)
            self.assertEqual(loaded['pallet'],doc['pallet'])
            self.assertEqual(loaded['pallets'][0]['packed_items'][0]['position'],{'x':0,'y':8,'z':0})

    def test_gui_repeated_calculations_keep_full_dimension_precision(self):
        with tempfile.TemporaryDirectory() as td:
            window=RobotWorkbench(ROOT,restore_workcell=False);window.output_dir=Path(td)/'output'
            expected=[2240.98765,1440.12345,720.54321]
            try:
                window.load_input_file(self.write_input(td));window.mode_combo.setCurrentText('基础模式')
                def edit_precision():
                    dialog=APP.activeModalWidget()
                    for entry,value in zip(dialog.findChildren(W.QLineEdit)[:3],('1440.12345','2240.98765','720.54321')):entry.setText(value)
                    dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.Ok).click()
                C.QTimer.singleShot(0,edit_precision);PackingWorkbench.show_settings(window)
                self.assertEqual(list(map(float,window.dimensions)),expected)
                for _ in range(2):
                    window.start_packing();deadline=time.monotonic()+15
                    while window.running and time.monotonic()<deadline:APP.processEvents();time.sleep(.01)
                    self.assertFalse(window.running)
                    self.assertEqual(list(map(float,window.dimensions)),expected)
                    pallet=window.document['pallet']
                    self.assertEqual([pallet['length'],pallet['width'],pallet['height']],expected)
            finally:
                if window.running:
                    window.stop_packing()
                    while window.running:APP.processEvents();time.sleep(.01)
                window.close();window.deleteLater();APP.processEvents()

    def test_robot_frame_conversion_preserves_the_physical_pallet(self):
        verifier=OfflineRobotVerifier.__new__(OfflineRobotVerifier)
        verifier.config={};verifier.base_pallet=np.eye(4);verifier.scale=.001
        verifier.cache={};verifier.model_fingerprint='original'
        verifier.configure_pallet_axes(Pallet(6,10,4))
        expected=np.array([[0,-1,0,.006],[1,0,0,0],[0,0,1,0],[0,0,0,1.]])
        np.testing.assert_allclose(verifier.base_pallet,expected)
        self.assertAlmostEqual(np.linalg.det(verifier.base_pallet[:3,:3]),1.)
        first=verifier.base_pallet.copy();fingerprint=verifier.model_fingerprint
        verifier.configure_pallet_axes(Pallet(6,10,4))
        np.testing.assert_allclose(verifier.base_pallet,first)
        self.assertEqual(verifier.model_fingerprint,fingerprint)
        verifier.config={'pallet_frame_convention':'long_side_x'}
        verifier.configure_pallet_axes(Pallet(6,10,4))
        np.testing.assert_allclose(verifier.base_pallet,np.eye(4))

    def test_real_robot_cli_handles_swapped_input_frame(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            source=json.loads((ROOT/'examples/ec66_offline_demo.json').read_text(encoding='utf-8'))
            source['pallet']['length'],source['pallet']['width']=10,25
            input_path=folder/'boxes.json';input_path.write_text(json.dumps(source),encoding='utf-8')
            scene=json.loads((ROOT/'examples/ec66_scene_demo.json').read_text(encoding='utf-8'))
            for key in ('urdf','srdf'):scene[key]=str((ROOT/'examples'/scene[key]).resolve())
            canonical=np.array(scene['base_T_pallet'])
            mapping=np.array([[0,-1,0,.01],[1,0,0,0],[0,0,1,0],[0,0,0,1.]])
            scene['base_T_pallet']=(canonical@np.linalg.inv(mapping)).tolist()
            scene['pallet_frame_convention']='input_length_width'
            scene_path=folder/'scene.json';scene_path.write_text(json.dumps(scene),encoding='utf-8')
            output=folder/'plan.json'
            with contextlib.redirect_stdout(io.StringIO()):
                code=main(['--algorithm','robot2025','--input-json',str(input_path),
                    '--robot-scene',str(scene_path),'--paper-config',str(ROOT/'examples/ec66_ga_demo.json'),
                    '--output-json',str(output),'--output-csv',str(folder/'positions.csv'),'--no-show'])
            self.assertEqual(code,0)
            doc=json.loads(output.read_text(encoding='utf-8'));audit=doc['robot_diagnostics']['motion_verification']
            self.assertEqual(doc['pallet'],{'length':25,'width':10,'height':10})
            self.assertTrue(audit['passed'],audit)
            self.assertEqual(len(audit['stages']),12)
            self.assertTrue(audit['pallet_frame_mapping']['axes_swapped'])
            np.testing.assert_allclose(audit['pallet_frame_mapping']['scene_pallet_T_calculation_pallet'],mapping)


if __name__=='__main__':unittest.main()
