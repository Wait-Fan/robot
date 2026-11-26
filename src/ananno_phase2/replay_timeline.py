"""Validated per-pallet playback of saved rest-to-rest joint trajectories."""
from bisect import bisect_right
import copy
from dataclasses import dataclass
import math
import numpy as np

OPERATIONS=('approach_pick','pick','lift','transfer','place','retreat')


@dataclass(frozen=True)
class ReplayFrame:
    q: np.ndarray
    stage: dict
    completed_ids: tuple[str,...]
    carrying_id: str | None
    source_id: str | None
    elapsed: float
    finished: bool


class ReplayTimeline:
    def __init__(self,document,pallet_index):
        from .pallet_coordinates import INTERNAL_FRAME
        self.coordinate_frame=document.get('coordinate_system',{}).get('frame',INTERNAL_FRAME)
        try:
            audit=document.get('robot_diagnostics',{})
            motion=audit.get('motion_verification',{})
            if not (audit.get('ik_verified') and audit.get('joint_trajectory_verified') and motion.get('passed')):
                raise ValueError('当前结果没有已验证的机器人轨迹。请配置工位、勾选“机器人完整校验”后重新计算。')
            self.interpolation=motion.get('time_parameterization')
            if self.interpolation not in ('rest_to_rest_cubic','piecewise_quintic_c2'):
                raise ValueError('轨迹时间格式不支持，请用当前版本重新进行机器人完整校验。')
            self.pallet=copy.deepcopy(next(p for p in document['pallets'] if p['pallet_index']==pallet_index))
            self.items={str(p['id']):p for p in sorted(self.pallet['packed_items'],key=lambda p:p['sequence'])}
            if not self.items:raise ValueError('该托盘没有可回放箱体。')
            if self.interpolation=='piecewise_quintic_c2':
                from .ec66_model import pose_matrix
                records=[r for r in motion.get('directions_by_box',[]) if r.get('pallet')==pallet_index]
                if len(records)!=len(self.items) or {str(r.get('box_id')) for r in records}!=set(self.items):
                    raise ValueError('新轨迹缺少逐箱抓取位置记录，请重新计算。')
                for record in records:
                    try:pose_matrix(record['grasp']['box_T_tcp'])
                    except (KeyError,TypeError,ValueError) as exc:raise ValueError('逐箱抓取变换无效，请重新计算。') from exc
            self.joint_names=list(motion['joint_names'])
            if len(self.joint_names)!=6 or len(set(self.joint_names))!=6:raise ValueError('轨迹关节名称无效。')
            self.stages=copy.deepcopy([s for s in motion['stages'] if s['pallet']==pallet_index])
            expected=[(key,op) for key in self.items for op in OPERATIONS]
            if [(str(s['box_id']),s['operation']) for s in self.stages]!=expected:
                raise ValueError('该托盘轨迹缺少抓取/搬运/放置阶段，或与箱子顺序不一致。请重新计算。')
            self.starts=[];self.ends=[];self.samples=[];self.retreat_starts=[];self.box_starts=[];self.knots=[]
            elapsed=0.;previous=None
            for stage in self.stages:
                points=stage['trajectory']
                if len(points)<2:raise ValueError('轨迹段至少需要两个采样点。')
                times=np.array([p['time_from_start'] for p in points],dtype=float)
                joints=np.array([p['positions'] for p in points],dtype=float)
                if times.ndim!=1 or joints.shape!=(len(points),6) or not np.isfinite(times).all() or not np.isfinite(joints).all():
                    raise ValueError('轨迹包含无效的时间或关节数据。')
                if abs(times[0])>1e-9 or np.any(np.diff(times)<=0):raise ValueError('轨迹段时间必须从零严格递增。')
                for point in points:
                    velocity=np.asarray(point.get('velocities',[0.]*6),dtype=float)
                    if velocity.shape!=(6,) or not np.isfinite(velocity).all():raise ValueError('轨迹关节速度无效。')
                    if self.interpolation=='rest_to_rest_cubic' and np.max(np.abs(velocity))>1e-9:
                        raise ValueError('旧格式需要静止到静止三次插值轨迹。')
                    if self.interpolation=='piecewise_quintic_c2':
                        acceleration=np.asarray(point.get('accelerations'),dtype=float)
                        if acceleration.shape!=(6,) or not np.isfinite(acceleration).all():raise ValueError('轨迹关节加速度无效。')
                if self.interpolation=='piecewise_quintic_c2':
                    for endpoint in (points[0],points[-1]):
                        if np.max(np.abs(endpoint['velocities']))>1e-8 or np.max(np.abs(endpoint['accelerations']))>1e-8:
                            raise ValueError('操作边界必须平滑停止。')
                if previous is not None and not np.allclose(previous,joints[0],rtol=0,atol=1e-8):
                    raise ValueError('相邻轨迹段关节状态不连续。')
                carrying=stage['operation'] in ('lift','transfer','place')
                if bool(stage.get('carrying_box'))!=carrying:raise ValueError('轨迹携箱状态与操作阶段不一致。')
                self.starts.append(elapsed);elapsed+=float(times[-1]);self.ends.append(elapsed)
                self.samples.append((times,joints));self.knots.append(points);previous=joints[-1]
                if stage['operation']=='retreat':self.retreat_starts.append(self.starts[-1])
                if stage['operation']=='approach_pick':self.box_starts.append(self.starts[-1])
            if not math.isfinite(elapsed) or elapsed<=0:raise ValueError('轨迹总时间无效。')
            self.duration=elapsed
        except (KeyError,TypeError,StopIteration,IndexError,OverflowError) as exc:
            raise ValueError('机器人轨迹数据不完整，请启用机器人完整校验重新计算。') from exc

    def validate_joint_limits(self,lower,upper):
        for _,joints in self.samples:
            if np.any(joints<np.asarray(lower)-1e-9) or np.any(joints>np.asarray(upper)+1e-9):
                raise ValueError('已保存轨迹超出当前机械臂关节限位，请重新计算。')
        if self.interpolation=='piecewise_quintic_c2':
            from .joint_trajectory import _coefficients,_extrema
            for points in self.knots:
                for a,b in zip(points,points[1:]):
                    low,high=_extrema(_coefficients(a,b)[0],0)
                    if np.any(low<np.asarray(lower)-1e-9) or np.any(high>np.asarray(upper)+1e-9):
                        raise ValueError('平滑曲线超出当前机械臂关节限位，请重新计算。')

    def frame_at(self,seconds):
        seconds=float(seconds)
        if not math.isfinite(seconds):raise ValueError('回放时间必须为有限数字。')
        elapsed=max(0.,min(self.duration,seconds))
        index=min(len(self.stages)-1,bisect_right(self.ends,elapsed))
        stage=self.stages[index];times,joints=self.samples[index]
        local=max(0.,min(float(times[-1]),elapsed-self.starts[index]))
        segment=min(len(times)-2,max(0,int(np.searchsorted(times,local,side='right'))-1))
        fraction=(local-times[segment])/(times[segment+1]-times[segment])
        if self.interpolation=='piecewise_quintic_c2':
            from .joint_trajectory import evaluate_segment
            q=evaluate_segment(self.knots[index][segment],self.knots[index][segment+1],fraction)[0]
        else:
            blend=fraction*fraction*(3-2*fraction)
            q=joints[segment]+(joints[segment+1]-joints[segment])*blend
        key=str(stage['box_id']);operation=stage['operation']
        complete=tuple(self.items)[:bisect_right(self.retreat_starts,elapsed)]
        return ReplayFrame(q.copy(),stage,complete,key if stage['carrying_box'] else None,
                           key if operation in ('approach_pick','pick') else None,elapsed,elapsed>=self.duration)
