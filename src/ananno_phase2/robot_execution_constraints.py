"""Layout pattern connectivity is independent of physical delivery order."""
from .paper_constraints import PaperConstraintSet,pattern_aligned
from .constraints import Feasibility


def pattern_connected(placements,pallet,cancelled=None):
    # Shared-vertex graph, indexed by EPS-sized cells. Neighbor cells retain
    # exact abs<=EPS comparisons, including points straddling bucket boundaries.
    from collections import defaultdict
    from itertools import product
    from math import floor
    from .paper_constraints import vertices
    from .constraints import EPS
    from .packer import check_cancelled
    for index in {p.pallet_index for p in placements}:
        items=[p for p in placements if p.pallet_index==index]
        parent=list(range(len(items)+1));buckets=defaultdict(list)
        def find(node):
            while parent[node]!=node:
                parent[node]=parent[parent[node]];node=parent[node]
            return node
        def cell(point):return tuple(floor(v/EPS) for v in point)
        for corner in product((0,pallet.length),(0,pallet.width),(0,)):
            buckets[cell(corner)].append((corner,0))
        for node,item in enumerate(items,1):
            check_cancelled(cancelled)
            for point in vertices(item):
                key=cell(point)
                for delta in product((-1,0,1),repeat=3):
                    for other,owner in buckets.get(tuple(k+d for k,d in zip(key,delta)),()):
                        if all(abs(a-b)<=EPS for a,b in zip(point,other)):
                            ra,rb=find(node),find(owner)
                            if ra!=rb:parent[ra]=rb
                buckets[key].append((point,node))
        check_cancelled(cancelled)
        if any(find(node)!=find(0) for node in range(1,len(items)+1)):return False
    return True


class RobotExecutionConstraintSet(PaperConstraintSet):
    def validate(self,candidate,placed,check_pattern=True):
        result=super().validate(candidate,placed,check_pattern=check_pattern)
        if not result.feasible:return result
        cfg=getattr(self,'tool_config',None)
        if not cfg or (cfg.get('tool_definition') or {}).get('kind')!='box_envelope':return result
        import math
        import numpy as np
        from .collision_acceleration import box_overlap
        scale=float(cfg['length_scale_to_m']);size=np.asarray(cfg['tool_definition']['size_m'])/scale
        angle=math.pi/2 if candidate.orientation.code=='Z90' else 0.
        box_rotation=np.array([[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,1.]])
        rotation=box_rotation@np.asarray(cfg['box_T_tcp_rotation'])[:3,:3]
        center=np.array([candidate.point.x+candidate.orientation.length/2,
                         candidate.point.y+candidate.orientation.width/2,candidate.point.z+candidate.orientation.height/2])
        from .robot_grasp import placement_grasp
        grasp=placement_grasp(candidate,placed,cfg,outside_side=getattr(self,'tool_outside_side',None))
        tcp=center+box_rotation@(np.asarray(grasp['box_T_tcp'])[:3,3]/scale)
        tool_center=tcp-rotation[:,2]*size[2]/2
        for other in placed:
            if other.pallet_index!=candidate.pallet_index or other.box.id==candidate.box.id:continue
            if other.z2<=tool_center[2]-float((np.abs(rotation)@(size/2))[2])+1e-5/scale:continue
            dimensions=np.array([other.orientation.length,other.orientation.width,other.orientation.height])
            other_center=np.array([other.point.x,other.point.y,other.point.z])+dimensions/2
            if box_overlap(tool_center,rotation,size/2,other_center,np.eye(3),dimensions/2,tolerance=1e-5/scale):
                return Feasibility(False,'吸盘放置包络与箱 '+other.box.id+' 干涉')
        return result

    def validate_pallet(self,placements):
        if not pattern_connected(placements,self.pallet,getattr(self,'cancelled',None)):
            return Feasibility(False,'箱体布局缺少与托盘角点连通的对齐关系')
        placed=[]
        for candidate in sorted(placements,key=lambda p:p.order):
            feasible=self.validate(candidate,placed,check_pattern=False)
            if not feasible.feasible:return feasible
            placed.append(candidate)
        state=self.stability(placed)
        if not state['quasi_static_tipping_pass']:return Feasibility(False,'托盘准静态倾倒检查失败')
        if not state['center_offset_pass']:return Feasibility(False,'托盘重心偏移超限')
        return Feasibility(True)
