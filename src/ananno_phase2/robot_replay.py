"""Read-only CAD replay of the verified joint trajectory saved with a packing run."""
from dataclasses import dataclass
from pathlib import Path
import math
import numpy as np
from PyQt5 import QtCore as C, QtGui as G, QtWidgets as W

from .replay_timeline import ReplayTimeline
from .robot_geometry import RobotGeometry
from .workcell_canvas import WorkcellCanvas, box_points
from .workcell_state import WorkcellState, transform
from .qt_widgets import VIVID_PALETTE
from .models import Pallet

OPERATIONS={'approach_pick':'接近取箱','pick':'吸附抓取','lift':'脱离取箱台',
            'transfer':'搬运至接近点','place':'放置箱体','retreat':'释放后撤离'}


@dataclass
class ReplayBundle:
    state: WorkcellState
    geometry: RobotGeometry
    timeline: ReplayTimeline
    snapshot: Path
    directions: dict


def load_replay_bundle(project_dir,document,result_path,pallet_index):
    timeline=ReplayTimeline(document,pallet_index)
    audit=document['robot_diagnostics'];motion=audit['motion_verification']
    name=audit.get('scene_snapshot')
    if result_path is None or not name or Path(name).name!=name:
        raise ValueError('该结果缺少计算时的工位快照，请打开原结果文件；仍缺失时需启用机器人完整校验重新计算。')
    directory=Path(result_path).resolve().parent;snapshot=(directory/name).resolve()
    if snapshot.parent!=directory or not snapshot.is_file():
        raise ValueError('计算时的工位快照已丢失，请保留结果文件夹中的工位快照，或重新计算。')
    from .robot_runtime import prepare_robot_runtime
    prepare_robot_runtime(project_dir,preload=True)
    from .robot_offline import OfflineRobotVerifier
    verifier=OfflineRobotVerifier(snapshot)
    mapping=motion.get('pallet_frame_mapping') or {}
    dims=mapping.get('input_dimensions')
    if not dims:
        dims=[timeline.pallet['pallet'][k] for k in ('length','width','height')]
    verifier.configure_pallet_axes(Pallet(*dims))
    if motion.get('model_parameters_sha256')!=verifier.model_fingerprint:
        raise ValueError('工位或机械臂模型与该结果计算时不同，不能使用当前模型冒充历史轨迹；请重新计算。')
    state=WorkcellState.load(project_dir,snapshot)
    # The backend may have remapped an older input frame into the long-side-X frame.
    state.pallet_pose=verifier.base_pallet.copy()
    state.dimensions=np.array([timeline.pallet['pallet'][k] for k in ('length','width','height')])*verifier.scale
    cfg=state.config
    geometry=RobotGeometry(cfg['urdf'],tip=cfg.get('tip_link'),tool_definition=cfg.get('tool_definition'))
    if timeline.joint_names!=geometry.names:raise ValueError('轨迹关节名称与当前机械臂模型不一致。')
    timeline.validate_joint_limits(geometry.lower,geometry.upper)
    if not np.allclose(timeline.samples[0][1][0],state.q,rtol=0,atol=1e-8):
        raise ValueError('轨迹初始构型与工位快照不一致，请重新计算。')
    directions={str(s['box_id']):s for s in motion.get('directions_by_box',[]) if s['pallet']==pallet_index}
    return ReplayBundle(state,geometry,timeline,snapshot,directions)


