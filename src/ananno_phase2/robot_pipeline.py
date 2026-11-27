"""在继承的2024优化内部加入2025开放侧模型，记录研究实现边界。"""
from dataclasses import replace
from types import SimpleNamespace
import hashlib
import json
from pathlib import Path

from .paper_pipeline import PaperTwoPhasePacker,NoPaperSolution,annotate_document
from .paper_layers import PaperLayerBuilder,LayerBuildResult
from .paper_ga import TypeEvaluation
from .robot_approach import ApproachConfig,executable_sequence,anchor_inside_out
from .run_control import PackingTimedOut,RobotPlanningIncomplete



def _validated_sequence(placements,pallet,config,approach,verifier=None,cancelled=None):
    """Validate requested strict sequence; never silently relax its outside reference."""
    attempts=[approach]
    # Explicit user requirement: never fall back to an outside-first sequence.
    preferred_failure=None;last_motion=None;seen=set()
    for index,policy in enumerate(attempts):
        ordered,audit=executable_sequence(placements,pallet,config,policy,cancelled)
        if ordered is None:
            preferred_failure=preferred_failure or audit.get('reason','geometry_sequence_failed')
            continue
        signature=tuple((p.pallet_index,p.box.id) for p in ordered)
        if signature in seen:break
        seen.add(signature)
        motion=verifier.verify(ordered,pallet,approach,cancelled=cancelled) if verifier is not None else None
        if motion is not None and not motion['passed']:
            if motion.get('status')=='unverified' or motion.get('reason') in ('sequence_budget_exhausted','box_validation_budget_exhausted'):
                raise RobotPlanningIncomplete('机器人当前局部路径尚未通过，未判定垛型不可行。箱 '+str(motion.get('box_id','未知'))+
                    '，动作 '+str(motion.get('failed_operation','未知'))+'，原因 '+str(motion.get('reason','未知'))+
                    ('；诊断：'+str(motion['diagnostic_file']) if motion.get('diagnostic_file') else '；详情见运行日志。'),
                    motion_report=motion,placements=ordered,audit=audit)
            last_motion=motion
            audit['reason']='robot_'+motion.get('status','unverified')+':'+motion.get('reason','unknown')
            audit['passed']=False
            preferred_failure=preferred_failure or audit['reason']
            continue
        if index:
            audit['sequencing_policy'].update(outside_side=approach.outside_side,
                requested_policy='bottom_up_inside_out',fallback_used=True,fallback_reason=preferred_failure)
        return ordered,audit,motion
    audit.update(passed=False,reason=preferred_failure or audit.get('reason','no_verified_sequence'))
    return None,audit,last_motion


