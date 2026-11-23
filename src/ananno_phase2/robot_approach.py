"""2025固定开放方向的刚性箱体扫掠模型；不进行机械臂IK或关节轨迹规划。"""
from dataclasses import dataclass, replace

from .constraints import EPS
from .packer import check_cancelled
from .paper_constraints import PaperConstraintSet


@dataclass(frozen=True)
class ApproachConfig:
    # 表示来向：+X即箱体从目标的X正侧向目标运动。
    open_direction: str = '+Z'

    def __post_init__(self):
        if self.open_direction not in ('+X','-X','+Y','-Y','+Z'):
            raise ValueError('开放方向必须为+X/-X/+Y/-Y/+Z；不支持穿过托盘从底部接近')


def extent(item):
    return ((item.point.x,item.x2),(item.point.y,item.y2),(item.point.z,item.z2))


class OpenDirectionModel:
    def __init__(self, config=None):
        self.config=config or ApproachConfig()

    def blockers(self,candidate,placed):
        direction=self.config.open_direction
        axis='XYZ'.index(direction[1]);positive=direction[0]=='+'
        target=extent(candidate)
        result=[]
        for other in placed:
            if other.pallet_index!=candidate.pallet_index or other.box.id==candidate.box.id:continue
            bounds=extent(other)
            if not all(min(target[k][1],bounds[k][1])-max(target[k][0],bounds[k][0])>EPS
                       for k in range(3) if k!=axis):continue
            if (bounds[axis][1]>target[axis][0]+EPS if positive else bounds[axis][0]<target[axis][1]-EPS):
                result.append(other.box.id)
        return result


def executable_sequence(placements,pallet,config,approach,cancelled=None):
    """遮挡A←B要求A先于B；下方接触支撑物要求先于上箱。展开依赖并重放旧约束。

    采用所有底面接触支撑箱为前置条件，是保守假设；不穷举不同支撑子集。
    开放方向固定时，依赖展开替代递归遍历，避免Python递归深度限制。
    """
    model=OpenDirectionModel(approach);constraints=PaperConstraintSet(pallet,config)
    items={p.box.id:p for p in placements}
    if len(items)!=len(placements):raise ValueError('可执行序列中箱号重复')
    edges={key:set() for key in items};indegree={key:0 for key in items}
    def edge(before,after):
        if after not in edges[before]:edges[before].add(after);indegree[after]+=1
    for candidate in placements:
        check_cancelled(cancelled)
        for blocker in model.blockers(candidate,placements):edge(candidate.box.id,blocker)
        for lower in placements:
            if lower.pallet_index!=candidate.pallet_index or lower.box.id==candidate.box.id:continue
            if abs(lower.z2-candidate.point.z)<=EPS and all(
                min(extent(lower)[k][1],extent(candidate)[k][1])-max(extent(lower)[k][0],extent(candidate)[k][0])>EPS
                for k in (0,1)):
                edge(lower.box.id,candidate.box.id)
    remaining=set(items);ordered=[];checks=[]
    while remaining:
        check_cancelled(cancelled)
        accepted=None
        ready=sorted((key for key in remaining if indegree[key]==0),key=lambda key:(items[key].order,key))
        for key in ready:
            candidate=items[key];previous=[p for p in ordered if p.pallet_index==candidate.pallet_index]
            if constraints.validate(candidate,previous).feasible and not model.blockers(candidate,previous):
                accepted=key;break
        if accepted is None:
            return None,{'passed':False,'open_direction':approach.open_direction,
                         'reason':'blocking_dependency_cycle_or_support_alignment_failure',
                         'remaining_ids':sorted(remaining),'checks':checks}
        original=items[accepted];sequence=len(ordered)+1
        ordered.append(replace(original,order=sequence));remaining.remove(accepted)
        checks.append({'box_id':accepted,'pallet':original.pallet_index+1,'source_sequence':original.order,
                       'sequence':sequence,'passed':True,'blockers':[]})
        for after in edges[accepted]:indegree[after]-=1
    for index in {p.pallet_index for p in ordered}:
        result=constraints.validate_pallet([p for p in ordered if p.pallet_index==index])
        if not result.feasible:return None,{'passed':False,'reason':result.reason,'checks':checks,
                                            'open_direction':approach.open_direction}
    return ordered,{'passed':True,'open_direction':approach.open_direction,'checks':checks,
                    'changed_order':any(p.box.id!=q.box.id for p,q in zip(sorted(placements,key=lambda p:p.order),ordered)),
                    'dependency_edges':sum(len(v) for v in edges.values())}
