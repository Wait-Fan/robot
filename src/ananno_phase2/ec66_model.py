"""Headless EC66 kinematics and convex-mesh collision queries. SI units only."""
from pathlib import Path
import math
import tempfile
import time
import threading
import xml.etree.ElementTree as ET
import hashlib
from collections import OrderedDict
from .collision_acceleration import local_bounds,world_bounds,overlapping_pairs,box_overlap
import numpy as np
from .robot_profiles import resolve_mesh_path,add_virtual_tool

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

# MuJoCo keeps the last imported XML for mj_saveLastXML.
# Protect every import in this module until that template has been exported.
_XML_COMPILER_LOCK=threading.RLock()


class EC66Model:
    def __init__(self,urdf,srdf=None,*,tip='cup_link',tool_definition=None,touch_links=None):
        self.urdf=Path(urdf);self.srdf=Path(srdf) if srdf is not None else None;tree=ET.parse(self.urdf);root=tree.getroot()
        add_virtual_tool(root,tool_definition)
        self.link_names={link.get('name') for link in root.findall('link')}
        if tip not in self.link_names:raise ValueError('TCP must name a URDF link, not a joint')
        self.tip=tip
        self.touch_links=set(touch_links if touch_links is not None else ['cup_link','link_base'])
        if not self.touch_links.issubset(self.link_names):raise ValueError('Touch links not found in selected robot')
        joints=[j for j in root.findall('joint') if j.get('type')=='revolute']
        self.names=[j.get('name') for j in joints]
        self.lower=np.array([float(j.find('limit').get('lower')) for j in joints])
        self.upper=np.array([float(j.find('limit').get('upper')) for j in joints])
        self.velocity=np.array([float(j.find('limit').get('velocity')) for j in joints])
        self.disabled=set()
        if srdf is not None:
            for entry in ET.parse(srdf).getroot().findall('disable_collisions'):
                self.disabled.add(frozenset([entry.get('link1'),entry.get('link2')]))
        if tool_definition:
            # The box envelope is rigidly mounted to the final robot link.
            parent=tool_definition.get('parent_link','tool0')
            ancestry={j.find('child').get('link'):j for j in root.findall('joint')}
            while parent in ancestry and ancestry[parent].get('type')=='fixed':
                parent=ancestry[parent].find('parent').get('link')
            self.disabled.add(frozenset([parent,'packing_tool']))
        assets={}
        package=self.urdf.parent.parent
        for mesh in root.findall('.//mesh'):
            uri=mesh.get('filename');path=resolve_mesh_path(self.urdf,uri)
            key=hashlib.sha256(str(path.relative_to(package.resolve())).encode()).hexdigest()[:12]+'_'+path.name;data=path.read_bytes()
            if key in assets and assets[key]!=data:raise ValueError('Ambiguous mesh filenames')
            assets[key]=data;mesh.set('filename',key)
        compiler=ET.SubElement(ET.SubElement(root,'mujoco'),'compiler')
        compiler.set('fusestatic','false');compiler.set('discardvisual','true')
        with _XML_COMPILER_LOCK:
            model=mj.MjModel.from_xml_string(ET.tostring(root,encoding='unicode'),assets=assets)
            with tempfile.TemporaryDirectory(prefix='ec66_model_') as folder:
                path=Path(folder)/'model.xml';mj.mj_saveLastXML(str(path),model)
                self.template=path.read_text(encoding='utf-8')
        self.assets=assets;self.attachment=None;self.obstacles=[]
        self._ik_cache=OrderedDict();self.ik_cache_hits=0
        self.collision_stats={"queries":0,"broadphase_skipped":0,"narrowphase_checks":0}
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
        with _XML_COMPILER_LOCK:
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
        self._bound_centers,self._bound_halves=local_bounds(self.model,mj)
        labels={i:mj.mj_id2name(self.model,mj.mjtObj.mjOBJ_BODY,int(self.model.geom_bodyid[i])) for i in self.robot_geoms}
        pairs=[]
        def add(a,b,label,held=False,box_sat=False):
            boxes=box_sat and self.model.geom_type[a]==mj.mjtGeom.mjGEOM_BOX and self.model.geom_type[b]==mj.mjtGeom.mjGEOM_BOX
            pairs.append((a,b,label,held,boxes))
        for index,a in enumerate(self.robot_geoms):
            la=labels[a]
            for b in self.robot_geoms[index+1:]:
                lb=labels[b]
                if la!=lb and frozenset([la,lb]) not in self.disabled:add(a,b,[la,lb])
            for b,item in zip(self.world_geoms,self.obstacles):
                if la not in item.get('allowed_touch_links',[]):add(a,b,[la,str(item.get('id',b))],box_sat=True)
            if la not in self.touch_links:add(a,self.held_id,[la,'carried_box'],True)
        for b,item in zip(self.world_geoms,self.obstacles):add(self.held_id,b,['carried_box',str(item.get('id',b))],True,box_sat=True)
        self._collision_pairs=pairs
        self._pair_a=np.array([p[0] for p in pairs],dtype=int);self._pair_b=np.array([p[1] for p in pairs],dtype=int)
        self._pair_held=np.array([p[3] for p in pairs],dtype=bool)

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
        self._set(q)
        if self.attachment:self._bound_halves[self.held_id]=self.model.geom_size[self.held_id]+1e-7
        centers,halves=world_bounds(self._bound_centers,self._bound_halves,self.data.geom_xpos,self.data.geom_xmat)
        enabled=np.ones(len(self._collision_pairs),dtype=bool) if self.attachment else ~self._pair_held
        near=overlapping_pairs(centers,halves,self._pair_a,self._pair_b)&enabled
        self.collision_stats['queries']+=1
        self.collision_stats['broadphase_skipped']+=int(np.count_nonzero(enabled&~near))
        self.collision_stats['narrowphase_checks']+=int(np.count_nonzero(near))
        pairs=[]
        for index in np.flatnonzero(near):
            a,b,label,_,boxes=self._collision_pairs[index]
            overlap=self._box_overlap(a,b) if boxes else mj.mj_geomDistance(self.model,self.data,a,b,.01,None)<-1e-5
            if overlap:pairs.append(list(label))
        return pairs

    def _box_overlap(self,a,b):
        return box_overlap(self.data.geom_xpos[a],self.data.geom_xmat[a].reshape(3,3),self.model.geom_size[a],
                           self.data.geom_xpos[b],self.data.geom_xmat[b].reshape(3,3),self.model.geom_size[b])

    def valid(self,q):
        q=np.asarray(q,dtype=float)
        self.last_collision_pairs=[]
        if q.shape!=(6,) or not np.all(np.isfinite(q)) or np.any(q<self.lower) or np.any(q>self.upper):return False
        self.last_collision_pairs=self.collisions(q)
        return not self.last_collision_pairs

    def ik(self,target,seed,*,check_collision=True,iterations=200,restarts=4,seconds=2.,
           random_seed=1,exclude_solutions=(),cancelled=None):
        target=pose_matrix(target);seed=np.asarray(seed,dtype=float)
        if seed.shape!=(6,) or not np.all(np.isfinite(seed)):raise ValueError('Invalid IK seed')
        details={'status':'search_exhausted','converged_colliding':0,'excluded_branches':0,'collision_pairs':[],'random_seed':random_seed}
        self.last_ik_diagnostics=details
        excluded=[np.asarray(q,dtype=float) for q in exclude_solutions]
        if any(q.shape!=(6,) or not np.isfinite(q).all() for q in excluded):raise ValueError('Invalid excluded IK branch')
        def excluded_branch(q):return any(np.max(np.abs(q-other))<=.15 for other in excluded)
        def check():
            if cancelled is not None and cancelled():raise InterruptedError('IK search cancelled')
        check();key=target.tobytes()
        for solution in self._ik_cache.get(key,[]):
            # Nearby branch reuse only; recheck the current scene and held box.
            if not excluded_branch(solution) and np.max(np.abs(solution-seed))<=.15 and (not check_collision or self.valid(solution)):
                details.update(status='verified_goal',cache_hit=True)
                self._ik_cache.move_to_end(key);self.ik_cache_hits+=1;return solution.copy()
        rng=np.random.default_rng(random_seed);deadline=time.monotonic()+seconds
        for attempt in range(restarts+1):
            q=np.clip(seed,self.lower,self.upper) if attempt==0 else rng.uniform(self.lower,self.upper)
            for _ in range(iterations):
                check()
                if time.monotonic()>deadline:
                    details['status']='budget_exhausted';return None
                current=self.fk(q);ep=target[:3,3]-current[:3,3];er=_rotvec(target[:3,:3]@current[:3,:3].T)
                if np.linalg.norm(ep)<1e-6 and np.linalg.norm(er)<5e-5:
                    if excluded_branch(q):details['excluded_branches']+=1;break
                    if not check_collision or self.valid(q):
                        solutions=self._ik_cache.setdefault(key,[])
                        if len(solutions)<4:solutions.append(q.copy())
                        self._ik_cache.move_to_end(key)
                        if len(self._ik_cache)>512:self._ik_cache.popitem(last=False)
                        details['status']='verified_goal';return q
                    details['converged_colliding']+=1
                    for pair in getattr(self,'last_collision_pairs',None) or self.collisions(q):
                        if pair not in details['collision_pairs'] and len(details['collision_pairs'])<8:details['collision_pairs'].append(pair)
                    break
                jp=np.zeros((3,self.model.nv));jr=jp.copy()
                mj.mj_jacBody(self.model,self.data,jp,jr,self.tip_id)
                jac=np.vstack([jp[:,self.daddr],.3*jr[:,self.daddr]])
                error=np.concatenate([ep,.3*er])
                delta=np.linalg.solve(jac.T@jac+np.eye(6)*1e-4,jac.T@error)
                length=np.linalg.norm(delta)
                if length>.2:delta*=.2/length
                q=np.clip(q+delta,self.lower,self.upper)
        if details['converged_colliding']:details['status']='converged_in_collision'
        elif details['excluded_branches']:details['status']='alternative_branch_not_found'
        return None


RobotModel=EC66Model