class ReplayCanvas(WorkcellCanvas):
    def __init__(self,bundle,parent=None):
        self.bundle=bundle;self.frame=bundle.timeline.frame_at(0);self.transparent_tool=True
        bundle.state.q=self.frame.q.copy()
        self._items=bundle.timeline.items;self._colors={key:VIVID_PALETTE[n%len(VIVID_PALETTE)] for n,key in enumerate(self._items)}
        super().__init__(bundle.state,bundle.geometry,parent)
        self.selection=None
        self.setToolTip('拖动旋转视角 · 滚轮缩放 · 双击适应画面；工位位置只读')

    def _original_size(self,item):
        size=np.array([item['placed_size'][k] for k in ('length','width','height')],dtype=float)*self.state.config['length_scale_to_m']
        if item['orientation']=='Z90':size[[0,1]]=size[[1,0]]
        return size

    def _box_tcp(self,item):
        saved=self.bundle.directions.get(str(item['id']),{}).get('grasp')
        if saved is not None:
            from .ec66_model import pose_matrix
            return pose_matrix(saved['box_T_tcp'])
        # Historical results used centered suction. Do not reinterpret old
        # verified joint paths with the new edge-alignment convention.
        size=self._original_size(item);matrix=np.asarray(self.state.config['box_T_tcp_rotation'],dtype=float).copy()
        matrix[:3,3]=np.array([0,0,size[2]/2])+np.asarray(self.state.config['tcp_offset_from_box_top_m'])
        return matrix

    def objects(self):
        state=self.state;length,width,_=state.dimensions;thickness=state.config.get('pallet_thickness_m',.04)
        result=[('pallet',box_points((length,width,thickness),state.pallet_pose@transform((length/2,width/2,-thickness/2))),'#ba8b4f')]
        for obstacle in state.fixed_obstacles():
            result.append((obstacle['id'],box_points(obstacle['size'],np.asarray(obstacle['pose'])),'#7e8fa0'))
        scale=state.config['length_scale_to_m']
        for key in self.frame.completed_ids:
            item=self._items[key];size=np.array([item['placed_size'][k] for k in ('length','width','height')])*scale
            from .pallet_coordinates import PUBLIC_FRAME,reflected_box_position
            position=item['position']
            if self.bundle.timeline.coordinate_frame==PUBLIC_FRAME:position=reflected_box_position(position,item['placed_size']['width'],state.dimensions[1]/scale)
            center=np.array([position[k] for k in ('x','y','z')])*scale+size/2
            result.append(('placed_'+key,box_points(size,state.pallet_pose@transform(center)),self._colors[key]))
        if self.frame.source_id is not None:
            key=self.frame.source_id;item=self._items[key];size=self._original_size(item)
            surface=state.config.get('pick_surface')
            if surface:
                pose=np.asarray(surface['pose'],dtype=float).copy();pose[:3,3]+=pose[:3,2]*size[2]/2
            else:pose=np.asarray(state.config['pick_tcp_pose'])@np.linalg.inv(self._box_tcp(item))
            result.append(('source_'+key,box_points(size,pose),self._colors[key]))
        if self.frame.carrying_id is not None:
            key=self.frame.carrying_id;item=self._items[key]
            pose=self.geometry.tcp_pose(state.q)@np.linalg.inv(self._box_tcp(item))
            result.append(('carried_'+key,box_points(self._original_size(item),pose),self._colors[key]))
        return result

    def set_frame(self,frame):
        self.frame=frame;self.state.q=frame.q.copy();self.update()

    def mousePressEvent(self,event):
        if event.button() in (C.Qt.LeftButton,C.Qt.RightButton):self._drag=('orbit',event.pos())
        else:event.ignore()

    def mouseDoubleClickEvent(self,event):self.fit_view()

    def paintEvent(self,event):
        super().paintEvent(event)
        painter=G.QPainter(self);painter.fillRect(0,0,self.width(),56,G.QColor('#edf2f6'))
        painter.fillRect(0,self.height()-34,self.width(),34,G.QColor('#edf2f6'))
        painter.setPen(G.QColor('#193b5b'));painter.setFont(G.QFont('Microsoft YaHei UI',11,G.QFont.Bold))
        painter.drawText(18,24,self.state.config.get('robot_name','机械臂')+' · 离线轨迹回放')
        painter.setFont(G.QFont('Microsoft YaHei UI',9))
        painter.drawText(18,46,'箱体 '+str(self.frame.stage['box_id'])+'  |  '+OPERATIONS[self.frame.stage['operation']])
        painter.drawText(18,self.height()-13,'拖动旋转视角 · 滚轮缩放 · 双击适应画面 · 已放箱体固定')


