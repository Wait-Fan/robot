"""Small deterministic regressions; no packing search or physical IK trial."""
from dataclasses import replace
import unittest
import numpy as np
from ananno_phase2.models import Box, Pallet, Placement, Point3D
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2.robot_approach import ApproachConfig, executable_sequence, OpenDirectionModel


def item(key,x=0,y=0,z=0,l=1,w=1,h=1,order=1):
    box=Box(key,l,w,h,1,key)
    return Placement(box,0,Point3D(x,y,z),box.orientations()[0],order)


class WholePalletFrontierTests(unittest.TestCase):
    def test_complete_deeper_column_before_near_floor_across_layers(self):
        boxes=[item('near'),item('far_floor',y=1,order=2),item('far_top',y=1,z=1,order=3)]
        ordered,audit=executable_sequence(boxes,Pallet(2,2,3),PaperConfig(),ApproachConfig('+Z',outside_side='-Y'))
        self.assertTrue(audit['passed'],audit)
        self.assertEqual([p.box.id for p in ordered],['far_floor','far_top','near'])
        self.assertEqual(audit['sequencing_policy']['name'],'whole_pallet_depth_frontier')

    def test_upper_small_box_can_require_wide_support_before_it(self):
        boxes=[item('wide',w=2),item('far_top',y=1,z=1,order=2)]
        ordered,audit=executable_sequence(boxes,Pallet(2,2,3),PaperConfig(),ApproachConfig('+Z',outside_side='-Y'))
        self.assertTrue(audit['passed'],audit)
        self.assertEqual([p.box.id for p in ordered],['wide','far_top'])

    def test_support_frontier_cycle_rejects_layout_instead_of_relaxing(self):
        # Near support -> spanning upper -> far upper -> near support.
        boxes=[item('near'),item('far',y=1,order=2),item('span',z=1,w=2,order=3),
               item('deep_top',y=1,z=2,order=4)]
        ordered,audit=executable_sequence(boxes,Pallet(2,2,4),PaperConfig(),ApproachConfig('+Z',outside_side='-Y'))
        self.assertIsNone(ordered)
        self.assertIn('cycle',audit['reason'])


class EdgeGraspTests(unittest.TestCase):
    def test_filter_receives_canonical_pallet_transform_like_full_planner(self):
        from tests.test_multiple_open_sides import fake_verifier
        from ananno_phase2.robot_pipeline import RobotTwoPhasePacker
        v=fake_verifier();v.config.update(self.config(),base_T_pallet=np.eye(4).tolist())
        v.base_pallet[:3,:3]=[[0,-1,0],[1,0,0],[0,0,1]];v.base_pallet[:3,3]=[.5,-1,0]
        packer=RobotTwoPhasePacker(Pallet(2000,1000,720),approach=ApproachConfig('+Z',outside_side='-Y'),robot_verifier=v)
        np.testing.assert_equal(packer.constraints.tool_config['base_T_pallet'],v.base_pallet)

    def config(self):
        return {'length_scale_to_m':.001,'tool_definition':{'kind':'box_envelope','size_m':[.6,.8,.25]},
                'box_T_tcp_rotation':np.diag([1,-1,-1,1]).tolist(),'tcp_offset_from_box_top_m':[0,0,0]}

    def test_neighbor_edges_align_and_excess_extends_to_free_side(self):
        from ananno_phase2.robot_grasp import placement_grasp
        p=item('box',x=500,y=350,l=500,w=350,h=120)
        neighbors=[item('left',x=0,y=350,l=500,w=350,h=480),item('back',x=500,y=700,l=500,w=350,h=480)]
        grasp=placement_grasp(p,neighbors,self.config(),outside_side='-Y')
        np.testing.assert_allclose(grasp['tool_bounds_pallet_m'][0],[.5,1.1],atol=1e-10)
        np.testing.assert_allclose(grasp['tool_bounds_pallet_m'][1],[-.1,.7],atol=1e-10)
        self.assertEqual(grasp['aligned_sides'],['-X','+Y'])
        transform=np.asarray(grasp['box_T_tcp'])
        self.assertGreater(np.linalg.norm(transform[:2,3]),0)

    def test_z90_grasp_maps_offset_to_original_box_frame(self):
        from ananno_phase2.robot_grasp import placement_grasp
        p=item('box',l=500,w=350,h=120)
        p=replace(p,orientation=p.box.orientations()[1])
        grasp=placement_grasp(p,[],self.config(),outside_side='-Y')
        bounds=np.asarray(grasp['tool_bounds_pallet_m'])
        self.assertAlmostEqual(bounds[1,1],.5)
        self.assertAlmostEqual(bounds[0,1]-bounds[0,0],.8)
        self.assertAlmostEqual(bounds[1,1]-bounds[1,0],.6)

    def test_filter_uses_same_offset_and_rejects_trapped_oversize_tool(self):
        from ananno_phase2.robot_execution_constraints import RobotExecutionConstraintSet
        c=RobotExecutionConstraintSet(Pallet(2000,2000,800));c.tool_config=self.config();c.tool_outside_side='-Y'
        short=item('short',y=350,l=500,w=350,h=120)
        tall=item('back',y=700,l=500,w=350,h=480)
        self.assertTrue(c.validate(short,[tall],check_pattern=False).feasible)
        front=item('front',y=0,l=500,w=350,h=480)
        self.assertFalse(c.validate(short,[tall,front],check_pattern=False).feasible)


