"""Headless EC66 kinematics and convex-mesh collision queries. SI units only."""
from pathlib import Path
import math
import tempfile
import time
import xml.etree.ElementTree as ET
import numpy as np

try:
    import mujoco as mj
except ImportError as exc:
    raise RuntimeError('Offline robot verification needs mujoco==3.3.7 and numpy; see requirements-robot.txt') from exc

def pose_matrix(value):
    matrix=np.asarray(value,dtype=float)
    if matrix.shape!=(4,4) or not np.all(np.isfinite(matrix)):
        raise ValueError('Pose must be a finite 4x4 matrix')
    if not np.allclose(matrix[3],[0,0,0,1],atol=1e-8) or not np.allclose(matrix[:3,:3].T@matrix[:3,:3],np.eye(3),atol=1e-5) or np.linalg.det(matrix[:3,:3])<.999:
        raise ValueError('Pose must be a rigid transform')
    return matrix

def _quat(rotation):
    out=np.empty(4);mj.mju_mat2Quat(out,np.asarray(rotation,dtype=float).reshape(9));return out

def _rotvec(rotation):
    q=_quat(rotation)
    if q[0]<0:q=-q
    norm=np.linalg.norm(q[1:])
    return 2*q[1:] if norm<1e-9 else q[1:]/norm*(2*math.atan2(norm,q[0]))

