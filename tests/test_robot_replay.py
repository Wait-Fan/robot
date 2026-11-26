import copy
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ananno_phase2.models import Box, Pallet
from ananno_phase2.packer import FixedSequencePacker
from ananno_phase2.io import write_packing_plan_json

ROOT=Path(__file__).resolve().parents[1]
OPERATIONS=('approach_pick','pick','lift','transfer','place','retreat')


def fixture_document():
    result=FixedSequencePacker(Pallet(2,2,1)).pack([Box('A',2,2,1),Box('B',2,2,1)])
    doc=write_packing_plan_json(None,result);stages=[]
    for pallet,box in [(1,'A'),(2,'B')]:
        for n,operation in enumerate(OPERATIONS):
            stages.append({'box_id':box,'pallet':pallet,'operation':operation,
                'carrying_box':operation in ('lift','transfer','place'),'open_direction':'-X',
                'path_mode':'cartesian_linear','trajectory':[
                    {'time_from_start':0.,'positions':[n*.01]*6,'velocities':[0.]*6},
                    {'time_from_start':2.,'positions':[(n+1)*.01]*6,'velocities':[0.]*6}]})
    doc['robot_diagnostics']={'passed':True,'ik_verified':True,'joint_trajectory_verified':True,
        'motion_verification':{'passed':True,'status':'verified','stages':stages,
            'joint_names':[f'j{i}' for i in range(6)],'time_parameterization':'rest_to_rest_cubic'}}
    return doc


class SelectedPalletTests(unittest.TestCase):
    def test_history_popup_text_has_dark_readable_pixels_on_white(self):
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench,W
        from PyQt5 import QtGui as G
        app=W.QApplication.instance() or W.QApplication([])
        G.QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
        window=RobotWorkbench(ROOT,restore_workcell=False)
        try:
            window.show();window.history.clear();window.history.addItems(['选择历史结果','2026-11-24 历史计算结果'])
            window.history.showPopup();app.processEvents()
            view=window.history.view();rect=view.visualRect(window.history.model().index(1,0))
            im=view.viewport().grab(rect.adjusted(4,3,-4,-3)).toImage()
            dark=sum(1 for y in range(im.height()) for x in range(im.width()) if max(im.pixelColor(x,y).getRgb()[:3])<120)
            self.assertGreater(dark,20)
        finally:
            window.history.hidePopup();window.close();window.deleteLater();app.processEvents()

    def test_card_and_detail_selection_update_box_table_and_export_scope(self):
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench,W
        app=W.QApplication.instance() or W.QApplication([])
        window=RobotWorkbench(ROOT,restore_workcell=False)
        try:
            window.display_document(fixture_document())
            self.assertEqual(window.box_table.rowCount(),1)
            self.assertEqual(window.box_table.item(0,2).text(),'A')
            window.overview_cards[1].select()
            self.assertEqual(window.box_table.rowCount(),1)
            self.assertEqual(window.box_table.item(0,2).text(),'B')
            self.assertEqual(window.table_rows[0][1],2)
            window.pallet_combo.setCurrentIndex(0)
            self.assertEqual(window.box_table.item(0,2).text(),'A')
            window.search.setText('no-such-box');window.apply_filter()
            self.assertEqual(window.box_table.rowCount(),0)
        finally:window.close();window.deleteLater();app.processEvents()

    def test_missing_trajectory_button_gives_actionable_message(self):
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench,W
        app=W.QApplication.instance() or W.QApplication([])
        doc=fixture_document();doc.pop('robot_diagnostics')
        window=RobotWorkbench(ROOT,restore_workcell=False)
        try:
            window.display_document(doc)
            messages=[]
            with patch.object(W.QMessageBox,'information',side_effect=lambda *args:messages.append(args[-1])):
                window.overview_cards[0].motion_button.click()
            self.assertEqual(len(messages),1)
            self.assertIn('完整校验',messages[0])
        finally:window.close();window.deleteLater();app.processEvents()


