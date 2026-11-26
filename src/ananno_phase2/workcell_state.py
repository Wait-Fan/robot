"""Editable virtual workcell. Geometry is in metres and radians."""
import copy
import json
import math
import os
import shutil
from datetime import datetime
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from .robot_profiles import profile_config,profiles,add_virtual_tool,identify_robot,resource_reference


def rotation_z(angle):
    co,si=math.cos(angle),math.sin(angle)
    return np.array([[co,-si,0],[si,co,0],[0,0,1.]])


def transform(xyz=(0,0,0),yaw=0):
    result=np.eye(4);result[:3,:3]=rotation_z(yaw);result[:3,3]=xyz
    return result


class WorkcellState:
    @classmethod
    def create(cls,project_dir,dimensions_mm=(1200,800,1400),sample_mm=(300,200,200)):
        self=cls();self.root=Path(project_dir).resolve()
        self.dimensions=np.array(dimensions_mm,dtype=float)*.001
        self.sample=np.array(sample_mm,dtype=float)*.001
        self.dimensions[:2]=sorted(self.dimensions[:2],reverse=True)
        self.config=profile_config(self.root,'ec66')
        self.q=np.array(self.config['initial_joints_rad'],dtype=float)
        self.pallet_pose=transform((-self.dimensions[0]/2,.35,0))
        self.pick_pose=transform((.45,-.40,.05))
        self.table_size=np.array([.65,.50,.75]);self.include_table=True
        self.obstacles=[];self.config['approach_distance_m']=.08
        self.config['pallet_thickness_m']=.04
        self.validate();return self

    def select_robot(self,robot_id):
        cfg=profile_config(self.root,robot_id)
        model_keys=('robot_id','robot_name','urdf','srdf','tip_link','touch_links','tool_definition','tool_status',
                    'box_T_tcp_rotation','tcp_offset_from_box_top_m','initial_joints_rad')
        updated=copy.deepcopy(self.config)
        for key in model_keys:
            updated.pop(key,None)
            if key in cfg:updated[key]=copy.deepcopy(cfg[key])
        self.config=updated;self.q=np.array(cfg['initial_joints_rad'],dtype=float);self.validate()

    @classmethod
    def load(cls,project_dir,path):
        path=Path(path).resolve();cfg=json.loads(path.read_text(encoding='utf-8-sig'))
        dimensions=np.asarray(cfg.get('pallet_dimensions_m',[1.2,.8,1.4]))*1000
        sample=np.asarray(cfg.get('workcell_editor',{}).get('sample_box_m',[.3,.2,.2]))*1000
        self=cls.create(project_dir,dimensions,sample)
        self.config=copy.deepcopy(cfg)
        for key in ('urdf','srdf'):self.config[key]=str((path.parent/cfg[key]).resolve())
        self.config.setdefault('robot_id',identify_robot(self.config['urdf']))
        if cfg.get('pallet_frame_convention','input_length_width')!='long_side_x':
            raise ValueError('请使用长边X坐标的工位配置；旧场景可在命令行继续使用。')
        self.pallet_pose=np.asarray(cfg['base_T_pallet'],dtype=float)
        self.q=np.asarray(cfg['initial_joints_rad'],dtype=float)
        if cfg.get('pick_surface'):
            self.pick_pose=np.asarray(cfg['pick_surface']['pose'],dtype=float)
        else:
            box_tcp=np.asarray(cfg['box_T_tcp_rotation'],dtype=float).copy()
            box_tcp[:3,3]=[0,0,self.sample[2]/2]+np.asarray(cfg['tcp_offset_from_box_top_m'])
            center=np.asarray(cfg['pick_tcp_pose'])@np.linalg.inv(box_tcp)
            self.pick_pose=center.copy();self.pick_pose[:3,3]-=center[:3,2]*self.sample[2]/2
        self.obstacles=copy.deepcopy(cfg.get('fixed_obstacles',[]));self.include_table=False
        for item in list(self.obstacles):
            if item['id']=='pickup_table':
                self.table_size=np.asarray(item['size'],dtype=float);self.include_table=True;self.obstacles.remove(item)
        self.validate();return self

    def validate(self):
        from .ec66_model import pose_matrix
        from .robot_validation_settings import planning_options
        from .robot_motion import motion_options
        planning_options(self.config)
        motion_options(self.config)
        if self.config.get('grasp_alignment','center') not in ('center','occupied_edges'):raise ValueError('未知吸盘对齐方式')
        if not math.isclose(float(self.config.get('length_scale_to_m',0)),.001,rel_tol=0,abs_tol=1e-12):
            raise ValueError('可视化工位按毫米编辑，length_scale_to_m必须为0.001')
        for vector in (self.dimensions,self.sample,self.table_size):
            if vector.shape!=(3,) or not np.isfinite(vector).all() or np.any(vector<=0):raise ValueError('尺寸必须为有限正数')
        pose_matrix(self.pallet_pose);pose_matrix(self.pick_pose)
        if self.q.shape!=(6,) or not np.isfinite(self.q).all():raise ValueError('需要六个有限的关节角')
        root=ET.parse(self.config['urdf']).getroot();add_virtual_tool(root,self.config.get('tool_definition'))
        links={n.get('name') for n in root.findall('link')}
        if self.config.get('robot_id','ec66') not in profiles():raise ValueError('未知机械臂型号')
        if self.config.get('robot_id','ec66')!=identify_robot(self.config['urdf']):raise ValueError('机械臂型号与URDF模型不一致')
        if self.config.get('tip_link','cup_link') not in links:raise ValueError('所选机械臂缺少配置的TCP坐标')
        joints=[j for j in root.findall('joint') if j.get('type')=='revolute']
        if len(joints)!=6 or any(q<float(j.find('limit').get('lower')) or q>float(j.find('limit').get('upper')) for q,j in zip(self.q,joints)):
            raise ValueError('初始关节角超出机械臂限位')
        pose_matrix(self.config['box_T_tcp_rotation'])
        offset=np.asarray(self.config['tcp_offset_from_box_top_m'],dtype=float)
        if offset.shape!=(3,) or not np.isfinite(offset).all():raise ValueError('TCP偏置必须是有限三维坐标')
        distance=float(self.config.get('approach_distance_m',.08))
        if not math.isfinite(distance) or distance<=0:raise ValueError('接近距离必须为有限正数')
        ids=set()
        for item in self.obstacles:
            if not isinstance(item['id'],str) or not item['id'] or item['id'] in ids or item['id'] in ('pallet','pickup','robot','pickup_table'):
                raise ValueError('障碍物标识无效、重复或使用保留名称')
            ids.add(item['id'])
            size=np.asarray(item['size'],dtype=float)
            if size.shape!=(3,) or not np.isfinite(size).all() or np.any(size<=0):raise ValueError('障碍物尺寸无效')
            pose_matrix(item['pose'])

    def entities(self):
        return [('robot',self.config.get('robot_name','EC66')+' · 基座原点'),('pallet','托盘 · 装箱底面角点'),('pickup','取箱台 · 台面中心')]+[
            (o['id'],'障碍物 · '+o['id']) for o in self.obstacles]

    def pose(self,key):
        if key=='robot':return np.eye(4)
        if key=='pallet':return self.pallet_pose.copy()
        if key=='pickup':return self.pick_pose.copy()
        return np.asarray(next(o for o in self.obstacles if o['id']==key)['pose'],dtype=float)

    def _set_pose(self,key,pose):
        if key=='robot':return
        if key=='pallet':self.pallet_pose=pose
        elif key=='pickup':self.pick_pose=pose
        else:next(o for o in self.obstacles if o['id']==key)['pose']=pose.tolist()

    def set_position(self,key,xyz):
        xyz=np.asarray(xyz,dtype=float)
        if xyz.shape!=(3,) or not np.isfinite(xyz).all():raise ValueError('位置必须为有限三维坐标')
        pose=self.pose(key);pose[:3,3]=xyz;self._set_pose(key,pose)

    def set_yaw(self,key,angle):
        if not math.isfinite(angle):raise ValueError('旋转角无效')
        pose=self.pose(key);old=math.atan2(pose[1,0],pose[0,0])
        pose[:3,:3]=rotation_z(angle-old)@pose[:3,:3];self._set_pose(key,pose)

    def add_obstacle(self):
        index=1
        while any(o['id']==f'obstacle_{index}' for o in self.obstacles):index+=1
        key=f'obstacle_{index}';self.obstacles.append({'id':key,'size':[.3,.3,.5],'pose':transform((-.5,-.3,.25)).tolist()})
        return key

    def fixed_obstacles(self):
        result=copy.deepcopy(self.obstacles)
        if self.include_table:
            offset=transform((0,0,-self.table_size[2]/2))
            result.append({'id':'pickup_table','size':self.table_size.tolist(),'pose':(self.pick_pose@offset).tolist()})
        return result

    def source_box_pose(self):
        return self.pick_pose@transform((0,0,self.sample[2]/2))

    def scene(self):
        self.validate();cfg=copy.deepcopy(self.config)
        cfg.update(base_T_pallet=self.pallet_pose.tolist(),pallet_frame_convention='long_side_x',
            pallet_dimensions_m=self.dimensions.tolist(),initial_joints_rad=self.q.tolist(),
            calibration_status='virtual_workcell_unmeasured',pick_surface={'pose':self.pick_pose.tolist()},
            fixed_obstacles=self.fixed_obstacles(),workcell_editor={'version':1,'sample_box_m':self.sample.tolist()})
        local_tcp=np.asarray(cfg['box_T_tcp_rotation'],dtype=float).copy()
        local_tcp[:3,3]=np.asarray([0,0,self.sample[2]/2])+cfg['tcp_offset_from_box_top_m']
        cfg['pick_tcp_pose']=(self.source_box_pose()@local_tcp).tolist()
        return cfg

    def save(self,path):
        path=Path(path).resolve();cfg=self.scene()
        for key in ('urdf','srdf'):cfg[key]=resource_reference(cfg[key],path.parent)
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+'.tmp')
        serialized=json.dumps(cfg,ensure_ascii=False,indent=2)
        if path.exists() and path.read_text(encoding='utf-8-sig')!=serialized:
            backup=self.root/('backup_before_workcell_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            backup.mkdir(parents=True,exist_ok=False);shutil.copy2(path,backup/path.name)
        temporary.write_text(serialized,encoding='utf-8');temporary.replace(path)
        return path
