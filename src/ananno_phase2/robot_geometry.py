"""Original STL visual geometry and URDF FK, independent of renderer."""
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import numpy as np
from .robot_profiles import resolve_mesh_path,add_virtual_tool


def rpy_rotation(rpy):
    r,p,y=rpy;cr,sr=math.cos(r),math.sin(r);cp,sp=math.cos(p),math.sin(p);cy,sy=math.cos(y),math.sin(y)
    return np.array([[cy,-sy,0],[sy,cy,0],[0,0,1.]])@np.array([[cp,0,sp],[0,1,0],[-sp,0,cp]])@np.array([[1,0,0],[0,cr,-sr],[0,sr,cr]])


def origin_matrix(element):
    pose=np.eye(4)
    if element is not None:
        pose[:3,3]=[float(x) for x in element.get('xyz','0 0 0').split()]
        pose[:3,:3]=rpy_rotation([float(x) for x in element.get('rpy','0 0 0').split()])
    return pose


def load_stl(path,limit=900):
    data=Path(path).read_bytes()
    count=struct.unpack_from('<I',data,80)[0] if len(data)>=84 else 0
    if 84+50*count==len(data):
        records=np.frombuffer(data,offset=84,count=count,dtype=np.dtype([('normal','<f4',(3,)),('vertices','<f4',(3,3)),('attr','<u2')]))
        triangles=records['vertices'].astype(float)
    else:
        vertices=[list(map(float,line.split()[1:])) for line in data.decode('ascii').splitlines() if line.strip().startswith('vertex ')]
        triangles=np.asarray(vertices,dtype=float).reshape(-1,3,3)
    if not np.isfinite(triangles).all():raise ValueError('Mesh contains invalid vertices')
    if len(triangles)<=limit:return triangles.copy()
    # Collapse nearby vertices while retaining the surface topology. Sampling
    # isolated triangles would turn the robot into a misleading perforated shell.
    vertices=triangles.reshape(-1,3);span=float(np.max(np.ptp(vertices,axis=0)))
    cell=max(span/35,1e-7);simplified=triangles
    for _ in range(12):
        keys=np.round(vertices/cell).astype(np.int64)
        _,inverse=np.unique(keys,axis=0,return_inverse=True)
        count=np.bincount(inverse);centres=np.column_stack([
            np.bincount(inverse,weights=vertices[:,axis])/count for axis in range(3)])
        faces=inverse.reshape(-1,3)
        valid=(faces[:,0]!=faces[:,1])&(faces[:,1]!=faces[:,2])&(faces[:,0]!=faces[:,2])
        faces=faces[valid]
        _,unique=np.unique(np.sort(faces,axis=1),axis=0,return_index=True)
        simplified=centres[faces[unique]]
        if len(simplified)<=limit:break
        cell*=1.3
    return simplified.copy()


class RobotGeometry:
    def __init__(self,urdf,*,tip=None,tool_definition=None):
        self.path=Path(urdf).resolve();root=ET.parse(self.path).getroot();self.joints=[];self.meshes=[]
        add_virtual_tool(root,tool_definition)
        names={n.get('name') for n in root.findall('link')}
        self.tip=tip or ('cup_link' if 'cup_link' in names else 'tool0')
        if self.tip not in names:raise ValueError('TCP not present in visual robot')
        self.names=[];self.lower=[];self.upper=[]
        for joint in root.findall('joint'):
            kind=joint.get('type');axis=np.array([float(x) for x in joint.find('axis').get('xyz','1 0 0').split()]) if joint.find('axis') is not None else np.array([1.,0,0])
            self.joints.append((joint.find('parent').get('link'),joint.find('child').get('link'),origin_matrix(joint.find('origin')),axis,kind,joint.get('name')))
            if kind=='revolute':
                self.names.append(joint.get('name'));self.lower.append(float(joint.find('limit').get('lower')));self.upper.append(float(joint.find('limit').get('upper')))
        self.lower=np.array(self.lower);self.upper=np.array(self.upper)
        for link in root.findall('link'):
            visual=link.find('visual')
            if visual is None:visual=link.find('collision')
            if visual is None:continue
            mesh=visual.find('geometry/mesh')
            if mesh is not None:
                path=resolve_mesh_path(self.path,mesh.get('filename'))
                triangles=load_stl(path)*np.array([float(x) for x in mesh.get('scale','1 1 1').split()])
            else:
                box=visual.find('geometry/box')
                if box is None:continue
                x,y,z=np.array([float(v) for v in box.get('size').split()])/2
                points=np.array([[-x,-y,-z],[x,-y,-z],[x,y,-z],[-x,y,-z],[-x,-y,z],[x,-y,z],[x,y,z],[-x,y,z]])
                triangles=points[np.array([(0,1,2),(0,2,3),(4,6,5),(4,7,6),(0,5,1),(0,4,5),(1,6,2),(1,5,6),(2,7,3),(2,6,7),(3,4,0),(3,7,4)])]
            self.meshes.append((link.get('name'),origin_matrix(visual.find('origin')),triangles))

    def transforms(self,q):
        q=np.asarray(q,dtype=float)
        if q.shape!=(6,) or not np.isfinite(q).all() or np.any(q<self.lower) or np.any(q>self.upper):raise ValueError('Robot joint values outside limits')
        values=dict(zip(self.names,q));poses={'base_link':np.eye(4)};pending=list(self.joints)
        while pending:
            before=len(pending)
            for joint in list(pending):
                parent,child,origin,axis,kind,name=joint
                if parent not in poses:continue
                motion=np.eye(4)
                if kind=='revolute':
                    axis=axis/np.linalg.norm(axis);x,y,z=axis
                    skew=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
                    angle=values[name];motion[:3,:3]=np.eye(3)+math.sin(angle)*skew+(1-math.cos(angle))*(skew@skew)
                poses[child]=poses[parent]@origin@motion;pending.remove(joint)
            if len(pending)==before:raise ValueError('Disconnected robot hierarchy')
        return poses

    def tcp_pose(self,q):return self.transforms(q)[self.tip]

    def posed_meshes(self,q):
        poses=self.transforms(q);result=[]
        for link,local,triangles in self.meshes:
            pose=poses[link]@local
            result.append({'link':link,'triangles':triangles@pose[:3,:3].T+pose[:3,3]})
        return result
