"""Visual, editable EC66 workcell dialog for the existing desktop application."""
import math
from decimal import Decimal
import copy
from pathlib import Path
import numpy as np
from PyQt5 import QtCore as C,QtWidgets as W
from .workcell_state import WorkcellState,transform
from .robot_geometry import RobotGeometry,rpy_rotation
from .workcell_canvas import WorkcellCanvas
from .robot_profiles import profiles
from .robot_validation_settings import planning_options
from .robot_motion import motion_options


def spin(value=0,low=-100000,high=100000,decimals=3):
    widget=W.QDoubleSpinBox();widget.setDecimals(decimals);widget.setRange(low,high)
    widget.setSingleStep(10);widget.setValue(value);widget.setKeyboardTracking(False)
    return widget


class WorkcellEditor(W.QDialog):
    def __init__(self,project_dir,dimensions_mm=(1200,800,1400),sample_mm=(300,200,200),scene_path=None,parent=None):
        super().__init__(parent);self.root=Path(project_dir).resolve();self.applied_path=None
        self.state=WorkcellState.load(self.root,scene_path) if scene_path else WorkcellState.create(self.root,dimensions_mm,sample_mm)
        self.state.dimensions=np.array(dimensions_mm,dtype=float)*.001
        self.state.dimensions[:2]=sorted(self.state.dimensions[:2],reverse=True)
        self.state.sample=np.array(sample_mm,dtype=float)*.001;self.state.validate()
        self.geometry=self._geometry_for_state(self.state);self.entity='pallet';self._syncing=False
        self.setWindowTitle('机器人可视化工位 · 选择型号与工位位置');self.resize(1440,900);self.setMinimumSize(1100,720)
        self.setStyleSheet('QDialog {background:#f3f6fa;} QLabel {color:#30485f;} QGroupBox {font-weight:600;border:1px solid #dce4ec;border-radius:5px;margin-top:9px;padding-top:9px;} QGroupBox::title{subcontrol-origin:margin;left:10px;} QDoubleSpinBox {min-height:24px;} QPushButton {min-height:27px;padding:3px 9px;}')
        layout=W.QVBoxLayout(self);header=W.QHBoxLayout();self.title=W.QLabel();self.title.setStyleSheet('font-size:20px;font-weight:700;')
        header.addWidget(self.title);header.addStretch();header.addWidget(W.QLabel('X沿托盘长边 · Y沿短边 · Z向上  |  位置单位 mm'))
        layout.addLayout(header)
        tools=W.QHBoxLayout();layout.addLayout(tools)
        self.canvas=WorkcellCanvas(self.state,self.geometry)
        for text,callback in [('立体视图',self.canvas.view_3d),('俯视摆放',self.canvas.view_top),('适应画面',self.canvas.fit_view),('初始摆放',self.arrange_preset),('载入工位…',self.load_dialog),('另存为…',self.save_dialog)]:
            b=W.QPushButton(text);b.clicked.connect(callback);tools.addWidget(b)
        tools.addStretch();self.status=W.QLabel('虚拟工位 · 位置尚未验证');tools.addWidget(self.status)
        split=W.QSplitter();layout.addWidget(split,1);split.addWidget(self.canvas)
        sidebar=W.QWidget();right=W.QVBoxLayout(sidebar);right.setContentsMargins(10,0,0,0)
        right.addWidget(W.QLabel('机械臂型号'))
        self.robot_combo=W.QComboBox()
        for key,name in profiles().items():self.robot_combo.addItem(name,key)
        self.robot_combo.setCurrentIndex(self.robot_combo.findData(self.state.config.get('robot_id','ec66')))
        self.robot_combo.currentIndexChanged.connect(self._robot_changed);right.addWidget(self.robot_combo)
        self.object_combo=W.QComboBox();right.addWidget(W.QLabel('选中对象'));right.addWidget(self.object_combo)
        self.object_combo.currentIndexChanged.connect(self._combo_selected)
        tabs=W.QTabWidget();right.addWidget(tabs,1)
        placement=W.QWidget();place=W.QVBoxLayout(placement);form=W.QFormLayout();place.addLayout(form)
        self.position_fields=[spin() for _ in range(3)]
        for axis,field in zip('XYZ',self.position_fields):
            form.addRow(axis+' / mm',field);field.valueChanged.connect(self._position_changed)
        self.yaw_field=spin(0,-360,360);self.yaw_field.setSingleStep(5);form.addRow('绕Z旋转 / °',self.yaw_field);self.yaw_field.valueChanged.connect(self._yaw_changed)
        self.pose_note=W.QLabel();self.pose_note.setWordWrap(True);place.addWidget(self.pose_note)
        self.size_fields=[spin(100,1,100000) for _ in range(3)]
        for axis,field in zip('XYZ',self.size_fields):form.addRow('尺寸 '+axis+' / mm',field);field.valueChanged.connect(self._size_changed)
        row=W.QHBoxLayout();add=W.QPushButton('添加障碍物');remove=W.QPushButton('删除障碍物');row.addWidget(add);row.addWidget(remove);place.addLayout(row)
        add.clicked.connect(self._add_obstacle);remove.clicked.connect(self._remove_obstacle)
        place.addStretch();tabs.addTab(placement,'对象位置')
        robot=W.QWidget();joints=W.QVBoxLayout(robot);joints.addWidget(W.QLabel('初始关节角：拖动滑块查看真实连杆姿态'))
        self.joint_fields=[];self.joint_sliders=[]
        for i,(lo,hi) in enumerate(zip(self.geometry.lower,self.geometry.upper)):
            line=W.QHBoxLayout();line.addWidget(W.QLabel(f'J{i+1}'))
            slider=W.QSlider(C.Qt.Horizontal);slider.setRange(math.ceil(math.degrees(lo)*100),math.floor(math.degrees(hi)*100));line.addWidget(slider,1)
            field=spin(0,math.ceil(math.degrees(lo)*1000)/1000,math.floor(math.degrees(hi)*1000)/1000);field.setSingleStep(1);field.setMaximumWidth(100);line.addWidget(field)
            field.valueChanged.connect(lambda value,index=i:self._joint_changed(index,value))
            slider.valueChanged.connect(lambda value,index=i:self._joint_changed(index,value/100))
            self.joint_fields.append(field);self.joint_sliders.append(slider);joints.addLayout(line)
        check=W.QPushButton('检查当前初始姿态');check.clicked.connect(self.check_initial_pose);joints.addWidget(check)
        note=W.QLabel('此检查只判断当前构型的碰撞；完整抓取—搬运—放置—撤离路径由装箱计算检查。');note.setWordWrap(True);joints.addWidget(note);joints.addStretch();tabs.addTab(robot,'机械臂')
        grasp=W.QWidget();grasp_layout=W.QFormLayout(grasp)
        self.sample_fields=[spin(v*1000,1,100000) for v in self.state.sample]
        for axis,field in zip('XYZ',self.sample_fields):grasp_layout.addRow('预览箱 '+axis+' / mm',field);field.valueChanged.connect(self._sample_changed)
        self.include_table=W.QCheckBox('把取箱台加入碰撞环境');self.include_table.setChecked(self.state.include_table);self.include_table.toggled.connect(self._table_changed);grasp_layout.addRow(self.include_table)
        self.tool_group=W.QGroupBox('现场吸盘：虚拟外包络');tool_form=W.QFormLayout(self.tool_group)
        self.tool_fields=[spin(v,1,5000) for v in (600,800,250)]
        for title,field in zip(('吸盘面 X / mm','吸盘面 Y / mm','法兰→吸附面 / mm'),self.tool_fields):
            tool_form.addRow(title,field);field.valueChanged.connect(self._tool_changed)
        self.tool_note=W.QLabel('面尺寸600×800由用户提供；高度250为暂定值，尚未现场标定。');self.tool_note.setWordWrap(True);tool_form.addRow(self.tool_note)
        grasp_layout.addRow(self.tool_group)
        self.grasp_alignment=W.QComboBox();self.grasp_alignment.setObjectName('graspAlignment')
        self.grasp_alignment.addItem('靠已放箱侧两边对齐，余量向空侧','occupied_edges');self.grasp_alignment.addItem('箱顶中心吸取（旧方式）','center')
        default_alignment='occupied_edges' if self.state.config.get('tool_definition') else 'center'
        self.grasp_alignment.setCurrentIndex(self.grasp_alignment.findData(self.state.config.get('grasp_alignment',default_alignment)))
        self.grasp_alignment.currentIndexChanged.connect(self._alignment_changed);grasp_layout.addRow('吸盘边缘位置',self.grasp_alignment)
        self.offset_fields=[spin(v*1000) for v in self.state.config['tcp_offset_from_box_top_m']]
        for axis,field in zip('XYZ',self.offset_fields):grasp_layout.addRow('箱顶→TCP '+axis+' / mm',field);field.valueChanged.connect(self._grasp_changed)
        rotation=np.asarray(self.state.config['box_T_tcp_rotation'])[:3,:3]
        rpy=[math.atan2(rotation[2,1],rotation[2,2]),math.asin(float(np.clip(-rotation[2,0],-1,1))),math.atan2(rotation[1,0],rotation[0,0])]
        self.grasp_angles=[spin(math.degrees(v),-360,360) for v in rpy]
        for axis,field in zip('XYZ',self.grasp_angles):grasp_layout.addRow('抓取姿态 R'+axis+' / °',field);field.valueChanged.connect(self._grasp_changed)
        self.approach_distance=spin(self.state.config.get('approach_distance_m',.08)*1000,1,1000);self.approach_distance.valueChanged.connect(self._grasp_changed);grasp_layout.addRow('接近/撤离距离 mm',self.approach_distance)
        tip=W.QLabel('两边对齐时，XY偏置由每箱邻接关系自动确定，Z偏置仍保留；需吸盘面水平且与箱边平行。取箱台是台面中心，预览箱用于显示。');tip.setWordWrap(True);grasp_layout.addRow(tip)
        tabs.addTab(grasp,'抓取与预览')
        planning=W.QWidget();planning_form=W.QFormLayout(planning);options=planning_options(self.state.config)
        self.box_budget=spin(options['box_budget_seconds'],.1,3600,1);self.box_budget.setObjectName('boxValidationSeconds');self.box_budget.setSingleStep(5)
        self.path_budget=spin(options['path_budget_seconds'],.1,3600,1);self.path_budget.setObjectName('pathValidationSeconds');self.path_budget.setSingleStep(.5)
        self.full_batch=W.QSpinBox();self.full_batch.setRange(1,10000);self.full_batch.setValue(options['full_validation_batch_size'])
        self.tiered_check=W.QCheckBox('GA快速筛选后，按排名分批完整验证');self.tiered_check.setChecked(options['tiered_validation'])
        planning_form.addRow('每箱验证上限 / 秒',self.box_budget);planning_form.addRow('每段路径上限 / 秒',self.path_budget)
        planning_form.addRow('详细验证批次 / 个',self.full_batch);planning_form.addRow(self.tiered_check)
        motion=motion_options(self.state.config)
        self.pick_lift=spin(motion['pick_lift_m']*1000,1,2000);self.pick_lift.setObjectName('pickLiftMm')
        self.preplace_height=spin(motion['preplace_height_m']*1000,1,2000);self.preplace_height.setObjectName('preplaceHeightMm')
        self.preplace_offset=spin(motion['preplace_side_offset_m']*1000,1,2000);self.preplace_offset.setObjectName('preplaceOffsetMm')
        for widget,key,title in ((self.pick_lift,'pick_lift_m','取箱后竖直抬升 / mm'),(self.preplace_height,'preplace_height_m','预放置点高于目标 / mm'),(self.preplace_offset,'preplace_side_offset_m','侧向预放置偏移 / mm')):
            planning_form.addRow(title,widget);widget.valueChanged.connect(lambda value,key=key:self._planning_changed(key,value/1000))
        smooth_note=W.QLabel('搬运段可绕障；最后从预放置点下降或斜下降。关节轨迹自动做避障捷径和连续速度/加速度平滑，抓取及释放等操作边界保留停止。')
        smooth_note.setWordWrap(True);planning_form.addRow(smooth_note)
        note=W.QLabel('每箱独立计时；整次任务仍受装箱设置中的总时限约束。快速筛选不代表路径通过，最终结果必须完整验证。缓存只在本次计算进程内复用，不跨重启恢复。')
        note.setWordWrap(True);planning_form.addRow(note)
        for widget,key in ((self.box_budget,'box_budget_seconds'),(self.path_budget,'path_budget_seconds'),(self.full_batch,'full_validation_batch_size')):
            widget.valueChanged.connect(lambda value,key=key:self._planning_changed(key,value))
        self.tiered_check.toggled.connect(lambda value:self._planning_changed('tiered_validation',value));tabs.addTab(planning,'验证与计算')
        split.addWidget(sidebar);split.setStretchFactor(0,1);split.setStretchFactor(1,0);sidebar.setMinimumWidth(360);sidebar.setMaximumWidth(420)
        footer=W.QHBoxLayout();layout.addLayout(footer)
        warning=W.QLabel('摆放预览 ≠ 机器人可执行。应用后由计算按钮执行IK、碰撞和路径检查；不控制真实机械臂。');warning.setWordWrap(True);footer.addWidget(warning,1)
        cancel=W.QPushButton('取消');cancel.clicked.connect(self.reject);footer.addWidget(cancel)
        apply=W.QPushButton('应用工位并启用机器人校验');apply.setStyleSheet('background:#2375cb;color:white;font-weight:600;');apply.clicked.connect(self.apply_scene);footer.addWidget(apply)
        self.canvas.selected.connect(self.select_entity);self.canvas.moved.connect(self._canvas_moved)
        self._refresh_objects();self.select_entity('pallet');self._sync_robot_controls()

    def _planning_changed(self,key,value):
        if self._syncing:return
        # Only the edited setting changes; preserve other loaded values exactly.
        self.state.config[key]=value
        self._changed()

    def _geometry_for_state(self,state):
        return RobotGeometry(state.config['urdf'],tip=state.config.get('tip_link','cup_link'),
                             tool_definition=state.config.get('tool_definition'))

    def arrange_preset(self):
        length=self.state.dimensions[0]
        if self.state.config.get('robot_id')=='fanuc_r2000ic210l':
            self.state.pallet_pose=transform((-length/2,.85,.15))
            self.state.pick_pose=transform((1.2,-.8,.7));self.state.table_size=np.array([.8,.7,.7])
        else:
            self.state.pallet_pose=transform((-length/2,.45,-.15))
            self.state.pick_pose=transform((.45,-.45,-.1));self.state.table_size=np.array([.65,.5,.75])
        self.select_entity('pallet');self.canvas.fit_view();self._changed()

    def _sync_robot_controls(self):
        self._syncing=True;cfg=self.state.config
        self.title.setText('工位布局 / '+cfg.get('robot_name','EC66'))
        self.robot_combo.setCurrentIndex(self.robot_combo.findData(cfg.get('robot_id','ec66')))
        for i,(lo,hi) in enumerate(zip(self.geometry.lower,self.geometry.upper)):
            self.joint_fields[i].setRange(math.ceil(math.degrees(lo)*1000)/1000,math.floor(math.degrees(hi)*1000)/1000)
            self.joint_sliders[i].setRange(math.ceil(math.degrees(lo)*100),math.floor(math.degrees(hi)*100))
        definition=cfg.get('tool_definition');self.tool_group.setVisible(definition is not None)
        if definition:
            for field,value in zip(self.tool_fields,np.asarray(definition['size_m'])*1000):field.setValue(float(value))
            values=definition['size_m'];self.tool_note.setText(f'吸盘面 {values[0]*1000:g}×{values[1]*1000:g} mm；高度 {values[2]*1000:g} mm 为可调暂定值，尚未现场标定。')
        for field,value in zip(self.offset_fields,np.asarray(cfg['tcp_offset_from_box_top_m'])*1000):field.setValue(float(value))
        alignment=cfg.get('grasp_alignment','occupied_edges' if definition else 'center')
        self.grasp_alignment.setCurrentIndex(self.grasp_alignment.findData(alignment))
        for field in self.offset_fields[:2]:field.setEnabled(alignment=='center')
        for field,key in ((self.pick_lift,'pick_lift_m'),(self.preplace_height,'preplace_height_m'),(self.preplace_offset,'preplace_side_offset_m')):
            value=motion_options(cfg)[key]*1000;field.setRange(min(1.,value),max(2000.,value));field.setValue(value)
        rotation=np.asarray(cfg['box_T_tcp_rotation']);angles=[math.atan2(rotation[2,1],rotation[2,2]),math.asin(float(np.clip(-rotation[2,0],-1,1))),math.atan2(rotation[1,0],rotation[0,0])]
        for field,value in zip(self.grasp_angles,angles):field.setValue(math.degrees(value))
        options=planning_options(cfg)
        for field,key in ((self.box_budget,'box_budget_seconds'),(self.path_budget,'path_budget_seconds')):
            value=options[key]
            field.setDecimals(min(323,max(1,-Decimal(str(value)).as_tuple().exponent)))
            field.setRange(min(.001,value),max(3600.,value));field.setValue(value)
        self.full_batch.setMaximum(max(10000,options['full_validation_batch_size']))
        self.full_batch.setValue(options['full_validation_batch_size']);self.tiered_check.setChecked(options['tiered_validation'])
        self._syncing=False;self._sync_joints()

    def _robot_changed(self,*args):
        if self._syncing:return
        old=self.state.config.get('robot_id','ec66')
        try:
            candidate=copy.deepcopy(self.state);candidate.select_robot(self.robot_combo.currentData())
            geometry=self._geometry_for_state(candidate);geometry.transforms(candidate.q)
            self.state=candidate;self.geometry=geometry;self.canvas.state=candidate;self.canvas.geometry=geometry;self.canvas._q=None
            self._sync_robot_controls();self._refresh_objects();self.select_entity(self.entity);self.canvas.fit_view();self._changed()
        except Exception as exc:
            blocker=C.QSignalBlocker(self.robot_combo);self.robot_combo.setCurrentIndex(self.robot_combo.findData(old))
            W.QMessageBox.warning(self,'型号切换失败',str(exc))

    def _tool_changed(self,*args):
        if self._syncing or 'tool_definition' not in self.state.config:return
        self.state.config['tool_definition']['size_m']=[f.value()/1000 for f in self.tool_fields]
        self.state.config['tool_definition']['height_source']='provisional_user_adjustable'
        values=self.state.config['tool_definition']['size_m'];self.tool_note.setText(f'吸盘面 {values[0]*1000:g}×{values[1]*1000:g} mm；高度 {values[2]*1000:g} mm 为可调暂定值，尚未现场标定。')
        self.geometry=self._geometry_for_state(self.state);self.canvas.geometry=self.geometry;self.canvas._q=None;self._changed()

    def _refresh_objects(self):
        blocker=C.QSignalBlocker(self.object_combo);self.object_combo.clear()
        for key,title in self.state.entities():self.object_combo.addItem(title,key)

    def _combo_selected(self,*args):
        if self._syncing:return
        key=self.object_combo.currentData()
        if key:self.select_entity(key)

    def select_entity(self,key):
        self.entity=key;self.canvas.selection=key;self._syncing=True
        self.object_combo.setCurrentIndex(self.object_combo.findData(key));pose=self.state.pose(key)
        for field,value in zip(self.position_fields,pose[:3,3]*1000):field.setValue(float(value));field.setEnabled(key!='robot')
        self.yaw_field.setValue(math.degrees(math.atan2(pose[1,0],pose[0,0])));self.yaw_field.setEnabled(key!='robot')
        size=self.state.dimensions if key=='pallet' else self.state.table_size if key=='pickup' else next((o['size'] for o in self.state.obstacles if o['id']==key),[0,0,0])
        for field,value in zip(self.size_fields,np.asarray(size)*1000):field.setValue(float(value));field.setEnabled(key not in ('robot','pallet'))
        self.pose_note.setText({'pallet':'位置基准：装箱底面角点P0。托盘长边为局部X，短边为局部Y；尺寸跟随装箱设置。',
            'pickup':'位置基准：取箱台面中心。Z可以低于机器人基座；下面尺寸为台体长、宽、高。',
            'robot':'参考模型base_link底座原点。FANUC控制器base在其上方670mm，现场坐标需核对。移动托盘/取箱台设置相对位置。' if self.state.config.get('robot_id')=='fanuc_r2000ic210l' else '机械臂基座固定在原点。移动托盘和取箱台，设置它们相对机械臂的位置。'}.get(key,'位置基准：障碍物几何中心。'))
        self._syncing=False;self.canvas.update()

    def _changed(self):self.status.setText('工位已修改 · 尚未验证');self.canvas.update()
    def _canvas_moved(self,key):self.select_entity(key);self._changed()
    def _position_changed(self,*args):
        if not self._syncing:self.state.set_position(self.entity,[f.value()/1000 for f in self.position_fields]);self._changed()
    def _yaw_changed(self,value):
        if not self._syncing:self.state.set_yaw(self.entity,math.radians(value));self._changed()
    def _size_changed(self,*args):
        if self._syncing:return
        size=[f.value()/1000 for f in self.size_fields]
        if self.entity=='pickup':self.state.table_size=np.array(size)
        elif self.entity not in ('pallet','robot'):next(o for o in self.state.obstacles if o['id']==self.entity)['size']=size
        self._changed()
    def _joint_changed(self,index,value):
        if self._syncing:return
        self.state.q[index]=np.clip(math.radians(value),self.geometry.lower[index],self.geometry.upper[index]);self._sync_joints();self._changed()
    def _sync_joints(self):
        self._syncing=True
        for field,slider,value in zip(self.joint_fields,self.joint_sliders,self.state.q):field.setValue(math.degrees(value));slider.setValue(round(math.degrees(value)*100))
        self._syncing=False
    def _sample_changed(self,*args):
        if not self._syncing:self.state.sample=np.array([f.value()/1000 for f in self.sample_fields]);self._changed()
    def _table_changed(self,value):self.state.include_table=value;self._changed()
    def _grasp_changed(self,*args):
        if self._syncing:return
        rotation=np.eye(4);rotation[:3,:3]=rpy_rotation([math.radians(f.value()) for f in self.grasp_angles])
        self.state.config['box_T_tcp_rotation']=rotation.tolist();self.state.config['tcp_offset_from_box_top_m']=[f.value()/1000 for f in self.offset_fields]
        self.state.config['approach_distance_m']=self.approach_distance.value()/1000;self._changed()
    def _alignment_changed(self,*args):
        if self._syncing:return
        alignment=self.grasp_alignment.currentData();self.state.config['grasp_alignment']=alignment
        for field in self.offset_fields[:2]:field.setEnabled(alignment=='center')
        self._changed()
    def _add_obstacle(self):key=self.state.add_obstacle();self._refresh_objects();self.select_entity(key);self._changed()
    def _remove_obstacle(self):
        if self.entity not in ('robot','pallet','pickup'):
            self.state.obstacles=[o for o in self.state.obstacles if o['id']!=self.entity];self._refresh_objects();self.select_entity('pallet');self._changed()

    def save_scene(self,path):return self.state.save(path)
    def save_dialog(self):
        path,_=W.QFileDialog.getSaveFileName(self,'保存工位',str(self.root/'configs/workcell.json'),'JSON (*.json)')
        if path:
            try:self.save_scene(path);self.status.setText('已保存配置 · 尚未验证')
            except Exception as exc:W.QMessageBox.warning(self,'保存失败',str(exc))
    def load_dialog(self):
        path,_=W.QFileDialog.getOpenFileName(self,'载入工位',str(self.root/'configs'),'JSON (*.json)')
        if path:
            try:
                state=WorkcellState.load(self.root,path)
                if not np.allclose(state.dimensions,self.state.dimensions):raise ValueError('工位托盘尺寸与本次装箱尺寸不同，请先核对装箱设置。')
                geometry=self._geometry_for_state(state);geometry.transforms(state.q)
                self.state=state;self.canvas.state=state;self.geometry=geometry;self.canvas.geometry=self.geometry;self.canvas._q=None
                self._syncing=True
                for f,v in zip(self.sample_fields,state.sample*1000):f.setValue(float(v))
                for f,v in zip(self.offset_fields,np.array(state.config['tcp_offset_from_box_top_m'])*1000):f.setValue(float(v))
                rotation=np.asarray(state.config['box_T_tcp_rotation']);angles=[math.atan2(rotation[2,1],rotation[2,2]),math.asin(float(np.clip(-rotation[2,0],-1,1))),math.atan2(rotation[1,0],rotation[0,0])]
                for f,v in zip(self.grasp_angles,angles):f.setValue(math.degrees(v))
                self.approach_distance.setValue(state.config.get('approach_distance_m',.08)*1000);self.include_table.setChecked(state.include_table)
                self._syncing=False;self._refresh_objects();self.select_entity('pallet');self._sync_robot_controls();self.canvas.fit_view();self._changed()
            except Exception as exc:W.QMessageBox.warning(self,'载入失败',str(exc))

    def check_initial_pose(self):
        try:
            from .ec66_model import EC66Model
            cfg=self.state.config
            self.state.validate();robot=EC66Model(cfg['urdf'],cfg['srdf'],tip=cfg.get('tip_link','cup_link'),
                tool_definition=cfg.get('tool_definition'),touch_links=cfg.get('touch_links'))
            length,width,_=self.state.dimensions
            thickness=self.state.config.get('pallet_thickness_m',.04)
            pallet={'id':'pallet','size':[length,width,thickness],'pose':(self.state.pallet_pose@transform((length/2,width/2,-thickness/2))).tolist()}
            source={'id':'preview_box','size':self.state.sample.tolist(),'pose':self.state.source_box_pose().tolist(),
                    'allowed_touch_links':cfg.get('touch_links',['cup_link','link_base'])}
            robot.set_obstacles(self.state.fixed_obstacles()+[pallet,source])
            self.status.setText('初始构型无碰撞 · 整批路径尚未验证' if robot.valid(self.state.q) else '初始构型存在碰撞，请调整关节或工位')
        except Exception as exc:W.QMessageBox.warning(self,'检查失败',str(exc))

    def apply_scene(self):
        try:
            self.geometry.transforms(self.state.q)
            self.applied_path=self.save_scene(self.root/'configs/workcell.json');self.accept()
        except Exception as exc:W.QMessageBox.warning(self,'工位参数错误',str(exc))


