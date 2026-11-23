"""允许开放侧的刚性箱体扫掠模型；机械臂运动由独立检查器验证。"""
from dataclasses import dataclass, replace

from .constraints import EPS
from .packer import check_cancelled
from .paper_constraints import PaperConstraintSet


@dataclass(frozen=True)
class ApproachConfig:
    # 表示来向：+X即箱体从目标的X正侧向目标运动。
    open_direction: str = '+Z'
    open_directions: tuple[str, ...] | None = None

    def __post_init__(self):
        directions = tuple(dict.fromkeys(self.open_directions)) if self.open_directions is not None else (self.open_direction,)
        if not directions or any(d not in ('+X','-X','+Y','-Y','+Z') for d in directions):
            raise ValueError('开放方向必须为+X/-X/+Y/-Y/+Z；不支持穿过托盘从底部接近')
        object.__setattr__(self, 'open_directions', directions)
        object.__setattr__(self, 'open_direction', directions[0])


def extent(item):
    return ((item.point.x,item.x2),(item.point.y,item.y2),(item.point.z,item.z2))


class OpenDirectionModel:
    def __init__(self, config=None):
        self.config=config or ApproachConfig()

    def blockers(self,candidate,placed,direction=None):
        direction=direction or self.config.open_direction
        if direction not in self.config.open_directions:raise ValueError('方向不在允许开放侧中')
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

    def available_directions(self,candidate,placed):
        return [d for d in self.config.open_directions if not self.blockers(candidate,placed,d)]


def _single_direction_sequence(placements,pallet,config,approach,cancelled=None):
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


def executable_sequence(placements,pallet,config,approach,cancelled=None):
    if len(approach.open_directions)==1:
        ordered,audit=_single_direction_sequence(placements,pallet,config,approach,cancelled)
        audit['open_directions']=list(approach.open_directions)
        for check in audit.get('checks',[]):check['open_direction']=approach.open_direction
        return ordered,audit
    model=OpenDirectionModel(approach);constraints=PaperConstraintSet(pallet,config)
    items={p.box.id:p for p in placements}
    if len(items)!=len(placements):raise ValueError('可执行序列中箱号重复')
    blockers={};supports={}
    for p in placements:
        check_cancelled(cancelled)
        blockers[p.box.id]={d:set(model.blockers(p,placements,d)) for d in approach.open_directions}
        supports[p.box.id]={q.box.id for q in placements if q.box.id!=p.box.id and
            q.pallet_index==p.pallet_index and abs(q.z2-p.point.z)<=EPS and all(
                min(extent(q)[k][1],extent(p)[k][1])-max(extent(q)[k][0],extent(p)[k][0])>EPS for k in (0,1))}
    remaining=set(items);placed_ids=set();ordered=[];directions=[];states=0;limit=10000
    def choices():
        for key in sorted(remaining,key=lambda k:(items[k].order,k)):
            check_cancelled(cancelled)
            if not supports[key].issubset(placed_ids):continue
            free=[d for d in approach.open_directions if not blockers[key][d].intersection(placed_ids)]
            if not free:continue
            previous=[p for p in ordered if p.pallet_index==items[key].pallet_index]
            if constraints.validate(items[key],previous).feasible:yield key,free[0]
    stack=[iter(choices())] if remaining else []
    while remaining and stack:
        check_cancelled(cancelled)
        try:key,direction=next(stack[-1])
        except StopIteration:
            stack.pop()
            if ordered:
                p=ordered.pop();directions.pop();remaining.add(p.box.id);placed_ids.remove(p.box.id)
            continue
        states+=1
        if states>limit:break
        ordered.append(replace(items[key],order=len(ordered)+1));directions.append(direction)
        remaining.remove(key);placed_ids.add(key)
        if remaining:stack.append(iter(choices()))
    passed=not remaining
    audit={'passed':passed,'open_direction':None,'open_directions':list(approach.open_directions),
           'search_states':states,'search_state_limit':limit,'checks':[
               {'box_id':p.box.id,'pallet':p.pallet_index+1,'source_sequence':items[p.box.id].order,
                'sequence':p.order,'passed':True,'blockers':[],'open_direction':d}
               for p,d in zip(ordered,directions)]}
    if not passed:
        audit.update(reason='approach_sequence_budget_exhausted' if states>limit else 'no_executable_open_side_sequence',remaining_ids=sorted(remaining))
        return None,audit
    for index in {p.pallet_index for p in ordered}:
        validation=constraints.validate_pallet([p for p in ordered if p.pallet_index==index])
        if not validation.feasible:
            audit.update(passed=False,reason=validation.reason);return None,audit
    audit['changed_order']=any(p.box.id!=q.box.id for p,q in zip(sorted(placements,key=lambda p:p.order),ordered))
    return ordered,audit