class PreplaceTests(unittest.TestCase):
    def test_ui_exposes_motion_distances_and_default_policy(self):
        import tempfile,json
        from pathlib import Path
        from ananno_phase2.qt_workbench_2025 import RobotWorkbench,W
        from ananno_phase2.workcell_editor import WorkcellEditor
        app=W.QApplication.instance() or W.QApplication([])
        root=Path(__file__).resolve().parents[1];window=RobotWorkbench(root,restore_workcell=False);editor=WorkcellEditor(root)
        try:
            self.assertEqual(window.direction_policy,'preplace_optimized')
            editor.pick_lift.setValue(65);editor.preplace_height.setValue(125);editor.preplace_offset.setValue(90)
            editor.grasp_alignment.setCurrentIndex(editor.grasp_alignment.findData('occupied_edges'))
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'scene.json';editor.save_scene(path);cfg=json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(cfg['pick_lift_m'],.065)
                self.assertEqual(cfg['preplace_height_m'],.125)
                self.assertEqual(cfg['preplace_side_offset_m'],.09)
                self.assertEqual(cfg['grasp_alignment'],'occupied_edges')
        finally:
            window.close();editor.close();window.deleteLater();editor.deleteLater();app.processEvents()

    def test_verifier_uses_short_lift_best_found_prepose_and_shared_grasp(self):
        from tests.test_multiple_open_sides import fake_verifier
        from tests.test_side_direct_approach import pose_robot
        v=fake_verifier();calls,_=pose_robot(v)
        v.config.update(pick_lift_m=.07,preplace_height_m=.16,preplace_side_offset_m=.09,
                        tool_definition={'kind':'box_envelope','size_m':[.6,.8,.25]})
        v.grasp_rotation=np.diag([1.,-1.,-1.])
        audit=v.verify([item('A',l=500,w=350,h=120)],Pallet(1000,1000,720),
                       ApproachConfig(open_directions=['-X','+Z'],outside_side='-Y',direction_policy='preplace_optimized'))
        self.assertTrue(audit['passed'],audit)
        stages=audit['stages'];lift=stages[2];place=stages[4];transfer=stages[3]
        self.assertEqual(len(stages),6)
        self.assertAlmostEqual(lift['target_tcp_pose'][2][3]-stages[1]['target_tcp_pose'][2][3],.07)
        self.assertAlmostEqual(transfer['target_tcp_pose'][2][3]-place['target_tcp_pose'][2][3],.16)
        self.assertFalse(calls[3][2])
        self.assertIn('grasp',audit['directions_by_box'][0])
        self.assertEqual(audit['time_parameterization'],'piecewise_quintic_c2')
        self.assertGreater(len(audit['directions_by_box'][0]['attempts']),1)

    def test_side_means_elevated_local_prepose_not_pallet_edge_slide(self):
        from ananno_phase2.robot_motion import preplace_pose, motion_options
        cfg=motion_options({})
        target=np.eye(4);target[:3,3]=[1,1,.3]
        pose=preplace_pose(target,np.eye(4),'-X',cfg)
        self.assertGreater(pose[2,3],target[2,3])
        self.assertLess(target[0,3]-pose[0,3],.3)
        self.assertEqual(preplace_pose(target,np.eye(4),'+Z',cfg)[0,3],target[0,3])

    def test_side_prepose_candidate_does_not_require_clear_infinite_horizontal_sweep(self):
        cfg=ApproachConfig(open_directions=['-Y'],direction_policy='preplace_optimized',outside_side='-Y')
        self.assertEqual(OpenDirectionModel(cfg).available_directions(item('far',y=1),[item('near')]),['-Y'])