class EC66Model:
    def __init__(self,urdf,srdf=None,*,tip='cup_link'):
        self.urdf=Path(urdf);self.srdf=Path(srdf) if srdf is not None else None;tree=ET.parse(self.urdf);root=tree.getroot()
        self.link_names={link.get('name') for link in root.findall('link')}
        if tip not in self.link_names:raise ValueError('TCP must name a URDF link, not a joint')
        self.tip=tip
        joints=[j for j in root.findall('joint') if j.get('type')=='revolute']
        self.names=[j.get('name') for j in joints]
        self.lower=np.array([float(j.find('limit').get('lower')) for j in joints])
        self.upper=np.array([float(j.find('limit').get('upper')) for j in joints])
        self.velocity=np.array([float(j.find('limit').get('velocity')) for j in joints])
        self.disabled=set()
        if srdf is not None:
            for entry in ET.parse(srdf).getroot().findall('disable_collisions'):
                self.disabled.add(frozenset([entry.get('link1'),entry.get('link2')]))
        assets={}
        package=self.urdf.parent.parent
        for mesh in root.findall('.//mesh'):
            uri=mesh.get('filename');relative=uri.split('package://robot_ec66/')[-1]
            path=(package/relative).resolve()
            if package.resolve() not in path.parents:raise ValueError('Mesh path outside robot package')
            key=path.name;data=path.read_bytes()
            if key in assets and assets[key]!=data:raise ValueError('Ambiguous mesh filenames')
            assets[key]=data;mesh.set('filename',key)
        compiler=ET.SubElement(ET.SubElement(root,'mujoco'),'compiler')
        compiler.set('fusestatic','false');compiler.set('discardvisual','true')
        model=mj.MjModel.from_xml_string(ET.tostring(root,encoding='unicode'),assets=assets)
        with tempfile.TemporaryDirectory(prefix='ec66_model_') as folder:
            path=Path(folder)/'model.xml';mj.mj_saveLastXML(str(path),model)
            self.template=path.read_text(encoding='utf-8')
        self.assets=assets;self.attachment=None;self.obstacles=[]
        self.set_obstacles([])

    def set_obstacles(self,obstacles):
        tree=ET.fromstring(self.template);world=tree.find('worldbody')
        for i,item in enumerate(obstacles):
            size=np.asarray(item['size'],dtype=float);pose=pose_matrix(item['pose'])
            if size.shape!=(3,) or not np.all(np.isfinite(size)) or np.any(size<=0):raise ValueError('Invalid obstacle size')
            ET.SubElement(world,'geom',{'name':f'world_{i}','type':'box','size':' '.join(map(str,size/2)),
                'pos':' '.join(map(str,pose[:3,3])),'quat':' '.join(map(str,_quat(pose[:3,:3]))),'contype':'0','conaffinity':'0'})
        held=ET.SubElement(world,'body',{'name':'carried_box_body','mocap':'true'})
        ET.SubElement(held,'geom',{'name':'carried_box','type':'box','size':'.001 .001 .001','contype':'0','conaffinity':'0'})
        self.model=mj.MjModel.from_xml_string(ET.tostring(tree,encoding='unicode'),assets=self.assets)
        self.data=mj.MjData(self.model)
        self.tip_id=mj.mj_name2id(self.model,mj.mjtObj.mjOBJ_BODY,self.tip)
        if self.tip_id<0:raise ValueError('TCP body was lost while importing URDF')
        self.qaddr=[int(self.model.jnt_qposadr[mj.mj_name2id(self.model,mj.mjtObj.mjOBJ_JOINT,n)]) for n in self.names]
        self.daddr=[int(self.model.jnt_dofadr[mj.mj_name2id(self.model,mj.mjtObj.mjOBJ_JOINT,n)]) for n in self.names]
        self.robot_geoms=[i for i in range(self.model.ngeom) if mj.mj_id2name(self.model,mj.mjtObj.mjOBJ_BODY,int(self.model.geom_bodyid[i])) in self.link_names]
        self.world_geoms=[mj.mj_name2id(self.model,mj.mjtObj.mjOBJ_GEOM,f'world_{i}') for i in range(len(obstacles))]
        self.held_id=mj.mj_name2id(self.model,mj.mjtObj.mjOBJ_GEOM,'carried_box')
        held_body=mj.mj_name2id(self.model,mj.mjtObj.mjOBJ_BODY,'carried_box_body')
        self.held_mocap=int(self.model.body_mocapid[held_body])
        self.obstacles=list(obstacles)

    def _set(self,q):
        q=np.asarray(q,dtype=float)
        if q.shape!=(6,) or not np.all(np.isfinite(q)):raise ValueError('Expected six finite joint angles')
        self.data.qpos[self.qaddr]=q;mj.mj_kinematics(self.model,self.data);mj.mj_comPos(self.model,self.data)
        if self.attachment:
            size,offset=self.attachment
            transform=self.fk(q)@offset
            self.data.mocap_pos[self.held_mocap]=transform[:3,3]
            self.data.mocap_quat[self.held_mocap]=_quat(transform[:3,:3])
            self.model.geom_size[self.held_id]=np.asarray(size)/2
            mj.mj_kinematics(self.model,self.data)
        return q

    def fk(self,q):
        q=np.asarray(q,dtype=float)
        if q.shape!=(6,) or not np.all(np.isfinite(q)):raise ValueError('Expected six finite joint angles')
        self.data.qpos[self.qaddr]=q;mj.mj_kinematics(self.model,self.data);mj.mj_comPos(self.model,self.data)
        pose=np.eye(4);pose[:3,3]=self.data.xpos[self.tip_id];pose[:3,:3]=self.data.xmat[self.tip_id].reshape(3,3)
        return pose

    def collisions(self,q):
        q=self._set(q);pairs=[]
        for index,a in enumerate(self.robot_geoms):
            link_a=mj.mj_id2name(self.model,mj.mjtObj.mjOBJ_BODY,int(self.model.geom_bodyid[a]))
            for b in self.robot_geoms[index+1:]:
                link_b=mj.mj_id2name(self.model,mj.mjtObj.mjOBJ_BODY,int(self.model.geom_bodyid[b]))
                if link_a==link_b or frozenset([link_a,link_b]) in self.disabled:continue
                if mj.mj_geomDistance(self.model,self.data,a,b,.01,None)<-1e-5:pairs.append([link_a,link_b])
            for b,item in zip(self.world_geoms,self.obstacles):
                if link_a in item.get('allowed_touch_links',[]):continue
                if mj.mj_geomDistance(self.model,self.data,a,b,.01,None)<-1e-5:pairs.append([link_a,str(item.get('id',b))])
            if self.attachment and link_a not in {'cup_link','link_base'}:
                if mj.mj_geomDistance(self.model,self.data,a,self.held_id,.01,None)<-1e-5:pairs.append([link_a,'carried_box'])
        if self.attachment:
            for b,item in zip(self.world_geoms,self.obstacles):
                if self._box_overlap(self.held_id,b):pairs.append(['carried_box',str(item.get('id',b))])
        return pairs

    def _box_overlap(self,a,b):
        # Exact OBB separating-axis test avoids signed-distance degeneracy at flush box contact.
        ra=self.data.geom_xmat[a].reshape(3,3);rb=self.data.geom_xmat[b].reshape(3,3)
        delta=self.data.geom_xpos[b]-self.data.geom_xpos[a]
        axes=[ra[:,i] for i in range(3)]+[rb[:,i] for i in range(3)]
        axes += [np.cross(ra[:,i],rb[:,j]) for i in range(3) for j in range(3)]
        for axis in axes:
            norm=np.linalg.norm(axis)
            if norm<1e-10:continue
            axis=axis/norm
            radius_a=np.dot(np.abs(ra.T@axis),self.model.geom_size[a])
            radius_b=np.dot(np.abs(rb.T@axis),self.model.geom_size[b])
            if radius_a+radius_b-abs(np.dot(delta,axis))<=1e-5:return False
        return True

    def valid(self,q):
        q=np.asarray(q,dtype=float)
        if q.shape!=(6,) or not np.all(np.isfinite(q)) or np.any(q<self.lower) or np.any(q>self.upper):return False
        return not self.collisions(q)

    def ik(self,target,seed,*,check_collision=True,iterations=200,restarts=4,seconds=2.):
        target=pose_matrix(target);seed=np.asarray(seed,dtype=float)
        if seed.shape!=(6,) or not np.all(np.isfinite(seed)):raise ValueError('Invalid IK seed')
        rng=np.random.default_rng(1);deadline=time.monotonic()+seconds
        for attempt in range(restarts+1):
            q=np.clip(seed,self.lower,self.upper) if attempt==0 else rng.uniform(self.lower,self.upper)
            for _ in range(iterations):
                if time.monotonic()>deadline:return None
                current=self.fk(q);ep=target[:3,3]-current[:3,3];er=_rotvec(target[:3,:3]@current[:3,:3].T)
                if np.linalg.norm(ep)<1e-6 and np.linalg.norm(er)<5e-5:
                    if not check_collision or self.valid(q):return q
                    break
                jp=np.zeros((3,self.model.nv));jr=jp.copy()
                mj.mj_jacBody(self.model,self.data,jp,jr,self.tip_id)
                jac=np.vstack([jp[:,self.daddr],.3*jr[:,self.daddr]])
                error=np.concatenate([ep,.3*er])
                delta=np.linalg.solve(jac.T@jac+np.eye(6)*1e-4,jac.T@error)
                length=np.linalg.norm(delta)
                if length>.2:delta*=.2/length
                q=np.clip(q+delta,self.lower,self.upper)
        return None
