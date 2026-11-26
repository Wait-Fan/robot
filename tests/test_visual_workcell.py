import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
import numpy as np
from ananno_phase2.ec66_model import EC66Model
from PyQt5 import QtWidgets as W,QtCore as C,QtGui as G,QtTest
from ananno_phase2.workcell_state import WorkcellState
from ananno_phase2.robot_geometry import RobotGeometry
from ananno_phase2.workcell_editor import WorkcellEditor
from ananno_phase2.qt_workbench_2025 import RobotWorkbench
from ananno_phase2.workbench_service import run_packing_job

ROOT=Path(__file__).resolve().parents[1]
APP=W.QApplication.instance() or W.QApplication([])

class VisualWorkcellTests(unittest.TestCase):
    def test_state_roundtrip_preserves_signed_positions_and_units(self):
        state=WorkcellState.create(ROOT,(2240,1440,720),(300,200,180))
        state.set_position('pallet',[-.8,.35,-.1]);state.set_yaw('pallet',np.pi/2)
        state.set_position('pickup',[.4,-.45,.12])
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'scene.json';state.save(path);other=WorkcellState.load(ROOT,path)
            np.testing.assert_allclose(other.pose('pallet'),state.pose('pallet'))
            np.testing.assert_allclose(other.pose('pickup')[:3,3],[.4,-.45,.12])
            cfg=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(cfg['pallet_frame_convention'],'long_side_x')
            self.assertEqual(cfg['calibration_status'],'virtual_workcell_unmeasured')
            np.testing.assert_allclose(cfg['pallet_dimensions_m'],[2.24,1.44,.72])
            self.assertIn('pick_surface',cfg)

    def test_robot_visual_meshes_and_tcp_match_actual_model(self):
        urdf=ROOT/'robot_models/robot_ec66/urdf/robot.ec66.urdf'
        geometry=RobotGeometry(urdf)
        model=EC66Model(urdf,ROOT/'robot_models/robot_config/config/robot_ec66.srdf')
        q=[.3,-.2,.6,-.4,.7,.2]
        # The collision backend saves/reloads MJCF, rounding quaternion text.
        # The visual FK follows original URDF rpy; agree well below 0.01mm.
        np.testing.assert_allclose(geometry.tcp_pose(q),model.fk(q),atol=1e-5)
        meshes=geometry.posed_meshes(q)
        self.assertGreaterEqual(len(meshes),9)
        self.assertGreater(sum(len(m['triangles']) for m in meshes),100)
        self.assertTrue(all(np.isfinite(m['triangles']).all() for m in meshes))

    def test_editor_select_move_save_and_cancel(self):
        editor=WorkcellEditor(ROOT,(2240,1440,720),(300,200,180))
        try:
            editor.select_entity('pallet');editor.position_fields[0].setValue(-750)
            editor.position_fields[2].setValue(-120)
            self.assertAlmostEqual(editor.state.pose('pallet')[0,3],-.75)
            self.assertAlmostEqual(editor.state.pose('pallet')[2,3],-.12)
            editor.canvas.view_top();editor.canvas.resize(800,600);editor.canvas.show();APP.processEvents()
            before=editor.state.pose('pallet')[:3,3].copy()
            editor.canvas.drag_entity('pallet',(40,0))
            self.assertFalse(np.allclose(before,editor.state.pose('pallet')[:3,3]))
            self.assertEqual(editor.state.pose('pallet')[2,3],before[2])
            before=editor.state.pose('pallet')[:3,3].copy()
            local=np.eye(4);local[:3,3]=[editor.state.dimensions[0]/2,editor.state.dimensions[1]/2,-.02]
            center=(editor.state.pallet_pose@local)[:3,3]
            screen=editor.canvas.project(np.array([center]))[0]
            point=C.QPoint(round(screen[0]),round(screen[1]))
            QtTest.QTest.mousePress(editor.canvas,C.Qt.LeftButton,pos=point)
            APP.sendEvent(editor.canvas,G.QMouseEvent(C.QEvent.MouseMove,C.QPointF(point+C.QPoint(20,0)),
                C.Qt.NoButton,C.Qt.LeftButton,C.Qt.NoModifier))
            QtTest.QTest.mouseRelease(editor.canvas,C.Qt.LeftButton,pos=point+C.QPoint(20,0))
            self.assertEqual(editor.canvas.selection,'pallet')
            self.assertFalse(np.allclose(before,editor.state.pose('pallet')[:3,3]))
            with tempfile.TemporaryDirectory() as td:
                path=Path(td)/'scene.json';editor.save_scene(path)
                self.assertTrue(path.exists())
            editor.reject()
            self.assertIsNone(editor.applied_path)
        finally:editor.close();editor.deleteLater();APP.processEvents()

    def test_workbench_applies_scene_to_job_and_disables_during_run(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'scene.json';WorkcellState.create(ROOT,(1200,800,1400)).save(path)
            window=RobotWorkbench(ROOT,restore_workcell=False)
            try:
                window.apply_workcell(path)
                self.assertEqual(Path(window._job_options()['robot_scene_path']),path)
                self.assertTrue(window.robot_check.isChecked())
                window._busy(True);self.assertFalse(window.workcell_button.isEnabled())
                window._busy(False);self.assertTrue(window.workcell_button.isEnabled())
            finally:window.close();window.deleteLater();APP.processEvents()

    def test_service_really_uses_scene_and_saves_actual_motion_audit(self):
        with tempfile.TemporaryDirectory() as td:
            scene=ROOT/'examples/ec66_scene_demo.json'
            result=run_packing_job(ROOT/'examples/ec66_offline_demo.json','全部箱子',25,10,10,1,
                Path(td)/'results',algorithm='robot2025',robot_scene_path=scene,
                paper_config=__import__('ananno_phase2.paper_config',fromlist=['PaperConfig']).PaperConfig(
                    population_size=4,mu=4,lambda_=4,generations=2,max_stagnation=1,max_pallets=2))
            audit=result['document']['robot_diagnostics']
            self.assertTrue(audit['ik_verified'])
            self.assertTrue(audit['joint_trajectory_verified'])
            self.assertEqual(len(audit['motion_verification']['stages']),12)
            self.assertFalse(audit['motion_verification']['hardware_verified'])
            self.assertTrue((Path(td)/'results/robot_scene_snapshot.json').exists())

    def test_pick_surface_uses_each_box_height(self):
        from tests.test_multiple_open_sides import fake_verifier
        from tests.test_robot_2025 import item
        from ananno_phase2.models import Pallet
        from ananno_phase2.robot_approach import ApproachConfig
        verifier=fake_verifier();surface=np.eye(4);surface[:3,3]=[.45,-.4,.05]
        verifier.config['pick_surface']={'pose':surface.tolist()};targets=[]
        def move(start,target,*,linear=False,cancelled=None):
            if linear and np.allclose(target[:2,3],[.45,-.4]):targets.append(float(target[2,3]))
            return [list(start),list(start)],''
        verifier._move=move
        report=verifier.verify([item('A',l=10,w=10,h=10),item('B',x=20,l=10,w=10,h=20,order=2)],
            Pallet(40,10,20),ApproachConfig())
        self.assertTrue(report['passed'],report)
        self.assertTrue(any(abs(z-.06)<1e-9 for z in targets))
        self.assertTrue(any(abs(z-.07)<1e-9 for z in targets))

    def test_scene_size_mismatch_and_stale_hash_are_rejected(self):
        from ananno_phase2.workcell_runtime import create_scene_verifier
        from ananno_phase2.models import Pallet
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'scene.json';WorkcellState.create(ROOT,(1200,800,1400)).save(path)
            with self.assertRaisesRegex(ValueError,'尺寸'):
                create_scene_verifier(ROOT,path,Pallet(25,10,10),Path(td)/'out')
            with self.assertRaisesRegex(ValueError,'更改'):
                create_scene_verifier(ROOT,path,Pallet(1200,800,1400),Path(td)/'out','wrong-hash')

    def test_workcell_load_rejects_non_mm_scale(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'scene.json';WorkcellState.create(ROOT).save(path)
            cfg=json.loads(path.read_text(encoding='utf-8'));cfg['length_scale_to_m']=.01
            path.write_text(json.dumps(cfg),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'毫米'):WorkcellState.load(ROOT,path)

    def test_bad_saved_scene_does_not_prevent_workbench_start(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'configs').mkdir();path=root/'configs/workcell.json'
            path.write_text('{broken',encoding='utf-8')
            window=RobotWorkbench(root)
            try:
                self.assertIsNone(window.robot_scene_path)
                self.assertFalse(window.robot_check.isChecked())
                self.assertFalse(window.robot_check.isEnabled())
                self.assertEqual(path.read_text(encoding='utf-8'),'{broken')
            finally:window.close();window.deleteLater();APP.processEvents()

    def test_removed_active_scene_is_a_validation_error(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'scene.json';WorkcellState.create(ROOT).save(path)
            window=RobotWorkbench(ROOT,restore_workcell=False)
            try:
                window.apply_workcell(path);path.unlink()
                with self.assertRaisesRegex(ValueError,'工位'):window._job_options()
            finally:window.close();window.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
