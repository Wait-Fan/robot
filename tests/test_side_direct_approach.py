from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
import numpy as np

from ananno_phase2.robot_approach import ApproachConfig, OpenDirectionModel, executable_sequence
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2.models import Pallet
from ananno_phase2.robot_offline import OfflineRobotVerifier
from tests.test_multiple_open_sides import fake_verifier
from tests.test_robot_2025 import item


def config(sides=('+Z', '-X')):
    return ApproachConfig(open_directions=sides, direction_policy='side_direct_first')


def pose_robot(verifier):
    """A deterministic Cartesian 6-axis surrogate, retaining real verifier stage/state logic."""
    def fk(q):
        pose = np.eye(4); pose[:3, 3] = np.asarray(q)[:3]; return pose
    verifier.robot.fk = fk
    calls = []
    def move(start, target, *, linear=False, cancelled=None):
        calls.append((np.asarray(start).copy(), target.copy(), linear))
        end = np.asarray(start).copy(); end[:3] = target[:3, 3]
        return [list(start), end.tolist()], ''
    verifier._move = move
    return calls, move


class SideDirectApproachTests(unittest.TestCase):
    def test_box_tool_flush_contact_is_clear_but_real_penetration_is_rejected(self):
        from ananno_phase2.ec66_model import EC66Model
        from ananno_phase2.workcell_state import WorkcellState
        from ananno_phase2.robot_profiles import FANUC
        root=Path(__file__).resolve().parents[1]
        state=WorkcellState.create(root);state.select_robot(FANUC);cfg=state.config
        robot=EC66Model(cfg['urdf'],cfg['srdf'],tip=cfg['tip_link'],
                        tool_definition=cfg['tool_definition'],touch_links=cfg['touch_links'])
        tcp=robot.fk(state.q);box=tcp.copy();box[:3,3]+=tcp[:3,2]*.005
        obstacle={'id':'contact_box','size':[.01,.01,.01],'pose':box.tolist()}
        robot.set_obstacles([obstacle])
        self.assertNotIn(['packing_tool','contact_box'],robot.collisions(state.q))
        box[:3,3]-=tcp[:3,2]*.0001;obstacle['pose']=box.tolist()
        robot.set_obstacles([obstacle])
        self.assertIn(['packing_tool','contact_box'],robot.collisions(state.q))
        obstacle['allowed_touch_links']=['packing_tool'];robot.set_obstacles([obstacle])
        self.assertNotIn(['packing_tool','contact_box'],robot.collisions(state.q))

    def test_real_robot_mesh_ik_and_checked_path_accept_side_direct(self):
        from tests.test_ec66_sequence import scene_config
        with tempfile.TemporaryDirectory() as td:
            scene = Path(td)/'scene.json'; scene.write_text(json.dumps(scene_config()), encoding='utf-8')
            audit = OfflineRobotVerifier(scene).verify([item('A',l=10,w=10,h=10)], Pallet(10,10,10), config(('+Z','-X','-Y')))
            self.assertTrue(audit['passed'], (audit['reason'],audit['failed_operation']))
            self.assertEqual(audit['directions_by_box'][0]['open_direction'], '-X')
            self.assertEqual(audit['directions_by_box'][0]['transfer_mode'], 'cartesian_direct')

    def test_gui_and_cli_default_to_elevated_prepose_and_label_geometry_only(self):
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench, W
        app = W.QApplication.instance() or W.QApplication([])
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)/'plan.json'
            source = Path(td)/'boxes.json'
            source.write_text(json.dumps({'pallet':{'length':1,'width':1,'height':1},
                'boxes':[{'id':'A','length':1,'width':1,'height':1}]}))
            result = subprocess.run([sys.executable,str(root/'main.py'),'--algorithm','robot2025',
                '--input-json',str(source),'--open-direction=+Z','--open-direction=-X',
                '--output-json',str(output),'--output-csv',str(Path(td)/'boxes.csv'),'--no-show'],
                capture_output=True,env=dict(os.environ,PYTHONIOENCODING='utf-8'),encoding='utf-8',timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            doc=json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(doc['robot_diagnostics']['direction_selection_policy'],'preplace_optimized')
            self.assertEqual(doc['robot_diagnostics']['direction_choice_status'],'geometric_candidate_only')
            self.assertEqual(doc['robot_diagnostics']['checks'][0]['open_direction'],'-X')
            window=RobotWorkbench(root,restore_workcell=False)
            try:
                window.approach_directions=('+Z','-X')
                self.assertEqual(window._job_options()['approach_config'].direction_policy,'preplace_optimized')
                window.display_document(doc)
                self.assertIn('几何候选：侧向 1 箱，上方 0 箱',window.result_summary.text())
            finally:
                window.close();window.deleteLater();app.processEvents()

    def test_available_side_gates_are_ranked_by_current_tcp_distance(self):
        verifier = fake_verifier(); pose_robot(verifier)
        verifier.pick[:3,3] = [.2,-.2,0]
        audit = verifier.verify([item('A',l=10,w=10,h=10)], Pallet(10,10,10), config(('+Z','-X','-Y')))
        self.assertTrue(audit['passed'],audit)
        self.assertEqual(audit['directions_by_box'][0]['open_direction'],'-Y')

    def test_geometric_direction_prefers_side_even_when_z_listed_first(self):
        cfg = config()
        model = OpenDirectionModel(cfg)
        self.assertEqual(model.available_directions(item('A'), []), ['-X', '+Z'])
        _, audit = executable_sequence([item('A')], Pallet(1, 1, 1), PaperConfig(), cfg)
        self.assertEqual(audit['checks'][0]['open_direction'], '-X')

    def test_side_transfer_is_linear_and_gate_is_outside_pallet(self):
        verifier = fake_verifier(); calls, _ = pose_robot(verifier)
        audit = verifier.verify([item('A', x=20, l=10, w=10, h=10)], Pallet(30, 10, 10), config())
        self.assertTrue(audit['passed'], audit)
        check = audit['directions_by_box'][0]
        self.assertEqual(check['open_direction'], '-X')
        self.assertEqual(check['transfer_mode'], 'cartesian_direct')
        transfer = [s for s in audit['stages'] if s['operation'] == 'transfer'][0]
        # Target TCP x=.025m. Box half length .005m; its right face at the entry
        # must be at or outside x=-.002m (the configured clearance).
        self.assertAlmostEqual(transfer['target_tcp_pose'][0][3], -.007)
        self.assertTrue(calls[3][2])
        self.assertEqual(transfer['path_mode'], 'cartesian_linear')
        self.assertLessEqual(max(c[1][2, 3] for c in calls), .012 + 1e-9)

    def test_direct_side_failure_tries_side_detour_before_top(self):
        verifier = fake_verifier(); calls, real_move = pose_robot(verifier)
        def move(start, target, *, linear=False, cancelled=None):
            if target[0, 3] < 0 and linear and verifier.robot.attachment is not None:
                return None, 'blocked_direct_line'
            return real_move(start, target, linear=linear, cancelled=cancelled)
        verifier._move = move
        audit = verifier.verify([item('A', l=10, w=10, h=10)], Pallet(10, 10, 10), config())
        self.assertTrue(audit['passed'], audit)
        check = audit['directions_by_box'][0]
        self.assertEqual(check['open_direction'], '-X')
        self.assertEqual(check['transfer_mode'], 'joint_rrt')
        self.assertEqual(check['attempts'][0]['reason'], 'blocked_direct_line')
        self.assertEqual(len(audit['stages']), 6)

    def test_all_side_attempts_fail_then_top_is_used_only_if_selected(self):
        verifier = fake_verifier(); _, real_move = pose_robot(verifier)
        def move(start, target, *, linear=False, cancelled=None):
            if target[0, 3] < 0: return None, 'side_gate_unreachable'
            return real_move(start, target, linear=linear, cancelled=cancelled)
        verifier._move = move
        placement = item('A', l=10, w=10, h=10)
        audit = verifier.verify([placement], Pallet(10, 10, 10), config())
        self.assertTrue(audit['passed'], audit)
        self.assertEqual(audit['directions_by_box'][0]['open_direction'], '+Z')
        self.assertEqual(len(audit['directions_by_box'][0]['attempts']), 3)
        self.assertFalse(verifier.verify([placement], Pallet(10, 10, 10), config(('-X',)))['passed'])

    def test_direction_policy_is_part_of_robot_result_cache(self):
        verifier = fake_verifier(); pose_robot(verifier)
        p = item('A', l=10, w=10, h=10); pallet = Pallet(10, 10, 10)
        legacy = verifier.verify([p], pallet, ApproachConfig(open_directions=['+Z', '-X']))
        preferred = verifier.verify([p], pallet, config())
        self.assertEqual(legacy['directions_by_box'][0]['open_direction'], '+Z')
        self.assertEqual(preferred['directions_by_box'][0]['open_direction'], '-X')
        self.assertEqual(verifier.calls, 2)

    def test_all_direct_sides_are_tried_before_any_joint_detour(self):
        verifier = fake_verifier(); _, real_move = pose_robot(verifier)
        def move(start, target, *, linear=False, cancelled=None):
            if target[0,3]<0 and linear and verifier.robot.attachment is not None:
                return None, 'first_side_direct_blocked'
            return real_move(start, target, linear=linear, cancelled=cancelled)
        verifier._move = move
        audit = verifier.verify([item('A', l=10, w=10, h=10)], Pallet(10,10,10), config(('+Z','-X','-Y')))
        self.assertTrue(audit['passed'], audit)
        check = audit['directions_by_box'][0]
        self.assertEqual(check['open_direction'], '-Y')
        self.assertEqual([a['transfer_mode'] for a in check['attempts']], ['cartesian_direct','cartesian_direct'])

    def test_rotated_pallet_side_gate_uses_the_pallet_axis(self):
        verifier = fake_verifier(); pose_robot(verifier)
        verifier.base_pallet[:3,:3] = [[0,-1,0],[1,0,0],[0,0,1]]
        verifier.base_pallet[:3,3] = [.1,.2,.3]
        audit = verifier.verify([item('A', l=10,w=10,h=10)], Pallet(10,10,10), config(('-X',)))
        self.assertTrue(audit['passed'], audit)
        entry = np.asarray(audit['directions_by_box'][0]['entry_tcp_pose'])[:3,3]
        np.testing.assert_allclose(entry, [.095,.193,.31], atol=1e-9)

    def test_failed_retreat_restores_attachment_obstacles_and_stages_for_next_side(self):
        verifier = fake_verifier(); _, real_move = pose_robot(verifier)
        restored = []
        def move(start, target, *, linear=False, cancelled=None):
            if target[0,3]<0 and linear and verifier.robot.attachment is None:
                self.assertIn('placed_A', [o['id'] for o in verifier.robot.obstacles])
                return None, 'retreat_blocked'
            if target[1,3]<0 and verifier.robot.attachment is not None:
                restored.append('placed_A' not in [o['id'] for o in verifier.robot.obstacles])
            return real_move(start, target, linear=linear, cancelled=cancelled)
        verifier._move = move
        audit = verifier.verify([item('A',l=10,w=10,h=10)], Pallet(10,10,10), config(('+Z','-X','-Y')))
        self.assertTrue(audit['passed'], audit)
        self.assertEqual(audit['directions_by_box'][0]['open_direction'], '-Y')
        self.assertEqual(restored, [True])
        self.assertEqual(len(audit['stages']), 6)
        self.assertEqual([o['id'] for o in verifier.robot.obstacles], ['pallet','placed_A'])

    def test_cartesian_motion_interpolates_orientation_instead_of_jumping(self):
        verifier = OfflineRobotVerifier.__new__(OfflineRobotVerifier)
        verifier.path_seconds = 2.; verifier.resolution = .1
        poses = []
        def ik(pose, seed, **kwargs):
            poses.append(pose.copy()); return np.zeros(6)
        verifier.robot = SimpleNamespace(valid=lambda q: True, ik=ik, fk=lambda q: np.eye(4))
        target = np.eye(4); target[:3, :3] = [[0,-1,0],[1,0,0],[0,0,1]]; target[0,3] = .01
        path, reason = verifier._move(np.zeros(6), target, linear=True)
        self.assertIsNotNone(path, reason)
        angles = [np.arctan2(p[1,0], p[0,0]) for p in poses]
        self.assertGreater(len(angles), 10)
        self.assertLess(angles[0], .1)
        self.assertAlmostEqual(angles[-1], np.pi/2)


if __name__ == '__main__': unittest.main()