def launch_editor(project_dir,dimensions_mm=None,robot_id=None):
    from .robot_runtime import prepare_robot_runtime
    prepare_robot_runtime(project_dir,preload=True)
    app=W.QApplication.instance() or W.QApplication([]);app.setStyle('Fusion')
    project_dir=Path(project_dir);saved=project_dir/'configs/workcell.json';sample=(300,200,200);valid_saved=False;load_error=None
    if saved.exists():
        try:
            state=WorkcellState.load(project_dir,saved);valid_saved=True
            if dimensions_mm is None:dimensions_mm=state.dimensions*1000
            sample=state.sample*1000
        except Exception as exc:load_error=str(exc)
    if dimensions_mm is None:
        import json
        results=sorted((project_dir/'output/robot2025_results').rglob('*plan.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        for path in results[:1]:
            try:
                data=json.loads(path.read_text(encoding='utf-8'));dims=data['pallet']
                dimensions_mm=[dims['length'],dims['width'],dims['height']]
            except (OSError,ValueError,KeyError):pass
    editor=WorkcellEditor(project_dir,dimensions_mm if dimensions_mm is not None else (1200,800,1400),sample,
                          saved if valid_saved else None)
    if robot_id is not None:editor.robot_combo.setCurrentIndex(editor.robot_combo.findData(robot_id))
    if not valid_saved:editor.arrange_preset()
    if load_error:editor.status.setText('旧配置不可读，已打开新布局；原文件保留。')
    app.setQuitOnLastWindowClosed(False);windows=[editor]
    def finished(result):
        if result==W.QDialog.Accepted:
            from .qt_workbench_2025 import RobotWorkbench
            window=RobotWorkbench(project_dir);window.dimensions=[str(float(v)*1000) for v in editor.state.dimensions]
            windows.append(window);window.showMaximized();app.setQuitOnLastWindowClosed(True)
        else:app.quit()
    editor.finished.connect(finished);editor.show()
    return app.exec_()
