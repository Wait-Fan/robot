"""原文六项硬约束的几何/质量部分与两项优化目标的基础度量。

稳定性模型及未给定参数的解释见 docs/full-reproduction-spec.md。
"""
import math
from itertools import product

from .constraints import EPS,Feasibility,_rectangle_union_area,aabb_overlap,fits_bounds,support_ratio
from .paper_config import PaperConfig


def type_key(box):
    return repr((box.group,box.length,box.width,box.height))


def vertices(item):
    return list(product((item.point.x,item.x2),(item.point.y,item.y2),(item.point.z,item.z2)))


def support_details(candidate,placed,inset_fraction=.01):
    ratio=support_ratio(candidate,placed)
    if candidate.point.z<=EPS: return ratio,4
    x,y=candidate.point.x,candidate.point.y
    l,w=candidate.orientation.length,candidate.orientation.width
    points=product((x+l*inset_fraction,x+l*(1-inset_fraction)),
                   (y+w*inset_fraction,y+w*(1-inset_fraction)))
    supporters=[p for p in placed if abs(p.z2-candidate.point.z)<=EPS]
    count=sum(any(p.point.x-EPS<=px<=p.x2+EPS and p.point.y-EPS<=py<=p.y2+EPS
                  for p in supporters) for px,py in points)
    return ratio,count


def pattern_aligned(candidate,placed,pallet):
    references=list(product((0,pallet.length),(0,pallet.width),(0,)))
    for item in placed: references.extend(vertices(item))
    # 所有棱均与坐标轴平行；共享顶点意味着相应轴向棱在同一直线上。
    return any(all(abs(a-b)<=EPS for a,b in zip(v,r))
               for v in vertices(candidate) for r in references)


def item_compactness(item,all_placements):
    low=(item.point.x,item.point.y,item.point.z)
    high=(item.x2,item.y2,item.z2)
    total=2*(item.orientation.length*item.orientation.width+
             item.orientation.length*item.orientation.height+
             item.orientation.width*item.orientation.height)
    contact=0.0
    for axis in range(3):
        others=[k for k in range(3) if k!=axis]
        a,b=others
        for side in (0,1):
            plane=(low,high)[side][axis]
            rectangles=[]
            if axis==2 and side==0 and abs(plane)<=EPS:
                rectangles.append((low[a],high[a],low[b],high[b]))
            for other in all_placements:
                if other is item or other.box.id==item.box.id or other.pallet_index!=item.pallet_index: continue
                olo=(other.point.x,other.point.y,other.point.z)
                ohi=(other.x2,other.y2,other.z2)
                if abs((ohi if side==0 else olo)[axis]-plane)>EPS: continue
                aa,ab=max(low[a],olo[a]),min(high[a],ohi[a])
                ba,bb=max(low[b],olo[b]),min(high[b],ohi[b])
                if ab-aa>EPS and bb-ba>EPS: rectangles.append((aa,ab,ba,bb))
            contact+=_rectangle_union_area(rectangles)
    return min(1.0,contact/total)


def mean_heterogeneity(placements):
    pallets={p.pallet_index for p in placements}
    if not pallets: return 0.0
    return sum(len({type_key(p.box) for p in placements if p.pallet_index==index}) for index in pallets)/len(pallets)


class PaperConstraintSet:
    def __init__(self,pallet,config=None):
        self.pallet=pallet
        self.config=config or PaperConfig()

    def validate(self,candidate,placed,check_pattern=True):
        if candidate.orientation not in candidate.box.orientations():
            return Feasibility(False,"违反Z轴姿态约束")
        if not fits_bounds(candidate,self.pallet): return Feasibility(False,"超出托盘边界")
        if any(aabb_overlap(candidate,p) for p in placed): return Feasibility(False,"箱体AABB碰撞")
        area,corners=support_details(candidate,placed,self.config.corner_inset_fraction)
        if not any(area+EPS>=threshold and corners>=minimum for threshold,minimum in ((.4,4),(.5,3),(.75,2))):
            return Feasibility(False,f"论文支撑规则不满足：面积{area:.3f}，内缩角点{corners}")
        if check_pattern and not pattern_aligned(candidate,placed,self.pallet):
            return Feasibility(False,"缺少与托盘或邻箱的共享顶点/对齐边")
        return Feasibility(True)

    def stability(self,placements):
        cfg=self.config
        mass=cfg.pallet_weight
        moments=[mass*self.pallet.length/2,mass*self.pallet.width/2,mass*cfg.pallet_com_height]
        substituted=0
        for item in placements:
            weight=item.box.weight
            if weight<=0:
                weight=cfg.missing_weight
                substituted+=1
            center=(item.point.x+item.orientation.length/2,item.point.y+item.orientation.width/2,
                    item.point.z+item.orientation.height/2)
            mass+=weight
            for axis in range(3): moments[axis]+=weight*center[axis]
        if mass<=0:
            center=(self.pallet.length/2,self.pallet.width/2,0)
        else: center=tuple(value/mass for value in moments)
        x,y,z=center
        dx,dy=abs(x-self.pallet.length/2),abs(y-self.pallet.width/2)
        centered=dx<=cfg.com_deviation_fraction*self.pallet.length+EPS and dy<=cfg.com_deviation_fraction*self.pallet.width+EPS
        # 加速度与长度单位必须相容。a/g无量纲，故z保留输入长度单位即可。
        sx,sy=abs(z)*cfg.acceleration_x/cfg.gravity,abs(z)*cfg.acceleration_y/cfg.gravity
        tipping=(x-sx>=-EPS and x+sx<=self.pallet.length+EPS and
                 y-sy>=-EPS and y+sy<=self.pallet.width+EPS)
        return {"center_of_mass":dict(zip(("x","y","z"),center)),"effective_mass":mass,
                "substituted_weight_count":substituted,"center_offset_pass":centered,
                "quasi_static_tipping_pass":tipping,"feasible":centered and tipping}

    def validate_pallet(self,placements):
        # 最终集合检查支持先按实际放置顺序重放，避免事后放上的箱子反向提供支撑。
        placed=[]
        for candidate in sorted(placements,key=lambda p:p.order):
            feasible=self.validate(candidate,placed)
            if not feasible.feasible: return feasible
            placed.append(candidate)
        state=self.stability(placed)
        if not state["quasi_static_tipping_pass"]: return Feasibility(False,"托盘准静态倾倒检查失败")
        if not state["center_offset_pass"]: return Feasibility(False,"托盘重心偏移超限")
        return Feasibility(True)