class ReplayTimelineTests(unittest.TestCase):
    def test_only_selected_pallet_and_correct_cubic_interpolation(self):
        from ananno_phase2.replay_timeline import ReplayTimeline
        timeline=ReplayTimeline(fixture_document(),2)
        self.assertEqual(timeline.duration,12.)
        frame=timeline.frame_at(.5)
        self.assertEqual(frame.stage['box_id'],'B')
        self.assertAlmostEqual(frame.q[0],.0015625)
        self.assertEqual(frame.source_id,'B')
        self.assertIsNone(frame.carrying_id)

    def test_attach_release_and_seek_back_do_not_leave_stale_boxes(self):
        from ananno_phase2.replay_timeline import ReplayTimeline
        timeline=ReplayTimeline(fixture_document(),1)
        carrying=timeline.frame_at(7)
        self.assertEqual(carrying.carrying_id,'A')
        self.assertEqual(carrying.completed_ids,())
        released=timeline.frame_at(10)
        self.assertIsNone(released.carrying_id)
        self.assertEqual(released.completed_ids,('A',))
        self.assertTrue(timeline.frame_at(12).finished)
        self.assertEqual(timeline.frame_at(0).completed_ids,())

    def test_bad_stages_are_rejected_and_other_pallet_cannot_fill_missing_stages(self):
        from ananno_phase2.replay_timeline import ReplayTimeline
        for change in ('nan','time','discontinuous','missing'):
            doc=fixture_document();stages=doc['robot_diagnostics']['motion_verification']['stages']
            if change=='nan':stages[0]['trajectory'][0]['positions'][0]=float('nan')
            elif change=='time':stages[0]['trajectory'][1]['time_from_start']=-1
            elif change=='discontinuous':stages[1]['trajectory'][0]['positions'][0]=2
            else:stages.pop(0)
            with self.subTest(change=change),self.assertRaises(ValueError):ReplayTimeline(doc,1)


class RealReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_ec66_sequence import scene_config
        from ananno_phase2.workbench_service import run_packing_job
        from ananno_phase2.robot_approach import ApproachConfig
        cls.temp=tempfile.TemporaryDirectory();cls.folder=Path(cls.temp.name)
        cfg=scene_config();cfg.update(pallet_frame_convention='long_side_x',pallet_dimensions_m=[.01,.01,.01],robot_name='EC66')
        scene=cls.folder/'scene.json';scene.write_text(json.dumps(cfg),encoding='utf-8')
        source=cls.folder/'boxes.csv';source.write_text('id,length,width,height\nA,10,10,10\n')
        cls.result=run_packing_job(source,'全部箱子',10,10,10,1,cls.folder/'run',algorithm='robot2025',
            robot_scene_path=scene,approach_config=__import__('ananno_phase2.robot_approach',fromlist=['ApproachConfig']).ApproachConfig(
                open_directions=['+Z','-X'],direction_policy='side_direct_first'))

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_real_saved_scene_loads_and_viewer_attaches_releases_and_closes(self):
        from ananno_phase2.robot_replay import load_replay_bundle,RobotReplayDialog
        from PyQt5 import QtWidgets as W
        app=W.QApplication.instance() or W.QApplication([])
        bundle=load_replay_bundle(ROOT,self.result['document'],self.result['paths']['json'],1)
        dialog=RobotReplayDialog(bundle)
        try:
            dialog.show();app.processEvents()
            stages=bundle.timeline.stages
            transfer=next(n for n,s in enumerate(stages) if s['operation']=='transfer')
            dialog.seek_time(bundle.timeline.starts[transfer]+.00001)
            names=[key for key,_,_ in dialog.canvas.objects()]
            self.assertIn('carried_A',names);self.assertNotIn('placed_A',names)
            dialog.final()
            names=[key for key,_,_ in dialog.canvas.objects()]
            self.assertIn('placed_A',names);self.assertNotIn('carried_A',names)
            dialog.reset();self.assertIn('source_A',[key for key,_,_ in dialog.canvas.objects()])
            dialog.play();self.assertTrue(dialog.timer.isActive())
            dialog.close();self.assertFalse(dialog.timer.isActive())
        finally:
            dialog.close();app.processEvents()

    def test_fanuc_replay_loads_real_tool_and_places_visible_sized_box(self):
        import numpy as np
        from ananno_phase2.workcell_state import WorkcellState
        from ananno_phase2.robot_profiles import FANUC
        from ananno_phase2.ec66_model import EC66Model
        from ananno_phase2.robot_approach import ApproachConfig
        from ananno_phase2.workbench_service import run_packing_job
        from ananno_phase2.robot_replay import load_replay_bundle,ReplayCanvas
        from PyQt5 import QtWidgets as W
        app=W.QApplication.instance() or W.QApplication([])
        state=WorkcellState.create(ROOT,(600,400,400),(300,200,180));state.select_robot(FANUC);state.include_table=False
        cfg=state.config;cfg['approach_distance_m']=.03;cfg['path_budget_seconds']=6.;cfg['sequence_budget_seconds']=45.
        robot=EC66Model(cfg['urdf'],cfg['srdf'],tip=cfg['tip_link'],tool_definition=cfg['tool_definition'],touch_links=cfg['touch_links'])
        tcp=robot.fk(state.q);state.pick_pose[:3,3]=tcp[:3,3]-[0,0,.18]
        state.pallet_pose[:3,3]=tcp[:3,3]-[.15,.1,.18]+np.array([.04,0,0])
        scene=self.folder/'fanuc.json';state.save(scene)
        source=self.folder/'fanuc_boxes.csv';source.write_text('id,length,width,height\nA,300,200,180\n')
        result=run_packing_job(source,'全部箱子',600,400,400,1,self.folder/'fanuc_result',algorithm='robot2025',robot_scene_path=scene,
            approach_config=ApproachConfig(open_directions=['+Z','-X'],direction_policy='side_direct_first'))
        bundle=load_replay_bundle(ROOT,result['document'],result['paths']['json'],1)
        self.assertEqual(bundle.state.config['robot_id'],FANUC)
        self.assertEqual(bundle.geometry.names,[f'joint_{i}' for i in range(1,7)])
        canvas=ReplayCanvas(bundle)
        try:
            self.assertTrue(any(m[0]=='packing_tool' for m in bundle.geometry.meshes))
            canvas.set_frame(bundle.timeline.frame_at(bundle.timeline.duration))
            vertices=next(points for key,points,_ in canvas.objects() if key=='placed_A')
            np.testing.assert_allclose(np.ptp(vertices,axis=0),[.3,.2,.18],atol=1e-8)
        finally:canvas.close();canvas.deleteLater();app.processEvents()

    def test_changed_snapshot_is_rejected_instead_of_using_current_scene(self):
        from ananno_phase2.robot_replay import load_replay_bundle
        doc=self.result['document'];snapshot=self.result['paths']['json'].parent/doc['robot_diagnostics']['scene_snapshot']
        original=snapshot.read_bytes()
        try:
            cfg=json.loads(original);cfg['approach_distance_m']*=2
            snapshot.write_text(json.dumps(cfg),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'不同'):load_replay_bundle(ROOT,doc,self.result['paths']['json'],1)
        finally:snapshot.write_bytes(original)

    def test_reopening_result_keeps_new_dialog_registered_after_old_dialog_deletion(self):
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench,W,C
        app=W.QApplication.instance() or W.QApplication([])
        window=RobotWorkbench(ROOT,restore_workcell=False);new=None
        try:
            window.display_document(self.result['document'],self.result['paths']['json'])
            window.open_robot_replay(1);old=window._motion_windows[1];old.pause()
            window.display_document(self.result['document'],self.result['paths']['json'])
            window.open_robot_replay(1);new=window._motion_windows[1];new.pause()
            self.assertIsNot(old,new)
            app.sendPostedEvents(None,C.QEvent.DeferredDelete)
            self.assertIs(window._motion_windows.get(1),new)
        finally:
            if new is not None:new.close()
            window.close();window.deleteLater();app.processEvents()


if __name__=='__main__':unittest.main()