class RobotReplayDialog(W.QDialog):
    def __init__(self,bundle,parent=None):
        super().__init__(parent);self.bundle=bundle;self.timeline=bundle.timeline;self.elapsed=0.
        self.setAttribute(C.Qt.WA_DeleteOnClose,True)
        self.setWindowFlags(self.windowFlags()|C.Qt.WindowMinMaxButtonsHint)
        self.setWindowTitle(f"托盘 {self.timeline.pallet['pallet_index']} · 机械臂动态装箱回放")
        self.resize(1360,880);self.setMinimumSize(920,640)
        self.setStyleSheet('QDialog {background:#f2f5f9;} QLabel {color:#253e57;font-size:12px;} QPushButton {min-height:26px;padding:3px 10px;} QGroupBox {font-weight:600;padding-top:12px;}')
        self.timer=C.QTimer(self);self.timer.setInterval(33);self.timer.timeout.connect(self._tick)
        self.clock=C.QElapsedTimer()
        layout=W.QVBoxLayout(self);top=W.QHBoxLayout()
        title=W.QLabel(f"PALLET-{self.timeline.pallet['pallet_index']:03d}  /  {len(self.timeline.items)} 箱")
        title.setStyleSheet('font-size:20px;font-weight:700');top.addWidget(title);top.addStretch()
        for text,method in [('立体视角',self.view_3d),('俯视',self.view_top),('适应画面',self.fit_view)]:
            button=W.QPushButton(text);button.clicked.connect(method);top.addWidget(button)
        self.transparent_tool=W.QCheckBox('吸盘半透明');self.transparent_tool.setChecked(True)
        self.transparent_tool.toggled.connect(self._set_tool_transparency);top.addWidget(self.transparent_tool)
        layout.addLayout(top)
        split=W.QSplitter();layout.addWidget(split,1);self.canvas=ReplayCanvas(bundle);split.addWidget(self.canvas)
        sidebar=W.QWidget();sidebar.setMinimumWidth(235);sidebar.setMaximumWidth(300)
        details=W.QVBoxLayout(sidebar);details.setContentsMargins(12,8,6,8)
        self.operation_label=W.QLabel();self.operation_label.setWordWrap(True);self.operation_label.setStyleSheet('font-size:16px;font-weight:700;')
        self.progress_label=W.QLabel();self.direction_label=W.QLabel();self.direction_label.setWordWrap(True)
        for label in (self.operation_label,self.progress_label,self.direction_label):details.addWidget(label)
        group=W.QGroupBox('关节角（度）');form=W.QFormLayout(group);self.joint_labels=[]
        for name in self.timeline.joint_names:
            value=W.QLabel();form.addRow(name,value);self.joint_labels.append(value)
        details.addWidget(group)
        robot_info=W.QLabel(bundle.state.config.get('robot_name','机械臂'));robot_info.setWordWrap(True);details.addWidget(robot_info)
        tool=bundle.state.config.get('tool_definition')
        if tool:
            dimensions=tool['size_m'];note=W.QLabel(f'吸盘 {dimensions[0]*1000:g}×{dimensions[1]*1000:g} mm\n工具高度 {dimensions[2]*1000:g} mm（暂定）')
            note.setWordWrap(True);details.addWidget(note)
        note=W.QLabel('播放计算时保存的关节轨迹\n工位与已放箱体只读\n离线验证，未连接真机')
        note.setWordWrap(True);details.addWidget(note);details.addStretch()
        source=W.QLabel('工位：'+bundle.snapshot.name);source.setToolTip(str(bundle.snapshot));source.setWordWrap(True);details.addWidget(source)
        split.addWidget(sidebar);split.setStretchFactor(0,1)
        controls=W.QHBoxLayout()
        for name,action in [('播放',self.play),('暂停',self.pause),('重置',self.reset),('上一箱',self.previous_box),('下一箱',self.next_box),('最终',self.final)]:
            button=W.QPushButton(name);button.clicked.connect(action);controls.addWidget(button)
        controls.addStretch();controls.addWidget(W.QLabel('倍速'))
        self.speed=W.QComboBox()
        for value in (.25,.5,1.,2.,5.,10.,20.):self.speed.addItem(f'{value:g}×',value)
        self.speed.setCurrentIndex(2);self.speed.currentIndexChanged.connect(self._speed_changed);controls.addWidget(self.speed)
        layout.addLayout(controls)
        row=W.QHBoxLayout();self.slider=W.QSlider(C.Qt.Horizontal);self.slider.setRange(0,10000)
        self.slider.sliderPressed.connect(self.pause);self.slider.valueChanged.connect(self._scrub)
        self.time_label=W.QLabel();self.time_label.setMinimumWidth(190);row.addWidget(self.slider,1);row.addWidget(self.time_label);layout.addLayout(row)
        self.seek_time(0)

    def _set_tool_transparency(self,enabled):self.canvas.transparent_tool=enabled;self.canvas.update()
    def view_3d(self):self.canvas.view_3d()
    def view_top(self):self.canvas.view_top()
    def fit_view(self):self.canvas.fit_view()

    def seek_time(self,seconds):
        frame=self.timeline.frame_at(seconds);self.elapsed=frame.elapsed;self.canvas.set_frame(frame)
        self.slider.blockSignals(True);self.slider.setValue(round(self.elapsed/self.timeline.duration*10000));self.slider.blockSignals(False)
        self.operation_label.setText('箱体 '+str(frame.stage['box_id'])+'\n'+OPERATIONS[frame.stage['operation']])
        self.progress_label.setText(f'已放置 {len(frame.completed_ids)} / {len(self.timeline.items)} 箱')
        record=self.bundle.directions.get(str(frame.stage['box_id']),{})
        direction=record.get('open_direction',frame.stage.get('open_direction','—'))
        mode=record.get('transfer_mode')
        description='侧向直线搬运' if mode=='cartesian_direct' else '上方接近 / 关节路径搬运' if direction=='+Z' else '侧向接近 / 关节路径搬运'
        self.direction_label.setText('接近方向 '+direction+'\n'+description)
        self.time_label.setText(f'{self.elapsed:.1f} / {self.timeline.duration:.1f} 秒（轨迹时间）')
        for label,value in zip(self.joint_labels,frame.q):label.setText(f'{math.degrees(value):.2f}°')
        if frame.finished:self.pause()
        return frame

    def _scrub(self,value):self.pause();self.seek_time(self.timeline.duration*value/10000)
    def _speed_changed(self,*args):
        if self.timer.isActive():self.clock.restart()
    def _tick(self):
        dt=self.clock.restart()/1000
        self.seek_time(self.elapsed+dt*float(self.speed.currentData()))
    def play(self):
        if self.elapsed>=self.timeline.duration:self.seek_time(0)
        self.clock.start();self.timer.start()
    def pause(self):self.timer.stop()
    def reset(self):self.pause();self.seek_time(0)
    def final(self):self.pause();self.seek_time(self.timeline.duration)
    def previous_box(self):
        self.pause();values=[v for v in self.timeline.box_starts if v<self.elapsed-1e-6];self.seek_time(values[-1] if values else 0)
    def next_box(self):
        self.pause();values=[v for v in self.timeline.box_starts if v>self.elapsed+1e-6];self.seek_time(values[0] if values else self.timeline.duration)
    def closeEvent(self,event):self.pause();event.accept()