class RobotLayerBuilder(PaperLayerBuilder):
    def __init__(self,*args,approach,robot_verifier=None,owner=None,**kwargs):
        super().__init__(*args,**kwargs);self.approach=approach;self.robot_verifier=robot_verifier;self.owner=owner

    def build(self,boxes):
        result=super().build(boxes)
        result.placements[:]=anchor_inside_out(result.placements,self.pallet,self.approach.outside_side)
        kept=[];failed=[];events=[];pending=[];retained_prefixes=[];protected=set()
        pallet_ids=sorted({p.pallet_index for p in result.placements})
        for pallet_number,index in enumerate(pallet_ids,1):
            items=[p for p in result.placements if p.pallet_index==index]
            if self.log:self.log(f'机器人验证：第一阶段托盘 {pallet_number}/{len(pallet_ids)}，{len(items)} 箱')
            partial=False
            try:ordered,audit,_=_validated_sequence(items,self.pallet,self.config,self.approach,self.robot_verifier,self.cancelled)
            except RobotPlanningIncomplete as problem:
                pending.append({'pallet':index+1,'reason':str(problem),'boxes':len(items)})
                ordered,audit=self._verified_prefix(problem)
                partial=ordered is not None
                if ordered is None:
                    if self.log:self.log(f'第一阶段托盘 {index+1} 暂无可保留的完整前缀，继续检查其他托盘。')
                    continue
            if ordered is None:
                failed.append({'pallet':index+1,'reason':audit['reason'],'boxes':len(items)});continue
            new_index=len({p.pallet_index for p in kept})
            for p in ordered:kept.append(replace(p,pallet_index=new_index,order=len(kept)+1))
            if partial:
                protected.add(new_index)
                retained_prefixes.append({'source_pallet':index+1,'pallet':new_index+1,'retained_boxes':len(ordered),'deferred_boxes':len(items)-len(ordered)})
                events.append({'pallet_index':new_index,'kind':'verified_prefix','box_count':len(ordered)})
                if self.log:self.log(f'第一阶段托盘 {index+1} 保留并封存已验证 {len(ordered)} 箱；仅失败箱和尾部 {len(items)-len(ordered)} 箱另行安排，继续下一盘。')
            else:
                for event in result.diagnostics['layer_placements']:
                    if event['pallet_index']==index:events.append({**event,'pallet_index':new_index})
        ids={p.box.id for p in kept};residuals=[b for b in boxes if b.id not in ids]
        diagnostics=dict(result.diagnostics)
        diagnostics.update(baseline_phase1_box_count=len(result.placements),phase1_box_count=len(kept),
                           placed_count=len(kept),residual_count=len(residuals),layer_placements=events,
                           robot_rejected_blocks=failed,
                           robot_motion_pending_blocks=pending,robot_retained_prefixes=retained_prefixes,
                           layers_placed={kind:sum(e['kind']==kind for e in events) for kind in ('full','half','quarter')})
        if self.log:self.log(f'2025开放侧：第一阶段保留{len(kept)}箱；恢复部分托盘 {len(retained_prefixes)} 盘，待安排余箱 {len(residuals)} 箱。')
        if self.owner is not None:
            self.owner._sealed_pallet_indices=({p.pallet_index for p in kept} if self.owner.seal_verified_pallets else protected)
            if self.log and self.owner._sealed_pallet_indices:self.log(f'已封存 {len(self.owner._sealed_pallet_indices)} 盘，已验证前缀不会被重新填入箱子。')
        return LayerBuildResult(kept,residuals,len({p.pallet_index for p in kept}),diagnostics)

    def _verified_prefix(self,problem):
        report=problem.motion_report or {};ordered=problem.placements or []
        records=report.get('directions_by_box',[]);prefix=[]
        operations=('approach_pick','pick','lift','transfer','place','retreat')
        stages=report.get('verified_prefix_stages',[])
        for p,record in zip(ordered,records):
            if record.get('box_id')!=p.box.id or record.get('pallet')!=p.pallet_index+1:break
            actual=[s.get('operation') for s in stages if s.get('box_id')==p.box.id and s.get('pallet')==p.pallet_index+1]
            if tuple(actual)!=operations:break
            prefix.append(p)
        if not prefix:return None,{}
        # Exact positive-cache verification retains geometry/stability checks.
        try:confirmed,audit,motion=_validated_sequence(prefix,self.pallet,self.config,self.approach,self.robot_verifier,self.cancelled)
        except RobotPlanningIncomplete:return None,{}
        return confirmed,audit


