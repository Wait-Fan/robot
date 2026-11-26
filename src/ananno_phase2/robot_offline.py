"""Configurable offline pick/place verifier, called during layout optimization."""
import json
import hashlib
import math
import time
import copy
from collections import OrderedDict
from pathlib import Path
import numpy as np
from .ec66_model import EC66Model, pose_matrix, _rotvec
from .robot_rrt import rrt_connect
from .robot_approach import OpenDirectionModel
from .robot_profiles import identify_robot
from .robot_validation_settings import planning_options
from .robot_grasp import placement_grasp,verifier_grasp_config
from .robot_motion import motion_options,preplace_pose
from .joint_trajectory import smooth_trajectory,evaluate_segment

class _BoxBudgetExpired(Exception):pass


class OfflineRobotVerifier:
    def __init__(self,scene_path):
        self.path=Path(scene_path).resolve()
        self.config=json.loads(self.path.read_text(encoding='utf-8-sig'))
        c=self.config;settings=planning_options(c);motion_options(c)
        def file(key):return (self.path.parent/c[key]).resolve()
        actual_robot=identify_robot(file('urdf'))
        if c.get('robot_id',actual_robot)!=actual_robot:raise ValueError('机械臂型号与URDF模型不一致')
        c.setdefault('robot_id',actual_robot)
        c.setdefault('robot_name','EC66' if actual_robot=='ec66' else 'FANUC R-2000iC/210L')
        self.robot=EC66Model(file('urdf'),file('srdf'),tip=c.get('tip_link','cup_link'),
            tool_definition=c.get('tool_definition'),touch_links=c.get('touch_links'))
        self.scale=float(c['length_scale_to_m'])
        self.distance=float(c.get('approach_distance_m',.05))
        self.resolution=float(c.get('joint_check_resolution_rad',.035))
        self.path_seconds=settings['path_budget_seconds']
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
        self.calls=0;self.cache={};self.prefix_cache=OrderedDict()
        self.tiered_validation=settings['tiered_validation']
        digest=hashlib.sha256(self.path.read_bytes()+self.robot.urdf.read_bytes()+self.robot.srdf.read_bytes())
        for name,data in sorted(self.robot.assets.items()):digest.update(name.encode()+data)
        self.model_fingerprint=digest.hexdigest()

    def set_log_callback(self,callback):self.log_callback=callback

    def screen(self,placements,pallet,approach,*,cancelled=None):
        from .robot_screen import screen_sequence
        return screen_sequence(self,placements,pallet,approach,cancelled=cancelled)

    def configure_pallet_axes(self,input_pallet):
        """Map the new calculation frame into the existing physical pallet frame."""
        canonical=input_pallet.with_long_side_x()
        convention=self.config.get('pallet_frame_convention','input_length_width')
        if convention not in ('input_length_width','long_side_x'):
            raise ValueError('pallet_frame_convention必须为input_length_width或long_side_x')
        if not hasattr(self,'_scene_base_pallet'):
            self._scene_base_pallet=self.base_pallet.copy()
            self._scene_model_fingerprint=self.model_fingerprint
        old_T_new=np.eye(4)
        swapped=input_pallet.length<input_pallet.width
        if swapped and convention=='input_length_width':
            # X_new=+Y_old, Y_new=-X_old, O_new=(L_old,0,0): right handed.
            old_T_new[:3,:3]=[[0,-1,0],[1,0,0],[0,0,1]]
            old_T_new[0,3]=input_pallet.length*self.scale
        self.base_pallet=self._scene_base_pallet@old_T_new
        self.pallet_frame_mapping={'scene_convention':convention,'calculation_convention':'long_side_x',
            'input_dimensions':[input_pallet.length,input_pallet.width,input_pallet.max_height],
            'axes_swapped':swapped,'scene_pallet_T_calculation_pallet':old_T_new.tolist()}
        self.model_fingerprint=hashlib.sha256((self._scene_model_fingerprint+
            json.dumps(self.pallet_frame_mapping,sort_keys=True)).encode()).hexdigest()
        self.cache.clear();self.prefix_cache=OrderedDict();self.pallet_cache=OrderedDict()
        return canonical

    def _move(self,start,target,*,linear=False,cancelled=None):
        deadline=time.monotonic()+self.path_seconds
        if cancelled is not None and cancelled():raise InterruptedError("Robot planning cancelled")
        if not self.robot.valid(start):return None,'motion_start_state_in_collision'
        if not linear:
            remaining=deadline-time.monotonic()
            if remaining<=0:return None,'path_budget_exhausted'
            goal=self.robot.ik(target,start,seconds=remaining)
            if cancelled is not None and cancelled():raise InterruptedError('Robot planning cancelled')
            remaining=deadline-time.monotonic()
            if remaining<=0:return None,'path_budget_exhausted'
            if goal is None:return None,'ik_search_failed_or_colliding'
            path=rrt_connect(start,goal,self.robot.lower,self.robot.upper,self.robot.valid,
                seconds=remaining,resolution=self.resolution,seed=1,cancelled=cancelled)
            return path,'path_budget_exhausted' if path is None else ''
        # Cartesian final approach is checked waypoint by waypoint, including joint edges.
        origin=self.robot.fk(start)
        rotvec=_rotvec(target[:3,:3]@origin[:3,:3].T);angle=float(np.linalg.norm(rotvec))
        axis=rotvec/angle if angle>1e-12 else np.zeros(3)
        cross=np.array([[0,-axis[2],axis[1]],[axis[2],0,-axis[0]],[-axis[1],axis[0],0]])
        count=max(2,int(math.ceil(np.linalg.norm(target[:3,3]-origin[:3,3])/.005)),int(math.ceil(angle/.05)))
        path=[list(start)]
        for i in range(1,count+1):
            if cancelled is not None and cancelled():raise InterruptedError('Robot planning cancelled')
            if time.monotonic()>=deadline:return None,'cartesian_approach_budget_exhausted'
            fraction=i/count;pose=target.copy()
            pose[:3,3]=origin[:3,3]+(target[:3,3]-origin[:3,3])*fraction
            theta=angle*fraction
            pose[:3,:3]=(np.eye(3)+math.sin(theta)*cross+(1-math.cos(theta))*(cross@cross))@origin[:3,:3]
            q=self.robot.ik(pose,path[-1],restarts=0,seconds=max(.001,deadline-time.monotonic()))
            if q is None:return None,'cartesian_ik_search_failed'
            a=np.asarray(path[-1]);n=max(1,int(math.ceil(np.max(np.abs(q-a))/self.resolution)))
            for t in range(1,n+1):
                if cancelled is not None and cancelled():raise InterruptedError('Robot planning cancelled')
                if time.monotonic()>=deadline:return None,'cartesian_approach_budget_exhausted'
                if not self.robot.valid(a+(q-a)*t/n):return None,'cartesian_joint_edge_collision'
            path.append(q.tolist())
        return path,''

    def _timed(self,path,*,linear=False,cancelled=None):
        def cartesian_corridor(q,a,b):
            left,right,pose=self.robot.fk(a),self.robot.fk(b),self.robot.fk(q)
            delta=right[:3,3]-left[:3,3];length=float(delta@delta)
            fraction=float(np.clip((pose[:3,3]-left[:3,3])@delta/length,0,1)) if length>1e-16 else 0.
            if np.linalg.norm(pose[:3,3]-left[:3,3]-fraction*delta)>.001:return False
            # Each original Cartesian edge rotates by <=.05rad. Bound the
            # smoothed attitude to both endpoints to prevent wrist excursions.
            return max(np.linalg.norm(_rotvec(pose[:3,:3]@p[:3,:3].T)) for p in (left,right))<=.06
        return smooth_trajectory(path,self.robot.velocity,self.acceleration,self.robot.valid,
            lower=getattr(self.robot,'lower',np.full(6,-np.inf)),upper=getattr(self.robot,'upper',np.full(6,np.inf)),
            resolution=self.resolution,shortcut=not linear,cancelled=cancelled,
            segment_valid=cartesian_corridor if linear else None)

    def verify(self,placements,pallet,approach,*,cancelled=None):
        from .robot_verification_cache import verify_pallets
        return verify_pallets(self,placements,pallet,approach,cancelled=cancelled)

    def _verify_sequence(self,placements,pallet,approach,*,cancelled=None):
        if cancelled is not None and cancelled():raise InterruptedError('Robot planning cancelled')
        # Pallets are independently presented at the same workcell. Finish one
        # pallet before resetting to the configured state for the next pallet.
        ordered=sorted(placements,key=lambda p:(p.pallet_index,p.order))
        context=hashlib.sha256(json.dumps({'model':self.model_fingerprint,'config':self.config,
            'base_pallet':self.base_pallet.tolist(),'pick':self.pick.tolist(),'initial':self.initial.tolist(),
            'obstacles':self.obstacles,'scale':self.scale,'distance':self.distance,'resolution':self.resolution,
            'path_seconds':self.path_seconds,'acceleration':self.acceleration.tolist(),
            'grasp_rotation':self.grasp_rotation.tolist(),'tcp_offset':self.tcp_offset.tolist()},
            sort_keys=True,default=lambda v:v.tolist()).encode()).hexdigest()
        context=hashlib.sha256((context+'edge_grasp_elevated_prepose_c2_v2'+str(approach.outside_side)).encode()).hexdigest()
        options=motion_options(self.config);grasp_config=verifier_grasp_config(self)
        signature=(context,pallet.length,pallet.width,pallet.max_height,approach.open_directions,approach.direction_policy,
            tuple((p.box.id,p.box.length,p.box.width,p.box.height,p.pallet_index,p.point.x,p.point.y,p.point.z,p.orientation.code,p.order,p.orientation.length,p.orientation.width,p.orientation.height) for p in ordered))
        if signature in self.cache:return copy.deepcopy(self.cache[signature])
        self.calls+=1;began=time.monotonic();stages=[];placed=[];active_pallet=None;current=self.initial.copy();failure_operation=None
        directions_by_box=[];previous_geometry=[];side_model=OpenDirectionModel(approach)
        budget=float(self.config.get('box_budget_seconds',self.config.get('sequence_budget_seconds',30.)))
        if not hasattr(self,'prefix_cache'):self.prefix_cache=OrderedDict()
        reused=0;prefix=context;box_began=began
        if not math.isfinite(budget) or budget<=0:raise ValueError('Per-box validation budget must be positive')
        thickness=float(self.config.get('pallet_thickness_m',.02))
        if not math.isfinite(thickness) or thickness<=0:raise ValueError('Pallet thickness must be positive')
        pallet_center=np.eye(4);pallet_center[:3,3]=[pallet.length*self.scale/2,pallet.width*self.scale/2,-thickness/2]
        environment=self.obstacles+[{'id':'pallet','size':[pallet.length*self.scale,pallet.width*self.scale,thickness],'pose':(self.base_pallet@pallet_center).tolist()}]
        def result(status,reason='',box_id=None):
            callback=getattr(self,'log_callback',None)
            if callback:callback(f'机器人验证结果：{status}；箱 {box_id or "全部"}；原因 {reason or "通过当前序列验证"}')
            duration=sum(s['trajectory'][-1]['time_from_start'] for s in stages)
            report={'passed':status=='verified','status':status,'reason':reason,'box_id':box_id,
                'backend':self.config.get('robot_id','ec66')+'_mujoco_rrt_connect','hardware_verified':False,
                'robot_id':self.config.get('robot_id','ec66'),'robot_name':self.config.get('robot_name','EC66'),
                'tool_definition':self.config.get('tool_definition'),'tool_status':self.config.get('tool_status','not_site_calibrated'),
                'model_parameters_sha256':self.model_fingerprint,'failed_operation':failure_operation,
                'scene_calibration_status':self.config.get('calibration_status','not_measured'),
                'pallet_frame_mapping':getattr(self,'pallet_frame_mapping',None),
                'open_directions':list(approach.open_directions),'direction_selection_policy':approach.direction_policy,
                'directions_by_box':list(directions_by_box),
                'ik_verified':status=='verified','joint_path_verified':status=='verified',
                'collision_geometry':'provided_mesh_convex_hulls',
                'collision_validation':'discrete_smoothed_joint_curves','joint_check_resolution_rad':self.resolution,
                'time_parameterization':'piecewise_quintic_c2','estimated_motion_seconds':duration,
                'trajectory_smoothing':'collision_checked_shortcut_and_c2_quintic',
                'trajectory_velocity_limits_rad_s':self.robot.velocity.tolist(),
                'trajectory_acceleration_limits_rad_s2':self.acceleration.tolist(),
                'motion_options':options,
                'wall_seconds':time.monotonic()-began,'joint_names':self.robot.names,
                'budget_scope':'per_box','box_budget_seconds':budget,'reused_prefix_boxes':reused,
                'collision_acceleration':'conservative_aabb_then_original_narrowphase',
                'collision_statistics':dict(getattr(self.robot,'collision_stats',{})),
                'ik_cache_hits':getattr(self.robot,'ik_cache_hits',0),
                'stages':stages,'final_joints_rad':current.tolist(),
                'assumptions':['No vacuum, payload dynamics or real controller verification',
                    'Each pallet independently starts at the configured robot state',
                    'Incoming box pose follows the configured pick TCP and grasp convention',
                    'Final approach Cartesian waypoints 5mm; joint edges discretely checked; no exact continuous-collision guarantee']}
            if status=='verified':
                if len(self.cache)>=16:self.cache.pop(next(iter(self.cache)))
                self.cache[signature]=copy.deepcopy(report)
            return report
        def move(name,target,linear=False):
            nonlocal current,failure_operation
            failure_operation=name
            callback=getattr(self,'log_callback',None)
            if callback:callback(f'机器人验证：箱 {box_number}/{len(ordered)}（{p.box.id}），托盘 {p.pallet_index+1}，动作 {name}')
            def box_cancelled():
                if cancelled is not None and cancelled():return True
                if time.monotonic()-box_began>=budget:raise _BoxBudgetExpired()
                return False
            if time.monotonic()-box_began>=budget:return 'box_validation_budget_exhausted'
            try:
                path,reason=self._move(current,target,linear=linear,cancelled=box_cancelled)
                trajectory=self._timed(path,linear=linear,cancelled=box_cancelled) if path is not None else None
            except _BoxBudgetExpired:return 'box_validation_budget_exhausted'
            except ValueError as exc:return 'trajectory_smoothing_failed:'+str(exc)
            if time.monotonic()-box_began>=budget:return 'box_validation_budget_exhausted'
            if path is None:return reason
            samples=[]
            for a,b in zip(trajectory,trajectory[1:]):
                samples.extend(evaluate_segment(a,b,u)[0] for u in np.linspace(0,1,9)[:-1])
            samples.append(np.asarray(trajectory[-1]['positions']))
            stages.append({'box_id':p.box.id,'pallet':p.pallet_index+1,'operation':name,
                'trajectory':trajectory,'target_tcp_pose':target.tolist(),
                'path_mode':'cartesian_linear' if linear else 'joint_rrt_connect',
                'joint_motion_rad':float(sum(np.sum(np.abs(b-a)) for a,b in zip(samples,samples[1:]))),
                'tcp_path_length_m':float(sum(np.linalg.norm(self.robot.fk(b)[:3,3]-self.robot.fk(a)[:3,3]) for a,b in zip(samples,samples[1:]))),
                'path_metrics':'sampled_smoothed_curve',
                'carrying_box':self.robot.attachment is not None})
            current=np.asarray(path[-1]);return ''
        for box_number,p in enumerate(ordered,1):
            if cancelled is not None and cancelled():raise InterruptedError('Robot planning cancelled')
            if p.pallet_index!=active_pallet:
                active_pallet=p.pallet_index;placed=[];previous_geometry=[];current=self.initial.copy()
                prefix=hashlib.sha256(repr((context,pallet.length,pallet.width,pallet.max_height,
                    approach.open_directions,approach.direction_policy)).encode()).hexdigest()
            box_began=time.monotonic()
            placement_key=(p.box.id,p.box.length,p.box.width,p.box.height,p.point.x,p.point.y,p.point.z,
                p.orientation.code,p.orientation.length,p.orientation.width,p.orientation.height)
            prefix=hashlib.sha256((prefix+repr(placement_key)+repr(current.tolist())).encode()).hexdigest()
            cached=self.prefix_cache.get(prefix)
            if cached is not None:
                current=cached['q'].copy();placed.append(copy.deepcopy(cached['obstacle']));previous_geometry.append(p)
                restored=copy.deepcopy(cached['stages'])
                for stage in restored:stage['pallet']=p.pallet_index+1
                stages.extend(restored)
                direction=copy.deepcopy(cached['direction']);direction['pallet']=p.pallet_index+1
                directions_by_box.append(direction);self.prefix_cache.move_to_end(prefix);reused+=1
                self.robot.attachment=None;self.robot.set_obstacles(environment+placed)
                callback=getattr(self,'log_callback',None)
                if callback:callback(f'机器人验证：箱 {box_number}/{len(ordered)}（{p.box.id}），复用完整已验证前缀')
                continue
            available=side_model.available_directions(p,previous_geometry)
            if not available:return result('rejected','all_allowed_open_sides_blocked',p.box.id)
            box_stage_start=len(stages)
            self.robot.attachment=None
            size=np.array([p.box.length,p.box.width,p.box.height])*self.scale
            oriented_size=np.array([p.orientation.length,p.orientation.width,p.orientation.height])*self.scale
            grasp=placement_grasp(p,previous_geometry,grasp_config,outside_side=approach.outside_side)
            box_tcp=np.asarray(grasp['box_T_tcp'])
            center=np.eye(4);center[:3,3]=np.array([p.point.x,p.point.y,p.point.z])*self.scale+oriented_size/2
            angle=math.pi/2 if p.orientation.code=='Z90' else 0.
            rotation=np.array([[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,1.]])
            center[:3,:3]=rotation
            surface=self.config.get('pick_surface')
            if surface is not None:
                surface_pose=pose_matrix(surface['pose']);source_pose=surface_pose.copy()
                source_pose[:3,3]+=surface_pose[:3,2]*size[2]/2
                pick=source_pose@box_tcp;pick_direction=surface_pose[:3,2]
            else:
                pick=self.pick;source_pose=pick@np.linalg.inv(box_tcp);pick_direction=np.array([0.,0,1.])
            source={'id':'pick_'+p.box.id,'size':size.tolist(),'pose':source_pose.tolist(),
                'allowed_touch_links':self.config.get('touch_links',['cup_link','link_base'])}
            self.robot.set_obstacles(environment+placed+[source])
            if not self.robot.valid(current):return result('rejected','start_state_in_collision',p.box.id)
            target=self.base_pallet@center@box_tcp
            pre_pick=pick.copy();pre_pick[:3,3]+=pick_direction*self.distance
            for name,pose,linear in [('approach_pick',pre_pick,False),('pick',pick,True)]:
                reason=move(name,pose,linear)
                if reason:return result('unverified',reason,p.box.id)
            self.robot.set_obstacles(environment+placed)
            self.robot.attachment=(size,np.linalg.inv(box_tcp))
            if not self.robot.valid(current):return result('rejected','carried_box_collision_at_pick',p.box.id)
            lift_pose=pick.copy();lift_pose[:3,3]+=np.array([0.,0.,options['pick_lift_m']]) if approach.direction_policy=='preplace_optimized' else pick_direction*self.distance
            reason=move('lift',lift_pose,True)
            if reason:return result('unverified',reason,p.box.id)
            held_state=current.copy();held_stage_count=len(stages);placed_count=len(placed);attempts=[]
            def entry_pose(chosen_direction):
                if approach.direction_policy=='preplace_optimized':return preplace_pose(target,self.base_pallet,chosen_direction,options)
                local_axis='XYZ'.index(chosen_direction[1]);positive=chosen_direction[0]=='+'
                travel=self.distance
                if approach.direction_policy=='side_direct_first' and local_axis<2:
                    low=(p.point.x,p.point.y)[local_axis]*self.scale
                    width=oriented_size[local_axis];limit=(pallet.length,pallet.width)[local_axis]*self.scale
                    travel=max(travel,(limit-low if positive else low+width)+self.distance)
                direction=np.zeros(3);direction[local_axis]=1 if positive else -1
                pose=target.copy();pose[:3,3]+=self.base_pallet[:3,:3]@direction*travel
                return pose
            if approach.direction_policy=='preplace_optimized':
                origin=self.robot.fk(held_state)[:3,3]
                routes=[(d,'joint_rrt_optimized') for d in sorted(available,key=lambda d:float(np.linalg.norm(entry_pose(d)[:3,3]-origin)))]
            elif approach.direction_policy=='side_direct_first':
                origin=self.robot.fk(held_state)[:3,3]
                horizontal=sorted((d for d in available if d!='+Z'),key=lambda d:float(np.linalg.norm(entry_pose(d)[:3,3]-origin)))
                routes=[(d,'cartesian_direct') for d in horizontal]+[(d,'joint_rrt') for d in horizontal]
                routes.extend((d,'joint_rrt') for d in available if d=='+Z')
            else:routes=[(d,'joint_rrt') for d in available]
            best=None;reason='no_valid_preplacement_route'
            for chosen_direction,transfer_mode in routes:
                # Preserve a complete feasible route if the remaining budget
                # cannot afford another full candidate; never publish a prefix.
                if best is not None and budget-(time.monotonic()-box_began)<max(.01,3*self.path_seconds):break
                callback=getattr(self,'log_callback',None)
                if callback:callback(f'机器人验证：箱 {box_number}/{len(ordered)}（{p.box.id}），尝试方向 {chosen_direction}，路径 {transfer_mode}')
                if cancelled is not None and cancelled():raise InterruptedError('Robot planning cancelled')
                current=held_state.copy();del stages[held_stage_count:];del placed[placed_count:]
                self.robot.set_obstacles(environment+placed)
                self.robot.attachment=(size,np.linalg.inv(box_tcp))
                pre_place=entry_pose(chosen_direction)
                reason=move('transfer',pre_place,transfer_mode=='cartesian_direct')
                if not reason:reason=move('place',target,True)
                if not reason:
                    self.robot.attachment=None
                    placed.append({'id':'placed_'+p.box.id,'size':size.tolist(),'pose':(self.base_pallet@center).tolist()})
                    self.robot.set_obstacles(environment+placed)
                    reason=move('retreat',pre_place,True)
                if callback:callback(f'机器人验证：箱 {box_number}/{len(ordered)}（{p.box.id}），方向 {chosen_direction}/{transfer_mode}，'+('通过' if not reason else '未通过：'+reason))
                attempts.append({'open_direction':chosen_direction,'transfer_mode':transfer_mode,'passed':not bool(reason),'reason':reason})
                if not reason:
                    cost=sum(s['trajectory'][-1]['time_from_start'] for s in stages[held_stage_count:])
                    attempts[-1]['estimated_motion_seconds']=cost
                    if best is None or cost<best['cost']:
                        best={'cost':cost,'current':current.copy(),'stages':copy.deepcopy(stages[box_stage_start:]),
                              'obstacle':copy.deepcopy(placed[-1]),'direction':chosen_direction,
                              'mode':transfer_mode,'pre_place':pre_place.copy()}
                    if approach.direction_policy!='preplace_optimized':break
                if time.monotonic()-box_began>=budget:break
            if best is None:return result('unverified',reason,p.box.id)
            current=best['current'];del stages[box_stage_start:];stages.extend(best['stages'])
            del placed[placed_count:];placed.append(best['obstacle']);self.robot.attachment=None;self.robot.set_obstacles(environment+placed)
            chosen_direction=best['direction'];pre_place=best['pre_place'];transfer_mode=best['mode']
            for stage in stages[box_stage_start:]:stage['open_direction']=chosen_direction
            directions_by_box.append({'box_id':p.box.id,'pallet':p.pallet_index+1,
                'open_direction':chosen_direction,'transfer_mode':transfer_mode,'grasp':grasp,
                'entry_tcp_pose':pre_place.tolist(),'attempts':attempts,
                'selection':'lowest_estimated_time_among_complete_checked_candidates' if approach.direction_policy=='preplace_optimized' else 'first_complete_checked_candidate'})
            previous_geometry.append(p)
            self.prefix_cache[prefix]={'q':current.copy(),'obstacle':copy.deepcopy(placed[-1]),
                'stages':copy.deepcopy(stages[box_stage_start:]),'direction':copy.deepcopy(directions_by_box[-1])}
            self.prefix_cache.move_to_end(prefix)
            if len(self.prefix_cache)>max(512,2*len(ordered)):self.prefix_cache.popitem(last=False)
        failure_operation=None
        return result('verified')
