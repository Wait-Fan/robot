import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
from ananno_phase2.ec66_model import EC66Model, mj

ROOT=Path(__file__).resolve().parents[1]

def reference(robot,q):
    robot._set(q);pairs=[]
    for index,a in enumerate(robot.robot_geoms):
        la=mj.mj_id2name(robot.model,mj.mjtObj.mjOBJ_BODY,int(robot.model.geom_bodyid[a]))
        for b in robot.robot_geoms[index+1:]:
            lb=mj.mj_id2name(robot.model,mj.mjtObj.mjOBJ_BODY,int(robot.model.geom_bodyid[b]))
            if la==lb or frozenset([la,lb]) in robot.disabled:continue
            if mj.mj_geomDistance(robot.model,robot.data,a,b,.01,None)<-1e-5:pairs.append([la,lb])
        for b,item in zip(robot.world_geoms,robot.obstacles):
            if la in item.get('allowed_touch_links',[]):continue
            boxes=robot.model.geom_type[a]==mj.mjtGeom.mjGEOM_BOX and robot.model.geom_type[b]==mj.mjtGeom.mjGEOM_BOX
            overlap=slow_sat(robot,a,b) if boxes else mj.mj_geomDistance(robot.model,robot.data,a,b,.01,None)<-1e-5
            if overlap:pairs.append([la,str(item.get('id',b))])
        if robot.attachment and la not in robot.touch_links:
            if mj.mj_geomDistance(robot.model,robot.data,a,robot.held_id,.01,None)<-1e-5:pairs.append([la,'carried_box'])
    if robot.attachment:
        for b,item in zip(robot.world_geoms,robot.obstacles):
            if slow_sat(robot,robot.held_id,b):pairs.append(['carried_box',str(item.get('id',b))])
    return pairs

def slow_sat(robot,a,b):
    ra=robot.data.geom_xmat[a].reshape(3,3);rb=robot.data.geom_xmat[b].reshape(3,3)
    delta=robot.data.geom_xpos[b]-robot.data.geom_xpos[a]
    axes=[ra[:,i] for i in range(3)]+[rb[:,i] for i in range(3)]
    axes += [np.cross(ra[:,i],rb[:,j]) for i in range(3) for j in range(3)]
    for axis in axes:
        norm=np.linalg.norm(axis)
        if norm<1e-10:continue
        axis=axis/norm
        radius=np.dot(np.abs(ra.T@axis),robot.model.geom_size[a])+np.dot(np.abs(rb.T@axis),robot.model.geom_size[b])
        if radius-abs(np.dot(delta,axis))<=1e-5:return False
    return True

def model():
    return EC66Model(ROOT/'robot_models/robot_ec66/urdf/robot.ec66.urdf',ROOT/'robot_models/robot_config/config/robot_ec66.srdf')

class CollisionAccelerationTests(unittest.TestCase):
    def test_broadphase_matches_original_narrowphase_with_attachment_and_rotated_world(self):
        robot=model();rng=np.random.default_rng(13)
        obstacles=[]
        for i in range(12):
            pose=np.eye(4);angle=rng.uniform(-3,3)
            pose[:2,:2]=[[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]]
            pose[:3,3]=rng.uniform(-.6,.6,3)
            obstacles.append({'id':str(i),'size':rng.uniform(.001,.4,3),'pose':pose,'allowed_touch_links':['cup_link'] if i%3==0 else []})
        robot.set_obstacles(obstacles)
        for carried in (False,True):
            robot.attachment=([.1,.2,.3],np.eye(4)) if carried else None
            for _ in range(25):
                q=rng.uniform(robot.lower,robot.upper)
                self.assertEqual(robot.collisions(q),reference(robot,q))
        self.assertGreater(robot.collision_stats['broadphase_skipped'],0)

    def test_fanuc_mesh_proxy_bounds_and_collision_results_match_original(self):
        from ananno_phase2.robot_profiles import profile_config,FANUC
        from ananno_phase2.collision_acceleration import world_bounds
        cfg=profile_config(ROOT,FANUC)
        robot=EC66Model(cfg['urdf'],cfg['srdf'],tip=cfg['tip_link'],tool_definition=cfg['tool_definition'],touch_links=cfg['touch_links'])
        pose=np.eye(4);pose[:3,3]=[.3,.5,.2]
        robot.set_obstacles([{'id':'near','size':[.4,.7,.3],'pose':pose}])
        robot.attachment=([.53,.35,.48],np.eye(4));rng=np.random.default_rng(19)
        for _ in range(12):
            q=rng.uniform(robot.lower,robot.upper)
            self.assertEqual(robot.collisions(q),reference(robot,q))
            centers,halves=world_bounds(robot._bound_centers,robot._bound_halves,robot.data.geom_xpos,robot.data.geom_xmat)
            for i in robot.robot_geoms:
                if robot.model.geom_type[i]!=mj.mjtGeom.mjGEOM_MESH:continue
                mesh=int(robot.model.geom_dataid[i]);start=int(robot.model.mesh_vertadr[mesh]);n=int(robot.model.mesh_vertnum[mesh])
                vertices=robot.model.mesh_vert[start:start+n]@robot.data.geom_xmat[i].reshape(3,3).T+robot.data.geom_xpos[i]
                self.assertTrue(np.all(np.abs(vertices-centers[i])<=halves[i]+1e-9))

    def test_far_obstacles_never_reach_narrowphase(self):
        robot=model();pose=np.eye(4);pose[:3,3]=[100]*3
        robot.set_obstacles([{'id':'far','size':[.1]*3,'pose':pose}])
        robot.collisions(np.zeros(6))
        self.assertGreaterEqual(robot.collision_stats['broadphase_skipped'],len(robot.robot_geoms))

    def test_vectorized_sat_agrees_at_flush_tolerance_and_almost_parallel(self):
        robot=model();robot.set_obstacles([{'id':'b','size':[.2]*3,'pose':np.eye(4)}])
        a=robot.held_id;b=robot.world_geoms[0];robot.model.geom_size[a]=[.1]*3
        for angle in [0,1e-11,1e-7,.3,1.5707963267948966]:
            robot.data.mocap_quat[robot.held_mocap]=[np.cos(angle/2),0,0,np.sin(angle/2)]
            for x in [0,.199,.199989,.199999,.2,.201]:
                robot.data.mocap_pos[robot.held_mocap]=[x,0,0];mj.mj_kinematics(robot.model,robot.data)
                self.assertEqual(robot._box_overlap(a,b),slow_sat(robot,a,b),(angle,x))

    def test_ik_cache_reuses_positive_solution_but_rechecks_current_collision(self):
        robot=model();q=np.array([.3,-.2,.6,-.4,.7,.2]);target=robot.fk(q)
        robot.ik(target,q+.03,check_collision=False)
        with patch.object(robot,'fk',wraps=robot.fk) as fk:
            solved=robot.ik(target,q+.03,check_collision=False)
            self.assertIsNotNone(solved);self.assertLessEqual(fk.call_count,1)
        self.assertGreater(robot.ik_cache_hits,0)
        robot.set_obstacles([{'id':'wall','size':[5]*3,'pose':np.eye(4)}])
        self.assertIsNone(robot.ik(target,q,restarts=0,iterations=5))

if __name__=='__main__':unittest.main()
