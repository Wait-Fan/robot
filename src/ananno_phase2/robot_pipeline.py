"""在继承的2024优化内部加入2025开放侧模型，记录研究实现边界。"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from .paper_pipeline import PaperTwoPhasePacker,NoPaperSolution,annotate_document
from .paper_layers import PaperLayerBuilder,LayerBuildResult
from .paper_ga import TypeEvaluation
from .robot_approach import ApproachConfig,executable_sequence


class RobotLayerBuilder(PaperLayerBuilder):
    def __init__(self,*args,approach,robot_verifier=None,**kwargs):
        super().__init__(*args,**kwargs);self.approach=approach;self.robot_verifier=robot_verifier

    def build(self,boxes):
        result=super().build(boxes)
        kept=[];failed=[];events=[]
        for index in sorted({p.pallet_index for p in result.placements}):
            items=[p for p in result.placements if p.pallet_index==index]
            ordered,audit=executable_sequence(items,self.pallet,self.config,self.approach,self.cancelled)
            if ordered is not None and self.robot_verifier is not None:
                robot_audit=self.robot_verifier.verify(ordered,self.pallet,self.approach,cancelled=self.cancelled)
                if not robot_audit['passed']:
                    ordered=None;audit={'reason':'robot_'+robot_audit.get('status','unverified')+':'+robot_audit.get('reason','unknown')}
            if ordered is None:
                failed.append({'pallet':index+1,'reason':audit['reason'],'boxes':len(items)});continue
            new_index=len({p.pallet_index for p in kept})
            for p in ordered:kept.append(replace(p,pallet_index=new_index,order=len(kept)+1))
            for event in result.diagnostics['layer_placements']:
                if event['pallet_index']==index:events.append({**event,'pallet_index':new_index})
        ids={p.box.id for p in kept};residuals=[b for b in boxes if b.id not in ids]
        diagnostics=dict(result.diagnostics)
        diagnostics.update(baseline_phase1_box_count=len(result.placements),phase1_box_count=len(kept),
                           placed_count=len(kept),residual_count=len(residuals),layer_placements=events,
                           robot_rejected_blocks=failed,
                           layers_placed={kind:sum(e['kind']==kind for e in events) for kind in ('full','half','quarter')})
        if self.log:self.log(f'2025开放侧：第一阶段保留{len(kept)}箱，退回GA的块{len(failed)}个。')
        return LayerBuildResult(kept,residuals,len({p.pallet_index for p in kept}),diagnostics)


class RobotTwoPhasePacker(PaperTwoPhasePacker):
    def __init__(self,pallet,config=None,approach=None,robot_verifier=None):
        super().__init__(pallet,config);self.approach=approach or ApproachConfig()
        self.robot_diagnostics={};self.evaluations=0;self.rejected=0
        self.robot_verifier=robot_verifier;self.robot_rejected=0

    def _make_layer_builder(self,cancelled=None,log=None):
        return RobotLayerBuilder(self.pallet,self.config,cancelled=cancelled,log=log,approach=self.approach,robot_verifier=self.robot_verifier)

    def evaluate_sequence(self,groups,sequence,initial,pallet_count,cancelled=None):
        evaluated=super().evaluate_sequence(groups,sequence,initial,pallet_count,cancelled)
        if not evaluated.feasible:return evaluated
        self.evaluations+=1
        ordered,audit=executable_sequence(evaluated.payload.placements,self.pallet,self.config,self.approach,cancelled)
        if ordered is None:
            self.rejected+=1
            return TypeEvaluation(False,float('inf'),-1,None)
        if self.robot_verifier is not None:
            audit=self.robot_verifier.verify(ordered,self.pallet,self.approach,cancelled=cancelled)
            if not audit['passed']:
                self.robot_rejected+=1
                return TypeEvaluation(False,float('inf'),-1,None)
        payload=replace(evaluated.payload,placements=ordered)
        return TypeEvaluation(True,evaluated.heterogeneity,evaluated.compactness,payload)

    def pack(self,boxes,*,progress=None,cancelled=None,log=None):
        self.evaluations=self.rejected=self.robot_rejected=0
        if log:
            log(f'Ananno2025固定来向{self.approach.open_direction}；'+
                ('已启用EC66离线IK、碰撞与路径验证。' if self.robot_verifier is not None else '轻量开放侧模型，未启用机械臂IK/关节轨迹验证。'))
        result=super().pack(boxes,progress=progress,cancelled=cancelled,log=log)
        ordered,audit=executable_sequence(result.placements,self.pallet,self.config,self.approach,cancelled)
        if ordered is None:raise NoPaperSolution('2025最终开放侧序列验证失败：'+audit['reason'])
        motion_audit=None
        if self.robot_verifier is not None:
            motion_audit=self.robot_verifier.verify(ordered,self.pallet,self.approach,cancelled=cancelled)
            if not motion_audit['passed']:
                raise NoPaperSolution('EC66最终序列验证未通过：'+motion_audit.get('reason','unknown'))
        self.robot_diagnostics={**audit,'model':'fixed_open_direction_rigid_box_sweep',
            'evaluations_inside_ga':self.evaluations,'rejected_inside_ga':self.rejected,
            'ik_verified':False,'joint_trajectory_verified':False,'robotstudio_verified':False,
            'assumptions':['Fixed axis-aligned straight final approach; box AABB only; gripper/arm not modeled',
                'All contacting lower boxes are conservative support prerequisites',
                'Failed Phase1 pallet blocks return to GA as implementation choice',
                'Each pallet is independently presented at the same workcell; inter-pallet obstacles not modeled',
                'Dependency traversal implements paper-inspired sequencing, not claimed exact Algorithm1/2 source equivalence']}
        if motion_audit is not None:
            self.robot_diagnostics.update(model='ec66_mesh_ik_rrt_connect',ik_verified=True,
                joint_trajectory_verified=True,robot_rejected_inside_ga=self.robot_rejected,
                motion_verification=motion_audit)
            self.robot_diagnostics['assumptions']=motion_audit['assumptions']
        return replace(result,placements=ordered)


def annotate_robot_document(document,packer):
    annotate_document(document,packer.diagnostics)
    document['algorithm']='Ananno 2025 fixed-open-direction research implementation'
    document['reproduction_status']='lightweight_approach_model_integrated_robot_validation_pending'
    if packer.robot_verifier is not None:
        document['algorithm']='Ananno2025 research extension with offline EC66 IK/collision/RRT-Connect'
        document['reproduction_status']='ec66_offline_model_extension_not_hardware_verified'
    document['robot_diagnostics']=packer.robot_diagnostics
    root=Path(__file__).resolve().parents[2]
    manifest=root/'provenance/baseline_2024_manifest.json'
    baseline=json.loads(manifest.read_text(encoding='utf-8'))
    document['provenance']={'baseline':baseline['baseline'],'source_project':baseline['source_project'],
        'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'snapshot_sha256':baseline['snapshot_sha256'],'paper_2025_doi':'10.1016/j.ifacol.2025.09.338'}
    return document
