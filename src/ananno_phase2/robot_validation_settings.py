"""Shared validation limits for scene loading, GUI and offline verification."""
import math


def planning_options(config):
    result={key:float(value) for key,value in {
        'path_budget_seconds':config.get('path_budget_seconds',2.),
        'box_budget_seconds':config.get('box_budget_seconds',config.get('sequence_budget_seconds',30.)),
        'screen_budget_seconds':config.get('screen_budget_seconds',1.),
    }.items()}
    if any(not math.isfinite(value) or value<=0 for value in result.values()):
        raise ValueError('机器人单段、单箱及快速筛选预算必须为有限正数')
    batch=config.get('full_validation_batch_size',3)
    if isinstance(batch,bool) or not isinstance(batch,int) or batch<1:
        raise ValueError('详细验证批次数必须为正整数')
    tiered=config.get('tiered_validation',True)
    if not isinstance(tiered,bool):raise ValueError('分层验证开关必须为布尔值')
    result.update(full_validation_batch_size=batch,tiered_validation=tiered)
    return result
