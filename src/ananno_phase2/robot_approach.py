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
    outside_side: str | None = None
    direction_policy: str = "first_feasible"

    def __post_init__(self):
        if self.direction_policy not in ("first_feasible","side_direct_first","preplace_optimized"):raise ValueError("未知接近方向选择策略")
        if self.outside_side not in (None,'+X','-X','+Y','-Y'):raise ValueError('里外基准必须为水平外侧+X/-X/+Y/-Y')
        directions = tuple(dict.fromkeys(self.open_directions)) if self.open_directions is not None else (self.open_direction,)
        if not directions or any(d not in ('+X','-X','+Y','-Y','+Z') for d in directions):
            raise ValueError('开放方向必须为+X/-X/+Y/-Y/+Z；不支持穿过托盘从底部接近')
        object.__setattr__(self, 'open_directions', directions)
        object.__setattr__(self, 'open_direction', directions[0])


def extent(item):
    return ((item.point.x,item.x2),(item.point.y,item.y2),(item.point.z,item.z2))



def outside_side_from_workcell(pallet,base_T_pallet,*,length_scale_to_m=1.0):
    """Robot base origin expressed in the pallet frame, reduced to a horizontal side.

    A base projected inside the pallet or exactly on a diagonal has no unique
    outside side. Return None and require a manual reference rather than guess.
    """
    if base_T_pallet is None:return None
    import math
    try:
        matrix=[[float(v) for v in row] for row in base_T_pallet]
        if len(matrix)!=4 or any(len(row)!=4 for row in matrix):raise ValueError()
        if not all(math.isfinite(v) for row in matrix for v in row):raise ValueError()
        if any(abs(matrix[3][k]-(1 if k==3 else 0))>1e-6 for k in range(4)):raise ValueError()
        for a in range(3):
            for b in range(3):
                if abs(sum(matrix[r][a]*matrix[r][b] for r in range(3))-(a==b))>1e-6:raise ValueError()
    except (TypeError,ValueError,OverflowError) as exc:
        raise ValueError('工位变换矩阵必须为有限的4×4刚体变换') from exc
    scale=float(length_scale_to_m)
    if not math.isfinite(scale) or scale<=0:raise ValueError('长度单位换算必须为有限正数')
    length,width=pallet.length*scale,pallet.width*scale
    robot=[-sum(matrix[r][axis]*matrix[r][3] for r in range(3)) for axis in (0,1)]
    if EPS<robot[0]<length-EPS and EPS<robot[1]<width-EPS:return None
    relative=[(robot[0]-length/2)/(length/2),(robot[1]-width/2)/(width/2)]
    if abs(abs(relative[0])-abs(relative[1]))<=1e-9:return None
    axis=0 if abs(relative[0])>abs(relative[1]) else 1
    return ('+' if relative[axis]>0 else '-')+'XY'[axis]


def _sequence_priority(item,approach):
    if approach.outside_side is None:return (item.order,item.box.id)
    axis='XY'.index(approach.outside_side[1]);bounds=extent(item)[axis]
    center=(bounds[0]+bounds[1])/2
    far_first=center if approach.outside_side[0]=='+' else -center
    return (item.pallet_index,far_first,item.point.z,item.order,item.box.id)


def ordered_directions(directions,approach):
    """Geometry-only ranking; actual Cartesian feasibility requires robot verification."""
    return sorted(directions,key=lambda d:d=='+Z') if approach.direction_policy in ('side_direct_first','preplace_optimized') else list(directions)


class OpenDirectionModel:
    def __init__(self, config=None):
        self.config=config or ApproachConfig()

    def blockers(self,candidate,placed,direction=None):
        direction=direction or self.config.open_direction
        if direction not in self.config.open_directions:raise ValueError('方向不在允许开放侧中')
        if self.config.direction_policy=='preplace_optimized':return []
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
        # Elevated preplacement is not an infinite horizontal box sweep. These
        # are candidates only: the full robot checks the finite diagonal entry.
        if self.config.direction_policy=='preplace_optimized':
            return ordered_directions(self.config.open_directions,self.config)
        return [d for d in ordered_directions(self.config.open_directions,self.config) if not self.blockers(candidate,placed,d)]


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
        ready=sorted((key for key in remaining if indegree[key]==0),key=lambda key:_sequence_priority(items[key],approach))
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


def _executable_sequence(placements,pallet,config,approach,cancelled=None):
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
        for key in sorted(remaining,key=lambda k:_sequence_priority(items[k],approach)):
            check_cancelled(cancelled)
            if not supports[key].issubset(placed_ids):continue
            free=[d for d in ordered_directions(approach.open_directions,approach) if not blockers[key][d].intersection(placed_ids)]
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


