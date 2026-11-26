import copy
import csv
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import numpy as np


class CoordinateBoundaryTests(unittest.TestCase):
    def test_internal_checkpoint_declares_its_geometry_frame(self):
        from ananno_phase2.pallet_coordinates import INTERNAL_FRAME
        from tests.test_multiple_open_sides import fake_verifier
        from tests.test_robot_2025 import item
        v=fake_verifier()
        with tempfile.TemporaryDirectory() as folder:
            v.diagnostics_dir=Path(folder);v.save_verified_pallet('test-key',[item('A')],{'passed':True})
            saved=json.loads((Path(folder)/'robot_verified_pallets/test-key.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['coordinate_frame'],INTERNAL_FRAME)

    def test_box_anchor_roundtrip_uses_box_width_not_only_point_reflection(self):
        from ananno_phase2.pallet_coordinates import reflected_box_position,reflected_side
        self.assertEqual(reflected_box_position({'x':100,'y':200,'z':50},350,1440),{'x':100,'y':890,'z':50})
        self.assertEqual(reflected_box_position({'x':100,'y':890,'z':50},350,1440),{'x':100,'y':200,'z':50})
        self.assertEqual(reflected_side('+Y'),'-Y');self.assertEqual(reflected_side('-X'),'-X')

    def test_view_adapter_changes_anchors_and_sides_without_copying_trajectory(self):
        from ananno_phase2.pallet_coordinates import public_document,PUBLIC_FRAME
        from tests.test_robot_replay import fixture_document
        doc=fixture_document();doc['pallets'][0]['packed_items'][0]['placed_size']['width']=1
        motion=doc['robot_diagnostics']['motion_verification'];motion['open_directions']=['-Y','+Z']
        old=copy.deepcopy(doc);new=public_document(doc)
        self.assertEqual(doc,old);self.assertEqual(new['pallets'][0]['packed_items'][0]['position']['y'],1)
        self.assertEqual(new['coordinate_system']['frame'],PUBLIC_FRAME)
        self.assertEqual(new['robot_diagnostics']['motion_verification']['open_directions'],['+Y','+Z'])
        self.assertIs(new['robot_diagnostics']['motion_verification']['stages'][0]['trajectory'],motion['stages'][0]['trajectory'])
        self.assertIs(public_document(new),new)

    def test_public_approach_normalizes_once_at_packer_boundary(self):
        from ananno_phase2.pallet_coordinates import PUBLIC_FRAME,INTERNAL_FRAME
        from ananno_phase2.robot_approach import ApproachConfig
        from ananno_phase2.robot_pipeline import RobotTwoPhasePacker
        from ananno_phase2.models import Pallet
        cfg=ApproachConfig(open_directions=['+Y','+X'],outside_side='-Y',coordinate_frame=PUBLIC_FRAME)
        packer=RobotTwoPhasePacker(Pallet(2240,1440,720),approach=cfg)
        self.assertEqual(packer.approach.open_directions,('-Y','+X'));self.assertEqual(packer.approach.outside_side,'+Y')
        self.assertEqual(packer.approach.coordinate_frame,INTERNAL_FRAME)
        self.assertEqual(packer.approach.calculation_config(),packer.approach)

    def test_service_json_and_csv_both_export_top_left_coordinates(self):
        from ananno_phase2.workbench_service import run_packing_job
        from ananno_phase2.pallet_coordinates import PUBLIC_FRAME
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'boxes.csv';source.write_text('id,length,width,height\nA,2,1,1\n')
            result=run_packing_job(source,'全部箱子',4,3,2,1,root/'out')
            doc=result['document'];item=doc['pallets'][0]['packed_items'][0]
            self.assertEqual(item['position']['y'],2);self.assertEqual(doc['coordinate_system']['frame'],PUBLIC_FRAME)
            with result['paths']['csv'].open(encoding='utf-8-sig',newline='') as f:row=next(csv.DictReader(f))
            self.assertEqual(float(row['y']),item['position']['y'])


class CoordinateUiTests(unittest.TestCase):
    def test_workcell_public_origin_is_opposite_y_corner_and_rh_pose_unchanged(self):
        from ananno_phase2.workcell_state import WorkcellState
        root=Path(__file__).resolve().parents[1];state=WorkcellState.create(root,(2240,1440,720))
        internal=state.pallet_pose.copy();origin,basis=state.pallet_public_axes()
        np.testing.assert_allclose(origin,internal[:3,3]+internal[:3,1]*1.44)
        np.testing.assert_allclose(basis[:,1],-internal[:3,1]);self.assertAlmostEqual(np.linalg.det(internal[:3,:3]),1)
        edit=state.pallet_edit_pose();state.set_pallet_edit_position(edit[:3,3]+[.1,.2,0])
        np.testing.assert_allclose(state.pallet_pose[:3,3],internal[:3,3]+[.1,.2,0])

    def test_top_view_origin_and_positive_xy_follow_edges(self):
        from ananno_phase2.native_scene import project_scene
        from ananno_phase2.pallet_coordinates import PUBLIC_FRAME
        pallet={'pallet':{'length':2240,'width':1440,'height':720},'packed_items':[],'coordinate_frame':PUBLIC_FRAME}
        faces,lines,texts=project_scene(pallet,800,600,yaw=0,pitch=90)
        origin=lines[0][0];x_end=lines[0][1];y_end=lines[3][0]
        self.assertGreater(x_end[0],origin[0]);self.assertGreater(y_end[1],origin[1])
        self.assertTrue(any(t[2].startswith('O ') for t in texts))
        self.assertTrue(any(t[2].startswith('X+') for t in texts))
        self.assertTrue(any(t[2].startswith('Y+') for t in texts))

    def test_history_view_is_public_but_input_and_file_unchanged(self):
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench,W
        from ananno_phase2.io import write_packing_plan_json
        from ananno_phase2.models import Box,Pallet
        from ananno_phase2.packer import FixedSequencePacker
        app=W.QApplication.instance() or W.QApplication([]);root=Path(__file__).resolve().parents[1]
        doc=write_packing_plan_json(None,FixedSequencePacker(Pallet(4,3,2)).pack([Box('A',2,1,1)]));original=copy.deepcopy(doc)
        window=RobotWorkbench(root,restore_workcell=False)
        try:
            window.display_document(doc)
            self.assertEqual(doc,original);self.assertEqual(window.document['pallets'][0]['packed_items'][0]['position']['y'],2)
            self.assertEqual(float(window.table_rows[0][5]),2)
            window.detail_canvas.view_top();self.assertEqual(window.detail_canvas.pitch,90)
        finally:window.close();window.deleteLater();app.processEvents()

    def test_replay_public_position_maps_to_same_internal_box(self):
        from ananno_phase2.robot_replay import ReplayCanvas
        from ananno_phase2.pallet_coordinates import PUBLIC_FRAME
        state=SimpleNamespace(dimensions=np.array([4.,3.,2.]),pallet_pose=np.eye(4),config={'length_scale_to_m':1.},fixed_obstacles=lambda:[])
        item={'position':{'x':1.,'y':2.,'z':0},'placed_size':{'length':2.,'width':1.,'height':1.}}
        stub=SimpleNamespace(state=state,bundle=SimpleNamespace(timeline=SimpleNamespace(coordinate_frame=PUBLIC_FRAME)),
            frame=SimpleNamespace(completed_ids=('A',),source_id=None,carrying_id=None),_items={'A':item},_colors={'A':'#ff0000'})
        objects=ReplayCanvas.objects(stub);points=next(points for key,points,color in objects if key=='placed_A')
        np.testing.assert_allclose(points.min(axis=0),[1.,0.,0.]);np.testing.assert_allclose(points.max(axis=0),[3.,1.,1.])

if __name__=='__main__':unittest.main()
