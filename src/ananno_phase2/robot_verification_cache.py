"""Reuse complete independent pallets; assemble reports in execution order."""
from collections import OrderedDict
import copy
import hashlib
import json
import time


def verify_pallets(verifier,placements,pallet,approach,*,cancelled=None):
    v=verifier;started=time.monotonic()
    def check():
        if cancelled is not None and cancelled():raise InterruptedError('Robot planning cancelled')
    check()
    if not hasattr(v,'pallet_cache'):v.pallet_cache=OrderedDict()
    context={'model':v.model_fingerprint,'config':v.config,'base_pallet':v.base_pallet,'pick':v.pick,
        'initial':v.initial,'obstacles':v.obstacles,'scale':v.scale,'distance':v.distance,'resolution':v.resolution,
        'path_seconds':v.path_seconds,'acceleration':v.acceleration,'grasp_rotation':v.grasp_rotation,
        'offset':v.tcp_offset,'pallet':[pallet.length,pallet.width,pallet.max_height],
        'sides':approach.open_directions,'policy':approach.direction_policy,'outside':approach.outside_side,
        'implementation':'whole_frontier_edge_grasp_prepose_c2_v2'}
    context_hash=hashlib.sha256(json.dumps(context,sort_keys=True,default=lambda x:x.tolist()).encode()).hexdigest()
    groups={}
    for p in sorted(placements,key=lambda p:(p.pallet_index,p.order)):groups.setdefault(p.pallet_index,[]).append(p)
    keys={index:hashlib.sha256((context_hash+repr(tuple((p.box.id,p.box.length,p.box.width,p.box.height,
        p.point.x,p.point.y,p.point.z,p.orientation.code,p.orientation.length,p.orientation.width,p.orientation.height)
        for p in items))).encode()).hexdigest() for index,items in groups.items()}
    # Pin hits before inserting other candidates, preventing sequential LRU thrashing.
    hits={index:copy.deepcopy(v.pallet_cache[key]) for index,key in keys.items() if key in v.pallet_cache}
    for index in hits:v.pallet_cache.move_to_end(keys[index])
    visit=[i for i in groups if i not in hits]+[i for i in groups if i in hits]
    reports={};reused=0;reused_boxes=0;callback=getattr(v,'log_callback',None)
    for index in visit:
        check();items=groups[index];key=keys[index]
        if index in hits:
            report=hits[index];reused+=1;reused_boxes+=len(items)
            if callback:callback(f'机器人验证：托盘 {index+1}，复用整盘 {len(items)} 箱完整轨迹；无需重新规划')
        else:
            if callback:callback(f'机器人验证：托盘 {index+1}，{len(items)} 箱需要检查；优先验证新增或变化托盘')
            report=v._verify_sequence(items,pallet,approach,cancelled=cancelled)
            reused_boxes+=report.get('reused_prefix_boxes',0)
            if not report['passed']:
                report.update(validation_pallet_order=[i+1 for i in visit],reused_pallets=reused,
                              reused_prefix_boxes=reused_boxes)
                return report
            v.pallet_cache[key]=copy.deepcopy(report);v.pallet_cache.move_to_end(key)
            while len(v.pallet_cache)>64:v.pallet_cache.popitem(last=False)
        for stage in report['stages']:stage['pallet']=index+1
        for direction in report.get('directions_by_box',[]):direction['pallet']=index+1
        reports[index]=report
    if not reports:return v._verify_sequence([],pallet,approach,cancelled=cancelled)
    check();ordered=[reports[i] for i in sorted(reports)];combined=copy.deepcopy(ordered[-1])
    combined.update(stages=[s for report in ordered for s in report['stages']],
        directions_by_box=[d for report in ordered for d in report.get('directions_by_box',[])],
        estimated_motion_seconds=sum(report['estimated_motion_seconds'] for report in ordered),
        wall_seconds=time.monotonic()-started,reused_pallets=reused,reused_prefix_boxes=reused_boxes,
        validation_pallet_order=[i+1 for i in visit])
    if callback:callback(f'机器人验证汇总：{len(groups)} 盘全部通过；复用整盘 {reused} 盘，复用已验证箱 {reused_boxes}/{len(placements)}')
    return combined
