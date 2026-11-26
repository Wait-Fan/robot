"""Local elevated preplacement geometry; no mandatory high pallet waypoint."""
import math
import numpy as np


def motion_options(config):
    values={key:float(config.get(key,default)) for key,default in (
        ('pick_lift_m',.08),('preplace_height_m',.15),('preplace_side_offset_m',.10))}
    if any(not math.isfinite(v) or v<=0 for v in values.values()):raise ValueError('抬升及预放置距离必须为有限正数')
    return values


def preplace_pose(target,base_pallet,direction,options):
    offset=np.array([0.,0.,options['preplace_height_m']])
    if direction!='+Z':
        axis='XY'.index(direction[1]);offset[axis]=options['preplace_side_offset_m']*(1 if direction[0]=='+' else -1)
    pose=np.asarray(target,dtype=float).copy();pose[:3,3]+=np.asarray(base_pallet)[:3,:3]@offset
    return pose
