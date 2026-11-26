"""Interactive native 3D editor canvas; CAD meshes projected with QPainter."""
import math
import numpy as np
from PyQt5 import QtCore as C,QtGui as G,QtWidgets as W
from .workcell_state import transform

EDGES=((0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7))
FACES=((0,1,2),(0,2,3),(4,6,5),(4,7,6),(0,5,1),(0,4,5),(1,6,2),(1,5,6),(2,7,3),(2,6,7),(3,4,0),(3,7,4))


def box_points(size,pose):
    x,y,z=np.asarray(size)/2
    points=np.array([[-x,-y,-z],[x,-y,-z],[x,y,-z],[-x,y,-z],[-x,-y,z],[x,-y,z],[x,y,z],[-x,y,z]])
    return points@pose[:3,:3].T+pose[:3,3]


class WorkcellCanvas(W.QWidget):
    selected=C.pyqtSignal(str)
    moved=C.pyqtSignal(str)

    def __init__(self,state,geometry,parent=None):
        super().__init__(parent);self.state=state;self.geometry=geometry;self.selection='pallet'
        self.yaw=math.radians(30);self.pitch=math.radians(30);self.zoom=1.
        self.focus=np.zeros(3);self.radius=1.;self._meshes=[];self._q=None;self._hits=[];self._drag=None
        self.setMinimumSize(550,420);self.setMouseTracking(True)
        self.setToolTip('左键选中并移动对象；右键旋转视角；滚轮缩放。俯视图适合摆放工位。')
        self.fit_view()

    def _robot_meshes(self):
        key=tuple(self.state.q)
        if key!=self._q:self._meshes=self.geometry.posed_meshes(self.state.q);self._q=key
        return self._meshes

    def objects(self):
        state=self.state;length,width,height=state.dimensions
        thickness=state.config.get('pallet_thickness_m',.04)
        deck=state.pallet_pose@transform((length/2,width/2,-thickness/2))
        result=[('pallet',box_points((length,width,thickness),deck),'#bf945b')]
        result.append(('pickup',box_points(state.sample,state.source_box_pose()),'#38a7cb'))
        for item in state.fixed_obstacles():
            key='pickup' if item['id']=='pickup_table' else item['id']
            result.append((key,box_points(item['size'],np.asarray(item['pose'])),'#72899c' if key=='pickup' else '#a78276'))
        return result

    def fit_view(self):
        points=[np.array([[0,0,0]])]
        points.extend(mesh['triangles'].reshape(-1,3) for mesh in self._robot_meshes())
        points.extend(p for _,p,_ in self.objects())
        length,width,height=self.state.dimensions
        points.append(box_points((length,width,height),self.state.pallet_pose@transform((length/2,width/2,height/2))))
        all_points=np.concatenate(points);low=all_points.min(axis=0);high=all_points.max(axis=0)
        self.focus=(low+high)/2;self.radius=max(.45,float(np.linalg.norm(high-low))/2)
        self.zoom=1.;self.update()

    def view_top(self):self.yaw=0.;self.pitch=math.pi/2;self.update()
    def view_3d(self):self.yaw=math.radians(30);self.pitch=math.radians(30);self.update()

    def matrix(self):
        ca,sa=math.cos(self.yaw),math.sin(self.yaw);sp,cp=math.sin(self.pitch),math.cos(self.pitch)
        return np.array([[ca,-sa,0],[-sp*sa,-sp*ca,-cp],[-cp*sa,-cp*ca,sp]])

    @property
    def scale(self):return min(max(1,self.width()),max(1,self.height()))/(2.25*self.radius)*self.zoom

    def project(self,points):
        result=(np.asarray(points)-self.focus)@self.matrix().T
        result[...,:2]*=self.scale;result[...,0]+=self.width()/2;result[...,1]+=self.height()/2
        return result

    def drag_entity(self,key,delta_pixels):
        if key=='robot':return
        delta=np.linalg.solve(self.matrix()[:2,:2]*self.scale,np.asarray(delta_pixels,dtype=float))
        position=self.state.pose(key)[:3,3].copy();position[:2]+=delta
        self.state.set_position(key,position);self.moved.emit(key);self.update()

    def _line(self,painter,start,end,color,width=1,style=C.Qt.SolidLine):
        a,b=self.project(np.asarray([start,end]))[:,:2]
        painter.setPen(G.QPen(G.QColor(color),width,style));painter.drawLine(C.QPointF(*a),C.QPointF(*b))

    def _mesh_opacity(self,link):
        return .32 if getattr(self,'transparent_tool',False) and link in self.state.config.get('touch_links',[]) else 1.

    def paintEvent(self,event):
        painter=G.QPainter(self);painter.setRenderHint(G.QPainter.Antialiasing)
        painter.fillRect(self.rect(),G.QColor('#edf2f6'));self._hits=[]
        extent=max(2.,math.ceil(self.radius*2));floor=min(-.1,float(self.state.pallet_pose[2,3]-.05))
        for v in np.arange(-extent,extent+.1,.25):
            self._line(painter,(v,-extent,floor),(v,extent,floor),'#dbe3eb')
            self._line(painter,(-extent,v,floor),(extent,v,floor),'#dbe3eb')
        triangles=[]
        for mesh in self._robot_meshes():
            if self.state.config.get('robot_id')=='fanuc_r2000ic210l':
                color='#e8b521' if mesh['link'] not in ('base_link','link_6','packing_tool') else '#3c434a' if mesh['link']!='packing_tool' else '#338da3'
            else:color='#4e7899' if mesh['link'] not in ('base_link','cup_link','link_base') else '#29455c' if mesh['link']=='base_link' else '#b3bdc5'
            triangles.append(('robot',mesh['triangles'],color,self._mesh_opacity(mesh['link'])))
        for key,vertices,color in self.objects():triangles.append((key,vertices[np.array(FACES)],color,1.))
        faces=[];light=np.array([.2,-.4,1.]);light/=np.linalg.norm(light)
        for key,vertices,color,opacity in triangles:
            projected=self.project(vertices)
            normals=np.cross(vertices[:,1]-vertices[:,0],vertices[:,2]-vertices[:,0]);norms=np.linalg.norm(normals,axis=1)
            illumination=.62+.35*np.abs(normals@light/np.maximum(norms,1e-10))
            for index,screen in enumerate(projected):
                tint=G.QColor(color);factor=illumination[index]
                tint.setRgbF(tint.redF()*factor,tint.greenF()*factor,tint.blueF()*factor,opacity)
                faces.append((float(screen[:,2].mean()),key,screen[:,:2],tint))
        painter.setPen(C.Qt.NoPen)
        for _,key,points,color in sorted(faces,key=lambda f:f[0]):
            polygon=G.QPolygonF([C.QPointF(*p) for p in points]);painter.setBrush(color);painter.drawPolygon(polygon)
            self._hits.append((key,polygon))
        length,width,height=self.state.dimensions
        limits=box_points((length,width,height),self.state.pallet_pose@transform((length/2,width/2,height/2)))
        for a,b in EDGES:self._line(painter,limits[a],limits[b],'#afc0cf',1,C.Qt.DashLine)
        selected_points=[]
        if self.selection=='pallet':
            thickness=self.state.config.get('pallet_thickness_m',.04)
            selected_points=box_points((length,width,thickness),self.state.pallet_pose@transform((length/2,width/2,-thickness/2)))
        elif self.selection=='pickup':selected_points=box_points(self.state.sample,self.state.source_box_pose())
        elif self.selection!='robot':
            for key,points,_ in self.objects():
                if key==self.selection:selected_points=points;break
        if len(selected_points):
            for a,b in EDGES:self._line(painter,selected_points[a],selected_points[b],'#ed922d',2)
        for start,basis,label,color in [(np.zeros(3),np.eye(3),'基座 O','#315777'),
                (self.state.pallet_pose[:3,3],self.state.pallet_pose[:3,:3],'托盘 P0','#b77828')]:
            for i,c in enumerate(('#d85a50','#3e9c6b','#4b7fc6')):
                end=start+basis[:,i]*.22;self._line(painter,start,end,c,2)
                p=self.project(np.array([end]))[0];painter.setPen(G.QColor(c));painter.drawText(C.QPointF(p[0]+4,p[1]-3),'XYZ'[i]+'+')
            p=self.project(np.array([start]))[0];painter.setPen(G.QColor(color));painter.drawText(C.QPointF(p[0]+4,p[1]+16),label)
        tcp=self.geometry.tcp_pose(self.state.q)[:3,3];p=self.project(np.array([tcp]))[0]
        painter.setPen(G.QPen(G.QColor('#d96c35'),2));painter.drawEllipse(C.QPointF(p[0],p[1]),4,4)
        painter.setFont(G.QFont('Microsoft YaHei UI',9));painter.setPen(G.QColor('#536d84'))
        painter.drawText(18,25,self.state.config.get('robot_name','EC66')+' URDF/STL模型  /  工位预览 · 未验证')
        if self.state.config.get('tool_definition'):
            values=self.state.config['tool_definition']['size_m']
            painter.drawText(18,45,f'吸盘外包络 {values[0]*1000:g}×{values[1]*1000:g} mm；高度 {values[2]*1000:g} mm 暂定 · 未标定')
        painter.drawText(18,self.height()-18,'左键选择 / 移动物体    右键旋转视角    滚轮缩放    虚线为堆码限高')

    def mousePressEvent(self,event):
        if event.button()==C.Qt.LeftButton:
            point=C.QPointF(event.pos());key=next((k for k,p in reversed(self._hits) if p.containsPoint(point,C.Qt.OddEvenFill)),None)
            if key:self.selection=key;self.selected.emit(key)
            self._drag=('move',event.pos());self.update()
        elif event.button()==C.Qt.RightButton:self._drag=('orbit',event.pos())

    def mouseMoveEvent(self,event):
        if self._drag:
            kind,old=self._drag;delta=event.pos()-old;self._drag=(kind,event.pos())
            if kind=='move':self.drag_entity(self.selection,(delta.x(),delta.y()))
            else:
                self.yaw+=delta.x()*.008;self.pitch=np.clip(self.pitch-delta.y()*.008,.12,math.pi/2);self.update()

    def mouseReleaseEvent(self,event):self._drag=None;self.update()
    def wheelEvent(self,event):self.zoom=float(np.clip(self.zoom*(1.13**(event.angleDelta().y()/120)),.2,8));self.update()
