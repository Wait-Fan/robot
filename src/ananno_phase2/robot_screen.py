"""Time-bounded endpoint screening; never a motion feasibility certificate."""
import math
import time
import numpy as np
from .ec66_model import pose_matrix
from .robot_grasp import placement_grasp,verifier_grasp_config


def screen_sequence(verifier,placements,pallet,approach,*,cancelled=None):
    approach=approach.calculation_config()
    v=verifier;started=time.monotonic();budget=float(v.config.get('screen_budget_seconds',1.))
    if not math.isfinite(budget) or budget<=0:raise ValueError('快速筛选预算必须为有限正数')
    checked=clear=0;placed=[];previous=[];active=None;seed=v.initial.copy();grasp_config=verifier_grasp_config(v)
    thickness=float(v.config.get('pallet_thickness_m',.02))
    center=np.eye(4);center[:3,3]=[pallet.length*v.scale/2,pallet.width*v.scale/2,-thickness/2]
    environment=v.obstacles+[{'id':'pallet','size':[pallet.length*v.scale,pallet.width*v.scale,thickness],
                              'pose':(v.base_pallet@center).tolist()}]
    ordered=sorted(placements,key=lambda p:(p.pallet_index,p.order))
    try:
        for p in ordered:
            if cancelled is not None and cancelled():raise InterruptedError('Robot screening cancelled')
            if time.monotonic()-started>=budget:break
            if p.pallet_index!=active:active=p.pallet_index;placed=[];previous=[];seed=v.initial.copy()
            size=np.array([p.box.length,p.box.width,p.box.height])*v.scale
            oriented=np.array([p.orientation.length,p.orientation.width,p.orientation.height])*v.scale
            box_tcp=np.asarray(placement_grasp(p,previous,grasp_config,outside_side=approach.outside_side)['box_T_tcp'])
            center=np.eye(4);center[:3,3]=np.array([p.point.x,p.point.y,p.point.z])*v.scale+oriented/2
            angle=math.pi/2 if p.orientation.code=='Z90' else 0.
            center[:3,:3]=[[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,1]]
            surface=v.config.get('pick_surface')
            if surface is not None:
                source=pose_matrix(surface['pose']).copy();source[:3,3]+=source[:3,2]*size[2]/2
                pick=source@box_tcp
            else:pick=v.pick;source=pick@np.linalg.inv(box_tcp)
            v.robot.attachment=None
            v.robot.set_obstacles(environment+placed+[{'id':'pick_'+p.box.id,'size':size.tolist(),
                'pose':source.tolist(),'allowed_touch_links':list(v.robot.touch_links)}])
            remaining=max(.001,budget-(time.monotonic()-started))
            pick_q=v.robot.ik(pick,seed,restarts=0,iterations=40,seconds=min(.05,remaining))
            target_q=None
            if time.monotonic()-started<budget:
                v.robot.set_obstacles(environment+placed);v.robot.attachment=(size,np.linalg.inv(box_tcp))
                remaining=max(.001,budget-(time.monotonic()-started))
                target_q=v.robot.ik(v.base_pallet@center@box_tcp,pick_q if pick_q is not None else seed,
                                   restarts=0,iterations=40,seconds=min(.05,remaining))
            checked+=1
            if pick_q is not None and target_q is not None:clear+=1
            if target_q is not None:seed=target_q
            placed.append({'id':'placed_'+p.box.id,'size':size.tolist(),'pose':(v.base_pallet@center).tolist()})
            previous.append(p)
    finally:v.robot.attachment=None
    # No IK solution in this short search is unknown, not proof of infeasibility.
    return {'passed':True,'status':'screened','reason':'full_motion_validation_pending',
            'requires_full_validation':True,'ik_verified':False,'joint_path_verified':False,
            'checked_endpoint_boxes':checked,'endpoint_clear_boxes':clear,'pending_boxes':len(ordered)-clear,
            'wall_seconds':time.monotonic()-started,'stages':[]}
