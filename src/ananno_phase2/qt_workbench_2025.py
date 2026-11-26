"""独立2025桌面入口；复用2024工作台布局和异步运行服务。"""
import json
import sys
import hashlib
from pathlib import Path
from .robot_runtime import prepare_robot_runtime

# On Windows the bundled MuJoCo plugin DLLs must load before Qt DLLs,
# not merely before QApplication is created.
_robot_runtime_error = None
try:prepare_robot_runtime(Path(__file__).resolve().parents[2],preload=True)
except (ImportError,RuntimeError,OSError) as exc:_robot_runtime_error = str(exc)

from PyQt5 import QtCore as C,QtWidgets as W

from .qt_workbench import PackingWorkbench,button,label
from .robot_approach import ApproachConfig,outside_side_from_workcell
from .models import Pallet


class RobotWorkbench(PackingWorkbench):
    @property
    def approach_directions(self):
        return self._approach_directions

    @approach_directions.setter
    def approach_directions(self,values):
        self._approach_directions=ApproachConfig(open_directions=values).open_directions

    @property
    def approach_direction(self):
        return self.approach_directions[0]

    @approach_direction.setter
    def approach_direction(self,value):
        self.approach_directions=(value,)

    def __init__(self,project_dir=None,*,restore_workcell=True):
        self.approach_direction='+Z'
        self.outside_mode='auto'
        self.direction_policy='preplace_optimized'
        self.initial_result_first=True
        self.robot_scene_path=None;self.robot_name='未配置机械臂'
        super().__init__(project_dir)
        self.setWindowTitle('Ananno 2025 · PyQt5版 v0.1.0 · 开放方向约束研究实现')
        self.findChild(W.QLabel,'brand').setText('Ananno 2025 装箱与开放方向约束')
        self.findChild(W.QLabel,'subtitle').setText('继承2024基线 · 轻量接近模型 · 可追溯研究实现 v0.1.0')
        self.output_dir=self.project_dir/'output/robot2025_results'
        self.mode_combo.insertItem(0,'2025 可达性');self.mode_combo.setCurrentText('2025 可达性')
        toolbar=self.settings_button.parentWidget().layout()
        self.workcell_button=button('工位布局',self.show_workcell,'darkButton')
        toolbar.insertWidget(toolbar.indexOf(self.settings_button)+1,self.workcell_button)
        self.robot_check=W.QCheckBox('机器人完整校验');self.robot_check.setEnabled(False)
        self.robot_check.toggled.connect(self._mode_changed)
        toolbar.insertWidget(toolbar.indexOf(self.workcell_button)+1,self.robot_check)
        self.robot_check.setToolTip('先在工位布局中摆放机械臂、托盘、取箱台并应用，再启用完整IK和路径检查。')
        for widget in self.findChildren(W.QLabel):
            if '当前不计算机械臂可达性或吸盘碰撞' in widget.text():
                widget.setText('开放侧指定预放置点的来向；配置“工位布局”并勾选机器人完整校验，检查IK、携箱碰撞、搬运及下降放置路径。')
        self.refresh_history()
        self._log('默认：抓取后短抬升 → 避障搬运到较高的预放置点 → 下降或斜下降；未启用完整校验时只生成几何候选。')
        if _robot_runtime_error:self._log('机器人运行库初始化失败：'+_robot_runtime_error)
        saved=self.project_dir/'configs/workcell.json'
        if restore_workcell and saved.exists():
            try:self.apply_workcell(saved)
            except Exception as exc:
                self.robot_scene_path=None;self.robot_check.setChecked(False);self.robot_check.setEnabled(False)
                self._log('上次工位无法载入，已保留原文件并关闭完整校验。请打开工位布局重新配置：'+str(exc))

    def _busy(self,busy):
        super()._busy(busy)
        if hasattr(self,'workcell_button'):
            self.workcell_button.setEnabled(not busy)
            self.robot_check.setEnabled(not busy and self.robot_scene_path is not None and self.mode_combo.currentText()=='2025 可达性')

    def apply_workcell(self,path):
        path=Path(path).resolve();config=json.loads(path.read_text(encoding='utf-8-sig'))
        if config.get('pallet_frame_convention')!='long_side_x':raise ValueError('可视工位需要使用长边X坐标')
        from .robot_runtime import prepare_robot_runtime
        prepare_robot_runtime(self.project_dir,preload=True)
        from .workcell_state import WorkcellState
        WorkcellState.load(self.project_dir,path)
        self.robot_scene_path=path;self.robot_name=config.get('robot_name','EC66');self.robot_check.setEnabled(True);self.robot_check.setChecked(True)
        self._mode_changed();self._log('已应用工位并启用'+self.robot_name+'完整校验：'+str(path))

    def show_workcell(self):
        try:
            from .robot_runtime import prepare_robot_runtime
            prepare_robot_runtime(self.project_dir,preload=True)
            from .workcell_editor import WorkcellEditor
            sample=(300,200,200)
            if self.input_path is not None:
                if self.input_path.suffix.lower()=='.json':
                    from .io import read_packing_json
                    boxes=read_packing_json(self.input_path)[1]
                elif self.input_path.suffix.lower()=='.xlsx':
                    from .xlsx_input import read_boxes_xlsx
                    boxes=read_boxes_xlsx(self.input_path)[1]
                elif self.input_info and self.input_info['kind']=='paper':
                    from .io import read_order_dataset
                    boxes=read_order_dataset(self.input_path,self.order_combo.currentText())
                else:
                    from .io import read_boxes_csv
                    boxes=read_boxes_csv(self.input_path)
                if boxes:sample=(boxes[0].length,boxes[0].width,boxes[0].height)
            editor=WorkcellEditor(self.project_dir,tuple(map(float,self.dimensions)),sample,self.robot_scene_path,self)
            if editor.exec_()==W.QDialog.Accepted:self.apply_workcell(editor.applied_path)
        except Exception as exc:W.QMessageBox.warning(self,'工位界面无法打开',str(exc))

    def _outside_side(self,*,strict=False):
        if self.outside_mode!='auto':return self.outside_mode
        if self.robot_scene_path is None:return None
        try:
            config=json.loads(self.robot_scene_path.read_text(encoding='utf-8-sig'))
            if config.get('pallet_frame_convention')!='long_side_x':raise ValueError('自动里外基准需要长边X工位坐标')
            return outside_side_from_workcell(Pallet(*map(float,self.dimensions)).with_long_side_x(),config['base_T_pallet'],length_scale_to_m=config['length_scale_to_m'])
        except (OSError,KeyError,TypeError,ValueError) as exc:
            if strict:raise ValueError('无法确定里外基准，请重新应用工位或手动指定外侧：'+str(exc)) from exc
            return None

    def _fill_description(self):
        side=self._outside_side()
        return ('跨层先里后外，外侧 '+side+('（工位自动）' if self.outside_mode=='auto' else '（手动）')) if side else '里外基准待配置工位，或手动指定外侧'

    def _job_options(self):
        if self.mode_combo.currentText()=='2025 可达性':
            options={'algorithm':'robot2025','robot_seal_verified_pallets':self.initial_result_first,'paper_config':self._paper_config(self.paper_parameters),'max_seconds':self.max_job_minutes*60,
                    'approach_config':ApproachConfig(open_directions=self.approach_directions,outside_side=self._outside_side(strict=True),direction_policy=self.direction_policy)}
            if options['approach_config'].outside_side is None:self._log('尚无法自动判断里外：请在工位布局中应用位置，或在设置中手动指定外侧；本次保留原可行顺序。')
            if self.robot_check.isChecked():
                if self.robot_scene_path is None:raise ValueError('请先配置并应用工位')
                if options['approach_config'].outside_side is None:raise ValueError('当前工位无法唯一确定里外基准，请在装箱设置中手动选择外侧后计算。')
                try:scene_hash=hashlib.sha256(self.robot_scene_path.read_bytes()).hexdigest()
                except OSError as exc:raise ValueError('工位文件无法读取，请打开工位布局重新应用。') from exc
                options.update(robot_scene_path=self.robot_scene_path,robot_scene_sha256=scene_hash)
            return options
        return super()._job_options()

    def _mode_changed(self,*args):
        super()._mode_changed(*args)
        if hasattr(self,'method_note') and self.mode_combo.currentText()=='2025 可达性':
            full=hasattr(self,'robot_check') and self.robot_check.isChecked()
            self.method_note.setText(f'2025 {self.robot_name+"完整离线检查" if full else "几何开放侧筛选"}\n允许来向 {"、".join(self.approach_directions)}\n'+('将检查IK、携箱碰撞和完整抓放路径；实机未验证。' if full else '未启用机械臂IK和关节轨迹验证。'))
            self.method_note.setText(self.method_note.text()+'\n'+self._fill_description()+'\n短抬升 → 避障搬运 → 预放置 → 下降/斜下降\n比较完整可行候选的预计运动时间')
        if hasattr(self,'robot_check'):self.robot_check.setEnabled(self.robot_scene_path is not None and self.mode_combo.currentText()=='2025 可达性' and not self.running)

    def _result_identity(self):
        super()._result_identity()
        selected=self.mode_combo.currentText()
        audit=(self.document or {}).get('robot_diagnostics')
        if isinstance(audit,dict):
            loaded='2025 可达性'
            status='开放方向检查通过' if audit.get('passed') else '开放方向检查未通过'
            loaded_directions=audit.get('open_directions') or [audit.get('open_direction')]
            full=audit.get('ik_verified') and audit.get('joint_trajectory_verified')
            model_name=audit.get('robot_name') or audit.get('motion_verification',{}).get('robot_name','EC66')
            self.result_summary.setText(f"结果：2025 {model_name+'离线模型' if full else '几何筛选'}\n允许来向 {'、'.join(str(d) for d in loaded_directions)} · {status}\n"+('IK/操作路径已验证；工具/工位未实机标定。' if full else '机械臂IK/关节轨迹未验证。'))
        else:loaded='论文两阶段' if (self.document or {}).get('paper_diagnostics') else '基础模式' if self.document else '尚无结果'
        mismatch=' ｜ 模式不同，需重新计算' if self.document is not None and selected!=loaded else ''
        if selected==loaded=='2025 可达性' and set(loaded_directions)!=set(self.approach_directions):
            mismatch=' ｜ 来向已改，需重新计算'
        if selected==loaded=='2025 可达性' and hasattr(self,'robot_check'):
            if bool(full)!=self.robot_check.isChecked():mismatch+=' ｜ 校验方式不同，需重新计算'
            elif full and self.robot_scene_path is not None:
                try:current_hash=hashlib.sha256(self.robot_scene_path.read_bytes()).hexdigest()
                except OSError:current_hash=None
                if audit.get('scene_source_sha256')!=current_hash:mismatch+=' ｜ 工位不同或待确认，需重新计算'
        if selected==loaded=='2025 可达性':
            if audit.get('direction_selection_policy','first_feasible')!=self.direction_policy:mismatch+=' ｜ 接近策略已改，需重新计算'
            records=audit.get('motion_verification',{}).get('directions_by_box',[]) if full else audit.get('checks',[])
            sides=sum(c.get('open_direction') in ('+X','-X','+Y','-Y') for c in records)
            tops=sum(c.get('open_direction')=='+Z' for c in records)
            direct=sum(c.get('transfer_mode')=='cartesian_direct' for c in records)
            self.result_summary.setText(self.result_summary.text()+f'\n{"已验证" if full else "几何候选"}：侧向 {sides} 箱，上方 {tops} 箱'+(f'，侧向直线 {direct} 箱' if full else ''))
            policy=audit.get('sequencing_policy',{})
            if policy.get('outside_side')!=self._outside_side():mismatch+=' ｜ 里外基准已改，需重新计算'
            side=policy.get('outside_side')
            if side and policy.get('name')!='whole_pallet_depth_frontier':mismatch+=' ｜ 旧版同层顺序，需重新计算'
            order_note=('\n旧结果采用备用顺序' if policy.get('fallback_used') else '\n跨层先里后外，外侧 '+side if side and policy.get('name')=='whole_pallet_depth_frontier' else '\n旧版同层先里后外，外侧 '+side if side else '\n未应用里外优先规则')
            self.result_summary.setText(self.result_summary.text()+order_note)
        if selected=='2025 可达性':selected+=f'（来向{"、".join(self.approach_directions)}）'
        self.mode_banner.setText(f'2025版 v0.1.0  当前计算：{selected} ｜ 当前结果：{loaded}{mismatch}')

    def show_settings(self):
        dialog=W.QDialog(self);dialog.setWindowTitle('2025放置策略 / 装箱设置');dialog.setMinimumSize(600,720);dialog.resize(640,760)
        layout=W.QVBoxLayout(dialog)
        layout.addWidget(label('X沿托盘长边，Y沿短边，Z向上。勾选允许接近的开放侧，每箱选择可行方向；至少选一项。',wrap=True))
        boxes={};group=W.QGroupBox('允许的接近方向');group.setMinimumHeight(190);options=W.QVBoxLayout(group)
        for direction,title in [('+Z','+Z：上方接近（从上向下）'),('+X','+X：沿长边，从X正端接近'),('-X','-X：沿长边，从X负端接近'),('+Y','+Y：沿短边，从Y正端接近'),('-Y','-Y：沿短边，从Y负端接近')]:
            checkbox=W.QCheckBox(title);checkbox.setMinimumHeight(26);checkbox.setProperty('direction',direction)
            checkbox.setChecked(direction in self.approach_directions);options.addWidget(checkbox);boxes[direction]=checkbox
        layout.addWidget(group)
        layout.addWidget(label('接近策略：X/Y是在较高预放置点的短距离偏移，最后斜下降；+Z为正上方下降。搬运由避障规划器选择路径，比较预算内完整可行候选的预计时间。',wrap=True))
        fill=W.QGroupBox('装箱顺序约束（独立于允许接近方向）');form=W.QFormLayout(fill)
        outside=W.QComboBox();outside.setObjectName('outsideSideSelector')
        for title,value in [('自动：按工位机械臂所在侧','auto'),('外侧 -X：由+X远侧向-X装','-X'),('外侧 +X：由-X远侧向+X装','+X'),('外侧 -Y：由+Y远侧向-Y装','-Y'),('外侧 +Y：由-Y远侧向+Y装','+Y')]:outside.addItem(title,value)
        outside.setCurrentIndex(outside.findData(self.outside_mode));form.addRow('里外基准',outside)
        form.addRow(label('跨层约束：完整远侧深度区先于近侧区，同时满足下层支撑。两者冲突就淘汰垛型，不放宽成先外后里；深度重叠的跨区大箱优先满足支撑。',wrap=True))
        layout.addWidget(fill)
        first_result=W.QCheckBox('初步结果优先：已验证托盘封盘，余箱开新盘（可能增加盘数）')
        first_result.setObjectName('initialResultFirst');first_result.setChecked(self.initial_result_first);layout.addWidget(first_result)
        layout.addWidget(button('托盘尺寸、算法参数与输出目录…',lambda:super(RobotWorkbench,self).show_settings()))
        layout.addWidget(label('预放置方向仅为候选，真实可执行性须完整检查IK、工具/携箱碰撞与平滑后的路径。抬升距离和预放置高度可在工位布局中调整。',wrap=True))
        controls=W.QDialogButtonBox(W.QDialogButtonBox.Ok|W.QDialogButtonBox.Cancel)
        def validate_selection():
            controls.button(W.QDialogButtonBox.Ok).setEnabled(any(b.isChecked() for b in boxes.values()))
        for checkbox in boxes.values():checkbox.toggled.connect(validate_selection)
        validate_selection()
        controls.accepted.connect(dialog.accept);controls.rejected.connect(dialog.reject);layout.addWidget(controls)
        if dialog.exec_()==W.QDialog.Accepted:
            self.outside_mode=outside.currentData()
            self.initial_result_first=first_result.isChecked()
            self.approach_directions=tuple(d for d,b in boxes.items() if b.isChecked());self._mode_changed()
            self._log('装箱顺序：'+self._fill_description())
            self._log('允许的开放方向设置为 '+'、'.join(self.approach_directions))

    def display_document(self,document,path=None):
        super().display_document(document,path)
        if document.get('robot_diagnostics'):
            self.audit_box.setPlainText(json.dumps({'robot_diagnostics':document['robot_diagnostics'],
                'provenance':document.get('provenance'),'paper_diagnostics':document.get('paper_diagnostics')},ensure_ascii=False,indent=2))


def launch_workbench():
    from .robot_runtime import prepare_robot_runtime
    try:prepare_robot_runtime(Path(__file__).resolve().parents[2],preload=True)
    except (ImportError,RuntimeError,OSError):pass
    app=W.QApplication.instance()
    if app is None:
        C.QCoreApplication.setAttribute(C.Qt.AA_EnableHighDpiScaling,True)
        C.QCoreApplication.setAttribute(C.Qt.AA_UseHighDpiPixmaps,True)
        app=W.QApplication(sys.argv[:1])
    app.setStyle('Fusion');window=RobotWorkbench();window.showMaximized()
    return app.exec_()
