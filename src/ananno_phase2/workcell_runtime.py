"""Resolve and snapshot a scene before starting a background packing run."""
import hashlib
import json
import os
from pathlib import Path
from .robot_runtime import prepare_robot_runtime
from .robot_profiles import resource_reference


def create_scene_verifier(project_dir,scene_path,pallet,output_dir,expected_sha256=None):
    prepare_robot_runtime(project_dir,preload=True)
    import numpy as np
    from .robot_offline import OfflineRobotVerifier
    source=Path(scene_path).resolve();raw=source.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if expected_sha256 and digest!=expected_sha256:raise ValueError('工位配置已更改，请重新开始计算。')
    config=json.loads(raw.decode('utf-8-sig'))
    normalized=pallet.with_long_side_x();scale=float(config['length_scale_to_m'])
    if 'pallet_dimensions_m' in config and not np.allclose(config['pallet_dimensions_m'],
            np.array([normalized.length,normalized.width,normalized.max_height])*scale,rtol=0,atol=1e-8):
        raise ValueError('工位中的托盘尺寸与本次装箱不一致，请打开“工位布局”更新并应用。')
    directory=Path(output_dir).resolve();directory.mkdir(parents=True,exist_ok=True)
    for key in ('urdf','srdf'):config[key]=resource_reference((source.parent/config[key]).resolve(),directory)
    snapshot=directory/'robot_scene_snapshot.json';serialized=json.dumps(config,ensure_ascii=False,indent=2)
    if snapshot.exists() and snapshot.read_text(encoding='utf-8')!=serialized:
        snapshot=directory/f'robot_scene_snapshot_{digest[:12]}.json'
    snapshot.write_text(serialized,encoding='utf-8')
    verifier=OfflineRobotVerifier(snapshot);verifier.configure_pallet_axes(pallet)
    return verifier,snapshot,digest
