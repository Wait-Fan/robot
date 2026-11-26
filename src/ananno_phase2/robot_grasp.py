"""One per-box grasp convention for screening, motion, filtering and replay."""
import math
import numpy as np


def verifier_grasp_config(verifier):
    return dict(verifier.config,length_scale_to_m=verifier.scale,
        box_T_tcp_rotation=np.block([[verifier.grasp_rotation,np.zeros((3,1))],[np.zeros((1,3)),np.ones((1,1))]]).tolist(),
        tcp_offset_from_box_top_m=verifier.tcp_offset.tolist(),base_T_pallet=verifier.base_pallet.tolist())


def placement_grasp(p,placed,config,*,outside_side=None):
    scale=float(config['length_scale_to_m'])
    angle=math.pi/2 if p.orientation.code=='Z90' else 0.
    box_rotation=np.array([[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,1.]])
    dimensions=np.array([p.orientation.length,p.orientation.width,p.orientation.height])*scale
    low=np.array([p.point.x,p.point.y,p.point.z])*scale;high=low+dimensions
    center=(low+high)/2
    grasp=np.asarray(config['box_T_tcp_rotation'],dtype=float).copy()
    grasp[:3,3]=np.array([0.,0.,p.box.height*scale/2])+np.asarray(config['tcp_offset_from_box_top_m'],dtype=float)
    tool=config.get('tool_definition') or {}
    policy=config.get('grasp_alignment','occupied_edges' if tool.get('kind')=='box_envelope' else 'center')
    if policy not in ('center','occupied_edges'):raise ValueError('未知吸盘对齐方式')
    record={'policy':policy,'box_T_tcp':grasp.tolist(),'aligned_sides':[]}
    if tool.get('kind')!='box_envelope':return record
    tool_size=np.asarray(tool['size_m'],dtype=float);rotation=box_rotation@grasp[:3,:3]
    half=np.abs(rotation)@(tool_size/2)
    tcp=center+box_rotation@grasp[:3,3]
    tool_center=tcp-rotation[:,2]*tool_size[2]/2
    if policy=='occupied_edges':
        # Exact two-edge alignment is defined for a level rectangular suction
        # plate. Refuse tilted/oblique rectangles instead of inventing contact.
        if abs(abs(rotation[2,2])-1)>1e-7 or np.max(np.abs(rotation[:2,2]))>1e-7 or not np.allclose(np.abs(rotation[:2,:2]).sum(axis=0),1,atol=1e-7):
            raise ValueError('两边对齐需要吸盘面水平且与箱边平行；请修正抓取姿态或选择中心吸取')
        selected=[]
        for axis in (0,1):
            transverse=1-axis;candidates=[]
            for q in placed:
                if q.pallet_index!=p.pallet_index or q.box.id==p.box.id:continue
                qlow=np.array([q.point.x,q.point.y,q.point.z])*scale
                qhigh=qlow+np.array([q.orientation.length,q.orientation.width,q.orientation.height])*scale
                if min(high[transverse],qhigh[transverse])-max(low[transverse],qlow[transverse])<=1e-9:continue
                if qhigh[2]<=low[2]+1e-9:continue  # Supporting boxes do not occupy a lateral edge.
                if qhigh[axis]<=low[axis]+1e-9:sign='-';gap=low[axis]-qhigh[axis]
                elif qlow[axis]>=high[axis]-1e-9:sign='+';gap=qlow[axis]-high[axis]
                else:continue
                # Prioritize boxes that actually reach above this box's top.
                candidates.append((qhigh[2]<=high[2]+1e-9,gap,str(q.box.id),sign))
            if candidates:sign=min(candidates)[-1]
            elif outside_side and outside_side[1]=='XY'[axis]:sign='-' if outside_side[0]=='+' else '+'
            else:
                base=config.get('base_T_pallet')
                if base is not None:
                    matrix=np.asarray(base,dtype=float);robot_pallet=-matrix[:3,:3].T@matrix[:3,3]
                    sign='+' if robot_pallet[axis]<=center[axis] else '-'
                else:sign='-'
            tool_center[axis]=(high[axis]-half[axis]) if sign=='+' else (low[axis]+half[axis])
            selected.append(sign+'XY'[axis])
        tcp=tool_center+rotation[:,2]*tool_size[2]/2
        grasp[:3,3]=box_rotation.T@(tcp-center)
        record.update(box_T_tcp=grasp.tolist(),aligned_sides=selected)
    record['tool_bounds_pallet_m']=[[float(tool_center[k]-half[k]),float(tool_center[k]+half[k])] for k in range(3)]
    return record
