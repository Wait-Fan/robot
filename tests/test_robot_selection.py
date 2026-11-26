import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from ananno_phase2.ec66_model import EC66Model
from ananno_phase2.robot_profiles import profiles,resolve_mesh_path
from ananno_phase2.workcell_state import WorkcellState
from ananno_phase2.robot_geometry import RobotGeometry
from ananno_phase2.workcell_editor import WorkcellEditor
from ananno_phase2.robot_offline import OfflineRobotVerifier
from ananno_phase2.models import Box,Pallet,Placement,Point3D
from ananno_phase2.robot_approach import ApproachConfig
from PyQt5 import QtWidgets as W

ROOT=Path(__file__).resolve().parents[1]
APP=W.QApplication.instance() or W.QApplication([])
FANUC='fanuc_r2000ic210l'

class RobotSelectionTests(unittest.TestCase):
    def test_switch_keeps_workcell_and_uses_600_800_250_tool(self):
        self.assertIn(FANUC,profiles())
        state=WorkcellState.create(ROOT,(2240,1440,720));pallet=state.pallet_pose.copy()
        state.select_robot(FANUC)
        self.assertEqual(state.config['robot_id'],FANUC)
        self.assertEqual(state.config['tip_link'],'packing_tcp')
        self.assertEqual(state.config['tool_definition']['size_m'],[.6,.8,.25])
        self.assertEqual(state.config['tool_status'],'footprint_provided_height_provisional')
        np.testing.assert_allclose(state.pallet_pose,pallet)
        state.select_robot('ec66');self.assertNotIn('tool_definition',state.config)

    def test_visual_fk_and_collision_model_agree_for_fanuc(self):
        state=WorkcellState.create(ROOT);state.select_robot(FANUC);cfg=state.config
        geometry=RobotGeometry(cfg['urdf'],tip=cfg['tip_link'],tool_definition=cfg['tool_definition'])
        robot=EC66Model(cfg['urdf'],cfg['srdf'],tip=cfg['tip_link'],tool_definition=cfg['tool_definition'],touch_links=cfg['touch_links'])
        np.testing.assert_allclose(geometry.tcp_pose(state.q),robot.fk(state.q),atol=1e-5)
        self.assertEqual(robot.names,[f'joint_{i}' for i in range(1,7)])
        self.assertGreater(float(robot.upper[0]),np.pi)
        self.assertTrue(any(m['link']=='packing_tool' for m in geometry.posed_meshes(state.q)))
        self.assertTrue(robot.valid(state.q),robot.collisions(state.q))
        goal=robot.fk(state.q);solution=robot.ik(goal,state.q+.01,check_collision=False)
        self.assertIsNotNone(solution)
        wall=np.eye(4);wall[:3,3]=goal[:3,3]
        robot.set_obstacles([{'id':'wall','size':[10,10,10],'pose':wall.tolist()}])
        self.assertFalse(robot.valid(state.q))

    def test_gripper_footprint_participates_in_collision(self):
        state=WorkcellState.create(ROOT);state.select_robot(FANUC);cfg=state.config
        robot=EC66Model(cfg['urdf'],cfg['srdf'],tip=cfg['tip_link'],tool_definition=cfg['tool_definition'],touch_links=cfg['touch_links'])
        tcp=robot.fk(state.q);blocker=np.eye(4);blocker[:3,3]=tcp[:3,3]+tcp[:3,:3]@np.array([.25,.35,-.125])
        robot.set_obstacles([{'id':'tool_edge_blocker','size':[.03,.03,.03],'pose':blocker.tolist()}])
        self.assertIn(['packing_tool','tool_edge_blocker'],robot.collisions(state.q))

    def test_fanuc_can_verify_a_complete_software_pick_and_place(self):
        state=WorkcellState.create(ROOT,(10,10,10),(10,10,10));state.select_robot(FANUC);state.include_table=False;state.config['approach_distance_m']=.002
        cfg=state.config
        robot=EC66Model(cfg['urdf'],cfg['srdf'],tip=cfg['tip_link'],tool_definition=cfg['tool_definition'],touch_links=cfg['touch_links'])
        tcp=robot.fk(state.q)
        state.pick_pose[:3,3]=tcp[:3,3]-np.array([0,0,.01])
        state.pallet_pose[:3,3]=tcp[:3,3]-np.array([.005,.005,.01])+np.array([.04,0,0])
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'scene.json';state.save(path)
            verifier=OfflineRobotVerifier(path);verifier.configure_pallet_axes(Pallet(10,10,10))
            box=Box('A',10,10,10);placement=Placement(box,0,Point3D(0,0,0),box.orientations()[0],1)
            report=verifier.verify([placement],Pallet(10,10,10),ApproachConfig())
            self.assertTrue(report['passed'],(report['reason'],report['failed_operation']))
            self.assertEqual(len(report['stages']),6)
            self.assertEqual(report['robot_id'],FANUC)
            self.assertEqual(report['tool_definition']['size_m'],[.6,.8,.25])
            self.assertFalse(report['hardware_verified'])

    def test_scene_roundtrip_keeps_robot_and_tool(self):
        state=WorkcellState.create(ROOT);state.select_robot(FANUC)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'scene.json';state.save(path);loaded=WorkcellState.load(ROOT,path)
            self.assertEqual(loaded.config['robot_id'],FANUC)
            self.assertEqual(loaded.config['tool_definition'],state.config['tool_definition'])
            np.testing.assert_allclose(loaded.q,state.q)

    def test_config_cannot_mislabel_the_loaded_robot(self):
        state=WorkcellState.create(ROOT);state.select_robot(FANUC)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'scene.json';state.save(path)
            cfg=json.loads(path.read_text(encoding='utf-8'));cfg['robot_id']='ec66'
            path.write_text(json.dumps(cfg),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'不一致'):OfflineRobotVerifier(path)

    def test_editor_combo_changes_mesh_limits_and_tool(self):
        editor=WorkcellEditor(ROOT,(2240,1440,720))
        try:
            editor.robot_combo.setCurrentIndex(editor.robot_combo.findData(FANUC))
            self.assertEqual(editor.state.config['robot_id'],FANUC)
            self.assertGreater(editor.joint_fields[0].maximum(),180)
            self.assertEqual([f.value() for f in editor.tool_fields],[600,800,250])
            editor.tool_fields[2].setValue(300)
            self.assertAlmostEqual(editor.state.config['tool_definition']['size_m'][2],.3)
            editor.robot_combo.setCurrentIndex(editor.robot_combo.findData('ec66'))
            self.assertNotIn('tool_definition',editor.state.config)
        finally:editor.close();editor.deleteLater();APP.processEvents()

    def test_package_mesh_paths_are_distinct_and_confined(self):
        urdf=ROOT/'robot_models/fanuc_r2000ic_support/urdf/r2000ic210l.urdf'
        paths=[resolve_mesh_path(urdf,f'package://fanuc_r2000ic_support/meshes/r2000ic210l/{kind}/base_link.stl') for kind in ('visual','collision')]
        self.assertNotEqual(*paths);self.assertTrue(all(p.exists() for p in paths))
        with self.assertRaises(ValueError):resolve_mesh_path(urdf,'package://fanuc_r2000ic_support/../../outside.stl')

if __name__=='__main__':unittest.main()
