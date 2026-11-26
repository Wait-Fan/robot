"""可审计的两阶段研究流程；原文未给定细节见复现说明。"""
from collections import defaultdict
from importlib.metadata import version,PackageNotFoundError
import math
import sys

from .constraints import EPS
from .models import PackingResult,Placement,Point3D
from .packer import check_cancelled
from .paper_config import PaperConfig
from .paper_constraints import PaperConstraintSet,item_compactness,mean_heterogeneity,type_key


class NoPaperSolution(ValueError):
    """输入或设定的硬约束下未能找到完整装运方案。"""


ASSUMPTIONS=[
    "功能流程版，尚未完成作者实验参数/基准数值等价验证",
    "角点按底面尺寸相对内缩；原文未给出实验内缩数值",
    "COM偏移、空托盘质量/COM、缺失重量替代值均为显式实现参数",
    "倾倒检查采用准静态合力投影，非运输动态稳定性认证",
    "异质性为各已用托盘不同箱型数均值；原文未给出完整归一化公式",
    "箱型按产品标识和原始尺寸联合区分；缺失产品标识按尺寸区分",
    "不宣称全局最优，无法找到满足所有硬约束的方案会显式报错",
]


def annotate_document(document,diagnostics):
    document["algorithm"]="Ananno 2024 two-stage research implementation"
    document["is_complete_reproduction"]=False
    document["reproduction_status"]="two_phase_workflow_implemented_numerical_equivalence_unverified"
    document["paper_diagnostics"]=diagnostics
    labels=diagnostics.get("box_type_labels",{})
    for pallet in document["pallets"]:
        for item in pallet["packed_items"]:
            if item["id"] in labels: item["box_type"]=labels[item["id"]]
    return document