def anchor_inside_out(placements,pallet,outside_side):
    """Reflect generated layouts to the far corner; original box dimensions stay fixed."""
    if outside_side not in ('-X','-Y'):return list(placements)
    from .models import Point3D
    axis='XY'.index(outside_side[1]);limit=(pallet.length,pallet.width)[axis]
    result=[]
    for p in placements:
        xyz=[p.point.x,p.point.y,p.point.z];xyz[axis]=limit-(p.x2,p.y2)[axis]
        result.append(replace(p,point=Point3D(*xyz)))
    return result


def _strict_sequence(placements,pallet,config,approach,cancelled=None):
    from .robot_execution_constraints import RobotExecutionConstraintSet,pattern_connected
    model=OpenDirectionModel(approach);constraints=RobotExecutionConstraintSet(pallet,config)
    constraints.cancelled=cancelled
    if not pattern_connected(placements,pallet,cancelled):return None,{"passed":False,"reason":"layout_pattern_disconnected","checks":[]}
    if len({p.box.id for p in placements})!=len(placements):raise ValueError('可执行序列中箱号重复')
    items={p.box.id:p for p in placements};edges={key:set() for key in items};indegree={key:0 for key in items}
    axis='XY'.index(approach.outside_side[1]);positive=approach.outside_side[0]=='+'
    def edge(before,after):
        if after not in edges[before]:edges[before].add(after);indegree[after]+=1
    groups={}
    for p in placements:groups.setdefault(p.pallet_index,[]).append(p)
    for group in groups.values():
        for p in group:
            check_cancelled(cancelled)
            a=extent(p)
            for q in group:
                if q.box.id==p.box.id:continue
                b=extent(q)
                # Depth intervals must be fully separated to impose a hard
                # frontier. Overlapping footprints may need the same support.
                deeper=(a[axis][1]<=b[axis][0]+EPS if positive else a[axis][0]>=b[axis][1]-EPS)
                if deeper:edge(p.box.id,q.box.id)
                if abs(p.z2-q.point.z)<=EPS and all(min(a[k][1],b[k][1])-max(a[k][0],b[k][0])>EPS for k in (0,1)):
                    edge(p.box.id,q.box.id)
    ordered=[];checks=[];remaining=set(items)
    while remaining:
        check_cancelled(cancelled)
        ready=[items[key] for key in remaining if indegree[key]==0]
        if not ready:return None,{'passed':False,'reason':'strict_inside_out:support_depth_dependency_cycle',
                                  'remaining_ids':sorted(remaining),'checks':checks}
        p=min(ready,key=lambda p:_sequence_priority(p,approach))
        previous=[q for q in ordered if q.pallet_index==p.pallet_index]
        valid=constraints.validate(p,previous,check_pattern=False)
        available=model.available_directions(p,previous)
        if not valid.feasible or not available:
            return None,{'passed':False,'reason':'strict_inside_out:'+ (valid.reason if not valid.feasible else 'all_open_sides_blocked'),
                         'box_id':p.box.id,'checks':checks,'open_directions':list(approach.open_directions),'open_direction':approach.open_direction}
        ordered.append(replace(p,order=len(ordered)+1))
        remaining.remove(p.box.id)
        for key in edges[p.box.id]:indegree[key]-=1
        checks.append({'box_id':p.box.id,'pallet':p.pallet_index+1,'source_sequence':p.order,
                       'sequence':len(ordered),'passed':True,'blockers':[],'open_direction':available[0]})
    for index in {p.pallet_index for p in ordered}:
        valid=constraints.validate_pallet([p for p in ordered if p.pallet_index==index])
        if not valid.feasible:return None,{'passed':False,'reason':valid.reason,'checks':checks}
    return ordered,{'passed':True,'checks':checks,'open_direction':approach.open_direction,
        'open_directions':list(approach.open_directions),'changed_order':any(p.box.id!=q.box.id for p,q in zip(sorted(placements,key=lambda p:p.order),ordered))}


def executable_sequence(placements,pallet,config,approach,cancelled=None):
    ordered,audit=(_strict_sequence if approach.outside_side else _executable_sequence)(placements,pallet,config,approach,cancelled)
    audit['direction_selection_policy']=approach.direction_policy
    audit['direction_choice_status']='geometric_candidate_only'
    audit['sequencing_policy']={'name':'whole_pallet_depth_frontier' if approach.outside_side else 'original_feasible_order',
        'outside_side':approach.outside_side,'preference_only':not bool(approach.outside_side),'fallback_used':False,
        'priority':['pallet','support_and_depth_dependencies','far_to_near','base_height','source_order'] if approach.outside_side else ['source_order'],
        'hard_constraints_take_precedence':True,'strict_inside_out':bool(approach.outside_side)}
    return ordered,audit
