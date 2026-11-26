"""Selectable robot descriptions and shared virtual-tool geometry."""
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np

FANUC='fanuc_r2000ic210l'


def resource_reference(resource,directory):
    resource=Path(resource).resolve();directory=Path(directory).resolve()
    try:return os.path.relpath(resource,directory).replace('\\','/')
    except ValueError:return resource.as_posix()  # Windows resources on another drive.


def identify_robot(urdf):
    name=ET.parse(urdf).getroot().get('name','').lower()
    if 'r2000ic210l' in name:return FANUC
    if 'ec66' in name:return 'ec66'
    raise ValueError('URDF不属于当前支持的EC66或R-2000iC/210L型号')


def profiles():
    return {'ec66':'EC66 · 实验室机械臂',FANUC:'FANUC R-2000iC/210L · 现场机械臂'}


def profile_config(root,robot_id):
    root=Path(root)
    if robot_id=='ec66':
        import json
        cfg=json.loads((root/'examples/ec66_scene_demo.json').read_text(encoding='utf-8'))
        for key in ('urdf','srdf'):cfg[key]=str((root/'examples'/cfg[key]).resolve())
        cfg.update(robot_id='ec66',robot_name='EC66',tip_link='cup_link',touch_links=['cup_link','link_base'],
                   tool_status='provided_lab_model_not_site_calibrated')
        return cfg
    if robot_id!=FANUC:raise ValueError('未知机械臂型号')
    base=root/'robot_models/fanuc_r2000ic_support/urdf/r2000ic210l'
    rotation=np.eye(4);rotation[:3,:3]=np.diag([1.,-1.,-1.])
    return {'robot_id':FANUC,'robot_name':'FANUC R-2000iC/210L',
        'urdf':str(base.with_suffix('.urdf').resolve()),'srdf':str(base.with_suffix('.srdf').resolve()),
        'tip_link':'packing_tcp','touch_links':['packing_tool','packing_tcp'],
        'tool_definition':{'kind':'box_envelope','parent_link':'tool0','size_m':[.6,.8,.25],
            'footprint_source':'user_provided_600x800mm','height_source':'provisional_250mm'},
        'tool_status':'footprint_provided_height_provisional',
        'initial_joints_rad':[math.pi/2,0,0,0,-math.pi/2,0],
        'length_scale_to_m':.001,'box_T_tcp_rotation':rotation.tolist(),'tcp_offset_from_box_top_m':[0.,0.,0.],
        'approach_distance_m':.08,'path_budget_seconds':3.,'box_budget_seconds':30.,'tiered_validation':True,'full_validation_batch_size':3,
        'calibration_status':'virtual_workcell_unmeasured','pallet_thickness_m':.04}


def resolve_mesh_path(urdf,uri):
    package=Path(urdf).resolve().parent.parent
    if uri.startswith('package://'):
        name,separator,relative=uri[len('package://'):].partition('/')
        if not separator or name!=package.name:raise ValueError('Mesh package does not match selected robot')
        path=(package/relative).resolve()
    else:path=(package/uri).resolve()
    if package not in path.parents:raise ValueError('Mesh path outside robot package')
    return path


def add_virtual_tool(root,definition):
    if definition is None:return root
    if definition.get('kind')!='box_envelope':raise ValueError('Unsupported virtual tool geometry')
    size=np.asarray(definition['size_m'],dtype=float)
    if size.shape!=(3,) or not np.isfinite(size).all() or np.any(size<=0):raise ValueError('工具尺寸必须为有限正数')
    parent=definition.get('parent_link','tool0');links={n.get('name') for n in root.findall('link')}
    if parent not in links or 'packing_tool' in links or 'packing_tcp' in links:raise ValueError('工具父坐标不存在或与模型重名')
    tool=ET.SubElement(root,'link',{'name':'packing_tool'})
    for tag in ('visual','collision'):
        part=ET.SubElement(tool,tag);geometry=ET.SubElement(part,'geometry')
        ET.SubElement(geometry,'box',{'size':' '.join(map(str,size))})
    joint=ET.SubElement(root,'joint',{'name':'packing_tool_mount','type':'fixed'})
    ET.SubElement(joint,'parent',{'link':parent});ET.SubElement(joint,'child',{'link':'packing_tool'})
    ET.SubElement(joint,'origin',{'xyz':f'0 0 {size[2]/2}','rpy':'0 0 0'})
    ET.SubElement(root,'link',{'name':'packing_tcp'})
    joint=ET.SubElement(root,'joint',{'name':'packing_tcp_mount','type':'fixed'})
    ET.SubElement(joint,'parent',{'link':parent});ET.SubElement(joint,'child',{'link':'packing_tcp'})
    ET.SubElement(joint,'origin',{'xyz':f'0 0 {size[2]}','rpy':'0 0 0'})
    return root