class PaperTwoPhasePacker:
    def __init__(self,pallet,config=None):
        self.pallet=pallet
        self.config=config or PaperConfig()
        self.constraints=PaperConstraintSet(pallet,self.config)
        self.diagnostics={}

    def _make_layer_builder(self,cancelled=None,log=None):
        from .paper_layers import PaperLayerBuilder
        return PaperLayerBuilder(self.pallet,self.config,cancelled=cancelled,log=log)

    def _optimize_types(self,groups,evaluation,cancelled=None,log=None):
        from .paper_ga import optimize_types
        return optimize_types(groups,evaluation,self.config,cancelled=cancelled,log=log)

    def pack(self,boxes,*,progress=None,cancelled=None,log=None):
        from .paper_layers import PaperLayerBuilder
        ids=[box.id for box in boxes]
        if len(ids)!=len(set(ids)): raise ValueError("箱号不可重复")
        check_cancelled(cancelled)
        for box in boxes:
            values=(box.length,box.width,box.height,box.weight)
            if not all(math.isfinite(v) for v in values): raise ValueError("箱体尺寸/重量必须有限")
            if not any(o.length<=self.pallet.length+EPS and o.width<=self.pallet.width+EPS
                       and o.height<=self.pallet.max_height+EPS for o in box.orientations()):
                raise NoPaperSolution(f"{box.id} 在两个允许姿态下都无法装入空托盘，不能满足完整装运")
        if progress: progress(0,len(boxes))
        if log: log("Phase 1：构造整层、半层、四分之一层与块。")
        phase1=self._make_layer_builder(cancelled=cancelled,log=log).build(boxes)
        initial=list(phase1.placements)
        residuals=list(phase1.residuals)
        diagnostics=dict(phase1.diagnostics)
        diagnostics["phase1_box_count"]=len(initial)
        dimensions_by_product=defaultdict(set)
        for box in boxes: dimensions_by_product[box.group].add((box.length,box.width,box.height))
        type_labels={box.id:(box.group if box.group and len(dimensions_by_product[box.group])==1 else
                    f"{box.group or 'SIZE'}[{box.length:g}x{box.width:g}x{box.height:g}]") for box in boxes}
        try: deap_version=version("deap")
        except PackageNotFoundError: deap_version=None
        self.diagnostics={"config":self.config.to_dict(),"implementation_assumptions":ASSUMPTIONS,
                          "phase1":diagnostics,"residual_box_count":len(residuals),"ga_attempts":[],
                          "box_type_labels":type_labels,
                          "runtime":{"python":sys.version,"executable":sys.executable,"deap":deap_version}}
        if progress: progress(len(initial),len(boxes))
        if not residuals:
            result=PackingResult(initial,[],self.pallet)
        else:
            from .paper_ga import optimize_types
            groups=defaultdict(list)
            for box in residuals: groups[type_key(box)].append(box)
            free_volume=phase1.pallet_count*self.pallet.volume-sum(p.box.volume for p in initial)
            additional=max(0,math.ceil((sum(b.volume for b in residuals)-free_volume-EPS)/self.pallet.volume))
            count=max(1,phase1.pallet_count+additional)
            limit=min(self.config.max_pallets,phase1.pallet_count+len(residuals))
            result=None
            while count<=limit:
                check_cancelled(cancelled)
                if log: log(f"Phase 2：{len(residuals)} 个剩余箱、{len(groups)} 种箱型，固定 {count} 盘运行 GA。")
                evaluation=lambda sequence:self.evaluate_sequence(groups,sequence,initial,count,cancelled)
                optimized=self._optimize_types(dict(groups),evaluation,cancelled=cancelled,log=log)
                self.diagnostics["ga_attempts"].append({"available_pallets":count,"feasible":optimized.best is not None,
                    "best_type_sequence":optimized.sequence,"generations":optimized.trace})
                if optimized.best is not None:
                    result=optimized.best.payload
                    break
                if log: log("当前盘数下未找到全部硬约束可行解；增加一盘并重启 GA。")
                count+=1
            if result is None:
                raise NoPaperSolution(f"在最多 {limit} 盘内未找到满足全部硬约束的完整方案；请检查COM/支撑参数或箱体数据。")
        check_cancelled(cancelled)
        if {p.box.id for p in result.placements}!=set(ids) or len(result.placements)!=len(boxes):
            raise RuntimeError("两阶段箱体守恒校验失败")
        audits=[]
        for index in range(result.pallet_count):
            placed=[p for p in result.placements if p.pallet_index==index]
            valid=self.constraints.validate_pallet(placed)
            if not valid.feasible: raise NoPaperSolution(f"最终托盘{index+1}检查失败：{valid.reason}")
            audits.append({"pallet_index":index+1,**self.constraints.stability(placed)})
        residual_ids={b.id for b in residuals}
        compact=[item_compactness(p,result.placements) for p in result.placements if p.box.id in residual_ids]
        self.diagnostics.update({"all_hard_constraints_pass":True,"pallet_stability":audits,
            "mean_pallet_type_count":mean_heterogeneity(result.placements),
            "mean_residual_compactness":sum(compact)/len(compact) if compact else None,
            "hard_constraints":["orientation","non_collision","pallet_stability","support","pattern_alignment","complete_shipment"],
            "soft_constraints":["customer_positioning","layer_interlocking"]})
        if progress: progress(len(boxes),len(boxes))
        return result

    def evaluate_sequence(self,groups,sequence,initial,pallet_count,cancelled=None):
        from .paper_ga import TypeEvaluation
        if len(sequence)!=len(groups) or set(sequence)!=set(groups):
            raise ValueError("GA箱型排列不完整或重复")
        states=[{"placed":[],"points":set()} for _ in range(pallet_count)]
        for item in initial:
            states[item.pallet_index]["placed"].append(item)
            states[item.pallet_index]["points"].update(Point3D(x,y,item.z2)
                for x in (item.point.x,item.x2) for y in (item.point.y,item.y2))
        for state in states:
            if not state["placed"]: state["points"].add(Point3D(0,0,0))
        placements=list(initial)
        next_order=max((p.order for p in initial),default=0)+1
        residual_items=[]
        for key in sequence:
            for box in groups[key]:
                check_cancelled(cancelled)
                points=sorted(((index,point) for index,state in enumerate(states) if index not in getattr(self,"_sealed_pallet_indices",set()) for point in state["points"]),
                              key=lambda pair:(pair[1].z,pair[1].x**2+pair[1].y**2,pair[0],pair[1].x,pair[1].y))
                accepted=None
                for index,point in points:
                    check_cancelled(cancelled)
                    for orientation in box.orientations():
                        candidate=Placement(box,index,point,orientation,next_order)
                        if self.constraints.validate(candidate,states[index]["placed"]).feasible:
                            accepted=candidate
                            break
                    if accepted: break
                if accepted is None: return TypeEvaluation(False,float("inf"),-1,None)
                state=states[accepted.pallet_index]
                state["placed"].append(accepted)
                state["points"].discard(accepted.point)
                state["points"].update((Point3D(accepted.x2,accepted.point.y,accepted.point.z),
                    Point3D(accepted.point.x,accepted.y2,accepted.point.z),Point3D(accepted.point.x,accepted.point.y,accepted.z2)))
                state["points"]={p for p in state["points"] if p.x<self.pallet.length-EPS
                                  and p.y<self.pallet.width-EPS and p.z<self.pallet.max_height-EPS}
                placements.append(accepted)
                residual_items.append(accepted)
                next_order+=1
        if any(not self.constraints.stability(state["placed"])["feasible"] for state in states if state["placed"]):
            return TypeEvaluation(False,float("inf"),-1,None)
        compact=sum(item_compactness(p,placements) for p in residual_items)/len(residual_items) if residual_items else 0
        return TypeEvaluation(True,mean_heterogeneity(placements),compact,PackingResult(placements,[],self.pallet))