class SmoothTrajectoryTests(unittest.TestCase):
    def test_recorded_grasp_is_used_by_replay_instead_of_centering(self):
        from types import SimpleNamespace
        from ananno_phase2.robot_replay import ReplayCanvas
        matrix=np.eye(4);matrix[:3,3]=[.05,-.225,.06]
        stub=SimpleNamespace(bundle=SimpleNamespace(directions={'A':{'grasp':{'box_T_tcp':matrix.tolist()}}}))
        np.testing.assert_equal(ReplayCanvas._box_tcp(stub,{'id':'A'}),matrix)

    def test_new_replay_cannot_silently_lose_recorded_grasp(self):
        from tests.test_robot_replay import fixture_document
        from ananno_phase2.replay_timeline import ReplayTimeline
        doc=fixture_document();motion=doc['robot_diagnostics']['motion_verification'];motion['time_parameterization']='piecewise_quintic_c2'
        for s in motion['stages']:
            for p in s['trajectory']:p['accelerations']=[0.]*6
        with self.assertRaisesRegex(ValueError,'抓取'):ReplayTimeline(doc,1)

    def test_internal_velocity_is_continuous_and_limits_hold(self):
        from ananno_phase2.joint_trajectory import smooth_trajectory, evaluate_segment
        points=smooth_trajectory([[0]*6,[.1]*6,[.2]*6],np.ones(6),np.ones(6),lambda q:True,
                                 lower=-np.ones(6),upper=np.ones(6),shortcut=False)
        self.assertGreater(points[1]['velocities'][0],0)
        for left,right in zip(points,points[1:]):
            for u in np.linspace(0,1,101):
                q,v,a=evaluate_segment(left,right,u)
                self.assertLessEqual(float(np.max(np.abs(v))),1.00001)
                self.assertLessEqual(float(np.max(np.abs(a))),1.00001)
        np.testing.assert_allclose(evaluate_segment(points[0],points[1],1)[1:],evaluate_segment(points[1],points[2],0)[1:],atol=1e-10)

    def test_smoothing_curve_is_collision_checked_not_just_waypoints(self):
        from ananno_phase2.joint_trajectory import smooth_trajectory, evaluate_segment
        path=[[0,0],[1,0],[1,1]]
        valid=lambda q: abs(q[1])<1e-8 or abs(q[0]-1)<1e-8
        points=smooth_trajectory(path,np.ones(2),np.ones(2),valid,lower=np.array([-2,-2]),upper=np.array([2,2]),shortcut=False)
        for a,b in zip(points,points[1:]):
            for u in np.linspace(0,1,101):self.assertTrue(valid(evaluate_segment(a,b,u)[0]))

    def test_shortcut_preserves_collision_avoidance_and_endpoints(self):
        from ananno_phase2.joint_trajectory import smooth_trajectory, evaluate_segment
        path=[[0,0],[0,1],[1,1],[1,0]]
        valid=lambda q:not(.2<q[0]<.8 and q[1]<.8)
        points=smooth_trajectory(path,np.ones(2),np.ones(2),valid,lower=-np.ones(2),upper=np.ones(2)*2)
        np.testing.assert_equal(points[0]['positions'],path[0]);np.testing.assert_equal(points[-1]['positions'],path[-1])
        for a,b in zip(points,points[1:]):
            for u in np.linspace(0,1,101):self.assertTrue(valid(evaluate_segment(a,b,u)[0]))

    def test_replay_uses_saved_derivatives_for_new_format(self):
        from tests.test_robot_replay import fixture_document
        from ananno_phase2.replay_timeline import ReplayTimeline
        from ananno_phase2.joint_trajectory import smooth_trajectory, evaluate_segment
        doc=fixture_document();motion=doc['robot_diagnostics']['motion_verification'];motion['time_parameterization']='piecewise_quintic_c2'
        motion['directions_by_box']=[{'box_id':key,'pallet':pal,'grasp':{'box_T_tcp':np.eye(4).tolist()}} for key,pal in [('A',1),('B',2)]]
        for s in motion['stages']:
            old=s['trajectory'];a=np.asarray(old[0]['positions']);b=np.asarray(old[-1]['positions'])
            s['trajectory']=smooth_trajectory([a,(a+b)/2,b],np.ones(6),np.ones(6),lambda q:True,lower=-np.ones(6),upper=np.ones(6),shortcut=False)
        timeline=ReplayTimeline(doc,1);pts=motion['stages'][0]['trajectory'];t=pts[1]['time_from_start']*.4
        np.testing.assert_allclose(timeline.frame_at(t).q,evaluate_segment(pts[0],pts[1],.4)[0])

if __name__=='__main__':unittest.main()
