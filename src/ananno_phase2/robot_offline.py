"""Configurable offline pick/place verifier, called during layout optimization."""
import json
import hashlib
import math
import time
from pathlib import Path
import numpy as np
from .ec66_model import EC66Model, pose_matrix
from .robot_rrt import rrt_connect

class OfflineRobotVerifier:
    def __init__(self,scene_path):
        self.path=Path(scene_path).resolve()
        self.config=json.loads(self.path.read_text(encoding='utf-8-sig'))
        c=self.config
        def file(key):return (self.path.parent/c[key]).resolve()
        self.robot=EC66Model(file('urdf'),file('srdf'),tip=c.get('tip_link','cup_link'))
        self.scale=float(c['length_scale_to_m'])
        self.distance=float(c.get('approach_distance_m',.05))
        self.resolution=float(c.get('joint_check_resolution_rad',.035))
        self.path_seconds=float(c.get('path_budget_seconds',2.))
        if not all(math.isfinite(v) and v>0 for v in [self.scale,self.distance,self.resolution,self.path_seconds]):raise ValueError('Robot scales, resolution and budgets must be positive')
        self.base_pallet=pose_matrix(c['base_T_pallet'])
        self.pick=pose_matrix(c['pick_tcp_pose'])
        self.grasp_rotation=pose_matrix(c['box_T_tcp_rotation'])[:3,:3]
        self.tcp_offset=np.asarray(c['tcp_offset_from_box_top_m'],dtype=float)
        if self.tcp_offset.shape!=(3,) or not np.all(np.isfinite(self.tcp_offset)):raise ValueError('TCP offset must be a finite three-vector')
        self.initial=np.asarray(c['initial_joints_rad'],dtype=float)
        if self.initial.shape!=(6,) or not np.all(np.isfinite(self.initial)) or np.any(self.initial<self.robot.lower) or np.any(self.initial>self.robot.upper):raise ValueError('Initial robot state is outside joint limits')
        self.obstacles=list(c.get('fixed_obstacles',[]))
        self.acceleration=np.asarray(c.get('joint_acceleration_limits_rad_s2',[.5]*6),dtype=float)
        if self.acceleration.shape!=(6,) or np.any(self.acceleration<=0) or not np.all(np.isfinite(self.acceleration)):raise ValueError('Invalid joint acceleration limits')
        self.calls=0;self.cache={}
        digest=hashlib.sha256(self.path.read_bytes()+self.robot.urdf.read_bytes()+self.robot.srdf.read_bytes())
        for name,data in sorted(self.robot.assets.items()):digest.update(name.encode()+data)
        self.model_fingerprint=digest.hexdigest()

    def _move(self,start,target,*,linear=False,cancelled=None):
        if not self.robot.valid(start):return None,'motion_start_state_in_collision'
        goal=self.robot.ik(target,start,seconds=self.path_seconds)
        if goal is None:return None,'ik_search_failed_or_colliding'
        if not linear:
            path=rrt_connect(start,goal,self.robot.lower,self.robot.upper,self.robot.valid,
                seconds=self.path_seconds,resolution=self.resolution,seed=1,cancelled=cancelled)
            return path,'path_budget_exhausted' if path is None else ''
        # Cartesian final approach is checked waypoint by waypoint, including joint edges.
        origin=self.robot.fk(start);count=max(2,int(math.ceil(np.linalg.norm(target[:3,3]-origin[:3,3])/.005)))
        path=[list(start)];deadline=time.monotonic()+self.path_seconds
        for i in range(1,count+1):
            if cancelled is not None and cancelled():raise InterruptedError('Robot planning cancelled')
            if time.monotonic()>=deadline:return None,'cartesian_approach_budget_exhausted'
            pose=target.copy();pose[:3,3]=origin[:3,3]+(target[:3,3]-origin[:3,3])*i/count
            q=self.robot.ik(pose,path[-1],restarts=0,seconds=max(.001,deadline-time.monotonic()))
            if q is None:return None,'cartesian_ik_search_failed'
            a=np.asarray(path[-1]);n=max(1,int(math.ceil(np.max(np.abs(q-a))/self.resolution)))
            for t in range(1,n+1):
                if cancelled is not None and cancelled():raise InterruptedError('Robot planning cancelled')
                if time.monotonic()>=deadline:return None,'cartesian_approach_budget_exhausted'
                if not self.robot.valid(a+(q-a)*t/n):return None,'cartesian_joint_edge_collision'
            path.append(q.tolist())
        return path,''

    def _timed(self,path):
        # Rest-to-rest cubic interpolation: max speed=1.5*dq/dt, max acceleration=6*dq/dt^2.
        elapsed=0.;points=[{'time_from_start':0.,'positions':list(path[0]),'velocities':[0.]*6}]
        for a,b in zip(path,path[1:]):
            delta=np.abs(np.asarray(b)-a)
            duration=max(.001,float(np.max(1.5*delta/self.robot.velocity)),float(np.sqrt(np.max(6*delta/self.acceleration))))
            elapsed+=duration;points.append({'time_from_start':elapsed,'positions':list(b),'velocities':[0.]*6})
        return points

    def verify(self,placements,pallet,approach,*,cancelled=None):
        if cancelled is not None and cancelled():raise InterruptedError('Robot planning cancelled')
        # Pallets are independently presented at the same workcell. Finish one
        # pallet before resetting to the configured state for the next pallet.
        ordered=sorted(placements,key=lambda p:(p.pallet_index,p.order))
        signature=(pallet.length,pallet.width,pallet.max_height,approach.open_direction,
            tuple((p.box.id,p.box.length,p.box.width,p.box.height,p.pallet_index,p.point.x,p.point.y,p.point.z,p.orientation.code,p.order,p.orientation.length,p.orientation.width,p.orientation.height) for p in ordered))
        if signature in self.cache:return self.cache[signature]
        self.calls+=1;began=time.monotonic();stages=[];placed=[];active_pallet=None;current=self.initial.copy();failure_operation=None
        budget=float(self.config.get('sequence_budget_seconds',30.))
        if not math.isfinite(budget) or budget<=0:raise ValueError('Sequence budget must be positive')
        thickness=float(self.config.get('pallet_thickness_m',.02))
        if not math.isfinite(thickness) or thickness<=0:raise ValueError('Pallet thickness must be positive')
        pallet_center=np.eye(4);pallet_center[:3,3]=[pallet.length*self.scale/2,pallet.width*self.scale/2,-thickness/2]
        environment=self.obstacles+[{'id':'pallet','size':[pallet.length*self.scale,pallet.width*self.scale,thickness],'pose':(self.base_pallet@pallet_center).tolist()}]
        def result(status,reason='',box_id=None):
            duration=sum(s['trajectory'][-1]['time_from_start'] for s in stages)
            report={'passed':status=='verified','status':status,'reason':reason,'box_id':box_id,
                'backend':'ec66_mujoco_rrt_connect','hardware_verified':False,
                'model_parameters_sha256':self.model_fingerprint,'failed_operation':failure_operation,
                'scene_calibration_status':self.config.get('calibration_status','not_measured'),
                'ik_verified':status=='verified','joint_path_verified':status=='verified',
                'collision_geometry':'provided_mesh_convex_hulls',
                'collision_validation':'discrete_joint_edges','joint_check_resolution_rad':self.resolution,
                'time_parameterization':'rest_to_rest_cubic','estimated_motion_seconds':duration,
                'wall_seconds':time.monotonic()-began,'joint_names':self.robot.names,
                'stages':stages,'final_joints_rad':current.tolist(),
                'assumptions':['No vacuum, payload dynamics or real controller verification',
                    'Each pallet independently starts at the configured robot state',
                    'Incoming box pose follows the configured pick TCP and grasp convention',
                    'Final approach Cartesian waypoints 5mm; joint edges discretely checked; no exact continuous-collision guarantee']}
            if len(self.cache)<128:self.cache[signature]=report
            return report
        def move(name,target,linear=False):
            nonlocal current,failure_operation
            failure_operation=name
            if time.monotonic()-began>budget:return 'sequence_budget_exhausted'
            path,reason=self._move(current,target,linear=linear,cancelled=cancelled)
            if path is None:return reason
            stages.append({'box_id':p.box.id,'pallet':p.pallet_index+1,'operation':name,
                'trajectory':self._timed(path),
                'joint_motion_rad':float(sum(np.sum(np.abs(np.asarray(b)-a)) for a,b in zip(path,path[1:]))),
                'tcp_path_length_m':float(sum(np.linalg.norm(self.robot.fk(b)[:3,3]-self.robot.fk(a)[:3,3]) for a,b in zip(path,path[1:]))),
                'carrying_box':self.robot.attachment is not None})
            current=np.asarray(path[-1]);return ''
        for p in ordered:
            if cancelled is not None and cancelled():raise InterruptedError('Robot planning cancelled')
            if p.pallet_index!=active_pallet:
                active_pallet=p.pallet_index;placed=[];current=self.initial.copy()
            self.robot.attachment=None
            size=np.array([p.box.length,p.box.width,p.box.height])*self.scale
            oriented_size=np.array([p.orientation.length,p.orientation.width,p.orientation.height])*self.scale
            box_tcp=np.eye(4);box_tcp[:3,:3]=self.grasp_rotation
            center=np.eye(4);center[:3,3]=np.array([p.point.x,p.point.y,p.point.z])*self.scale+oriented_size/2
            angle=math.pi/2 if p.orientation.code=='Z90' else 0.
            rotation=np.array([[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,1.]])
            center[:3,:3]=rotation
            box_tcp[:3,3]=np.array([0,0,size[2]/2])+self.tcp_offset
            source={'id':'pick_'+p.box.id,'size':size.tolist(),'pose':(self.pick@np.linalg.inv(box_tcp)).tolist(),'allowed_touch_links':['cup_link','link_base']}
            self.robot.set_obstacles(environment+placed+[source])
            if not self.robot.valid(current):return result('rejected','start_state_in_collision',p.box.id)
            target=self.base_pallet@center@box_tcp
            direction=np.zeros(3);direction['XYZ'.index(approach.open_direction[1])]=1 if approach.open_direction[0]=='+' else -1
            direction=self.base_pallet[:3,:3]@direction
            pre_pick=self.pick.copy();pre_pick[:3,3]+=[0,0,self.distance]
            pre_place=target.copy();pre_place[:3,3]+=direction*self.distance
            for name,pose,linear in [('approach_pick',pre_pick,False),('pick',self.pick,True)]:
                reason=move(name,pose,linear)
                if reason:return result('unverified',reason,p.box.id)
            self.robot.set_obstacles(environment+placed)
            self.robot.attachment=(size,np.linalg.inv(box_tcp))
            if not self.robot.valid(current):return result('rejected','carried_box_collision_at_pick',p.box.id)
            for name,pose,linear in [('lift',pre_pick,True),('transfer',pre_place,False),('place',target,True)]:
                reason=move(name,pose,linear)
                if reason:return result('unverified',reason,p.box.id)
            self.robot.attachment=None
            placed.append({'id':'placed_'+p.box.id,'size':size.tolist(),'pose':(self.base_pallet@center).tolist()})
            self.robot.set_obstacles(environment+placed)
            reason=move('retreat',pre_place,True)
            if reason:return result('unverified',reason,p.box.id)
        failure_operation=None
        return result('verified')