class RobotTwoPhasePacker(PaperTwoPhasePacker):
    def __init__(self,pallet,config=None,approach=None,robot_verifier=None,*,seal_verified_pallets=False):
        super().__init__(pallet,config);self.input_approach=approach or ApproachConfig();self.approach=self.input_approach.calculation_config()
        from .robot_execution_constraints import RobotExecutionConstraintSet
        self.constraints=RobotExecutionConstraintSet(pallet,self.config)
        self.robot_diagnostics={};self.evaluations=0;self.rejected=0
        self.robot_verifier=robot_verifier;self.robot_rejected=0
        self.motion_pending_candidates=0;self._pending_evaluation_reports=[]
        self.constraints.tool_config=getattr(robot_verifier,'config',None)
        if robot_verifier is not None and all(hasattr(robot_verifier,key) for key in ('scale','grasp_rotation','tcp_offset','base_pallet')):
            from .robot_grasp import verifier_grasp_config
            self.constraints.tool_config=verifier_grasp_config(robot_verifier)
        self.constraints.tool_outside_side=self.approach.outside_side
        self.seal_verified_pallets=seal_verified_pallets;self._sealed_pallet_indices=set()

    def _make_layer_builder(self,cancelled=None,log=None):
        return RobotLayerBuilder(self.pallet,self.config,cancelled=cancelled,log=log,approach=self.approach,robot_verifier=self.robot_verifier,owner=self)

    def _optimize_types(self,groups,evaluation,cancelled=None,log=None):
        pending=[]
        if not getattr(self.robot_verifier,'tiered_validation',False):
            self._pending_evaluation_reports=[]
            result=super()._optimize_types(groups,evaluation,cancelled,log)
            if result.best is None and self._pending_evaluation_reports:raise self._pending_summary(self._pending_evaluation_reports)
            return result
        from .paper_ga import optimize_types
        batch=self.robot_verifier.config.get('full_validation_batch_size',3)
        def validate(evaluated):
            try:
                ordered,audit,motion=_validated_sequence(evaluated.payload.placements,self.pallet,self.config,
                    self.approach,self.robot_verifier,cancelled)
            except RobotPlanningIncomplete as problem:
                pending.append(problem);self.motion_pending_candidates+=1
                if log:log(f'当前候选路径待验证（非垛型不可行），继续尝试备用候选。{problem}')
                return replace(evaluated,validation_status='motion_pending')
            if ordered is None:
                self.robot_rejected+=1
                return TypeEvaluation(False,float('inf'),-1,None)
            return replace(evaluated,payload=replace(evaluated.payload,placements=ordered),validation_status='verified')
        result=optimize_types(groups,evaluation,self.config,cancelled=cancelled,log=log,
                              validate_candidate=validate,validation_batch_size=batch)
        if result.best is None and pending:raise self._pending_summary(pending)
        return result

    def _pending_summary(self,problems):
        best=max(problems,key=lambda p:(p.motion_report or {}).get('verified_prefix_boxes',0))
        saver=getattr(self.robot_verifier,'save_pending_report',None)
        if saver and best.motion_report is not None:saver(best.motion_report)
        return RobotPlanningIncomplete(f'已尝试 {len(problems)} 个路径未完成候选，备用候选已用尽，尚未得到完整可执行方案；保留已验证检查点。最近诊断：{best}',
            motion_report=best.motion_report,placements=best.placements,audit=best.audit)

    def evaluate_sequence(self,groups,sequence,initial,pallet_count,cancelled=None):
        evaluated=super().evaluate_sequence(groups,sequence,initial,pallet_count,cancelled)
        if not evaluated.feasible:return evaluated
        self.evaluations+=1
        fixed={p.pallet_index for p in initial}
        generated=[p for p in evaluated.payload.placements if p.pallet_index not in fixed]
        retained=[p for p in evaluated.payload.placements if p.pallet_index in fixed]
        evaluated=replace(evaluated,payload=replace(evaluated.payload,placements=retained+anchor_inside_out(generated,self.pallet,self.approach.outside_side)))
        checker=self.robot_verifier
        if getattr(checker,'tiered_validation',False):checker=SimpleNamespace(verify=checker.screen)
        try:ordered,audit,motion=_validated_sequence(evaluated.payload.placements,self.pallet,self.config,self.approach,checker,cancelled)
        except RobotPlanningIncomplete as problem:
            self._pending_evaluation_reports.append(problem);self.motion_pending_candidates+=1
            return replace(evaluated,feasible=False,heterogeneity=float('inf'),compactness=-1,validation_status='motion_pending')
        if ordered is None:
            if motion is not None:self.robot_rejected+=1
            else:self.rejected+=1
            return TypeEvaluation(False,float('inf'),-1,None)
        if getattr(self.constraints,'tool_config',None):
            initial_ids={p.box.id for p in initial}
            changed={p.pallet_index for p in ordered if p.box.id not in initial_ids}
            preceding={}
            for p in ordered:
                previous=preceding.setdefault(p.pallet_index,[])
                if p.pallet_index in changed and not self.constraints.validate(p,previous,check_pattern=False).feasible:
                    self.rejected+=1
                    return TypeEvaluation(False,float('inf'),-1,None)
                previous.append(p)
        payload=replace(evaluated.payload,placements=ordered)
        return TypeEvaluation(True,evaluated.heterogeneity,evaluated.compactness,payload)

    def pack(self,boxes,*,progress=None,cancelled=None,log=None):
        from .pallet_coordinates import PUBLIC_FRAME,public_log_text
        if log is not None and self.input_approach.coordinate_frame==PUBLIC_FRAME:
            external_log=log
            log=lambda message:external_log(public_log_text(message))
        self.evaluations=self.rejected=self.robot_rejected=0
        self.motion_pending_candidates=0;self._pending_evaluation_reports=[]
        self.constraints.cancelled=cancelled
        self._sealed_pallet_indices=set()
        setter=getattr(self.robot_verifier,'set_log_callback',None)
        if setter:setter(log)
        if log:
            log(f'Ananno2025允许来向{"、".join(self.approach.open_directions)}；'+
                ('已启用'+getattr(self.robot_verifier,'config',{}).get('robot_name','EC66')+'离线IK、碰撞与路径验证。' if self.robot_verifier is not None else '轻量开放侧模型，未启用机械臂IK/关节轨迹验证。'))
        if log and getattr(self.robot_verifier,'tiered_validation',False):
            log('分层验证：第一阶段保留块完整检查；GA先做几何与端点快速筛选，候选按排名分批进行完整抓放路径验证。')
        result=super().pack(boxes,progress=progress,cancelled=cancelled,log=log)
        ordered,audit,motion_audit=_validated_sequence(result.placements,self.pallet,self.config,self.approach,self.robot_verifier,cancelled)
        if ordered is None:raise NoPaperSolution('2025最终序列验证失败：'+audit['reason'])
        if audit['sequencing_policy'].get('fallback_used') and log:
            log('先里后外优先顺序未通过约束，已采用重新验证通过的备用顺序：'+str(audit['sequencing_policy']['fallback_reason']))
        if motion_audit is not None:
            actual_directions={(c['pallet'],c['box_id']):c['open_direction'] for c in motion_audit.get('directions_by_box',[])}
            for check in audit['checks']:
                key=(check['pallet'],check['box_id'])
                if key in actual_directions:check['open_direction']=actual_directions[key]
        self.robot_diagnostics={**audit,'sealed_verified_pallets':self.seal_verified_pallets,'model':('elevated_preplacement_candidates' if self.approach.direction_policy=='preplace_optimized' else 'fixed_open_direction_rigid_box_sweep' if len(self.approach.open_directions)==1 else 'multiple_open_sides_rigid_box_sweep'),
            'evaluations_inside_ga':self.evaluations,'rejected_inside_ga':self.rejected,
            'ik_verified':False,'joint_trajectory_verified':False,'robotstudio_verified':False,
            'assumptions':[('Elevated preplacement directions are candidates only; robot trajectory validation required' if self.approach.direction_policy=='preplace_optimized' else 'One allowed axis-aligned straight final approach per box; box AABB only; gripper/arm not modeled'),
                'All contacting lower boxes are conservative support prerequisites',
                'Verified Phase1 prefixes are sealed; only deferred tails enter residual optimization',
                'Each pallet is independently presented at the same workcell; inter-pallet obstacles not modeled',
                'Dependency traversal implements paper-inspired sequencing, not claimed exact Algorithm1/2 source equivalence']}
        if motion_audit is not None:
            self.robot_diagnostics['direction_choice_status']='robot_trajectory_verified'
            robot_id=motion_audit.get('robot_id','ec66')
            self.robot_diagnostics.update(model=robot_id+'_mesh_ik_rrt_connect',robot_id=robot_id,
                robot_name=motion_audit.get('robot_name','EC66'),tool_status=motion_audit.get('tool_status'),ik_verified=True,
                joint_trajectory_verified=True,robot_rejected_inside_ga=self.robot_rejected,
                motion_verification=motion_audit,
                validation_strategy='screen_then_ranked_full_motion' if getattr(self.robot_verifier,'tiered_validation',False) else 'full_motion_every_candidate')
            self.robot_diagnostics['assumptions']=motion_audit['assumptions']
        self.robot_diagnostics['motion_pending_candidates']=self.motion_pending_candidates
        return replace(result,placements=ordered)


def annotate_robot_document(document,packer):
    annotate_document(document,packer.diagnostics)
    document['algorithm']='Ananno 2025 allowed-open-sides research implementation'
    document['reproduction_status']='lightweight_approach_model_integrated_robot_validation_pending'
    if packer.robot_verifier is not None:
        name=getattr(packer.robot_verifier,'config',{}).get('robot_name','EC66')
        document['algorithm']='Ananno2025 research extension with offline '+name+' IK/collision/RRT-Connect'
        document['reproduction_status']='robot_offline_model_extension_not_hardware_verified'
    document['robot_diagnostics']=packer.robot_diagnostics
    root=Path(__file__).resolve().parents[2]
    manifest=root/'provenance/baseline_2024_manifest.json'
    baseline=json.loads(manifest.read_text(encoding='utf-8'))
    document['provenance']={'baseline':baseline['baseline'],'source_project':baseline['source_project'],
        'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'snapshot_sha256':baseline['snapshot_sha256'],'paper_2025_doi':'10.1016/j.ifacol.2025.09.338'}
    return document
