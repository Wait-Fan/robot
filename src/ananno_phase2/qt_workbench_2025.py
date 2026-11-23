"""独立2025桌面入口；复用2024工作台布局和异步运行服务。"""
import json
import sys
from PyQt5 import QtCore as C,QtWidgets as W

from .qt_workbench import PackingWorkbench,button,label
from .robot_approach import ApproachConfig


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

    def __init__(self,project_dir=None):
        self.approach_direction='+Z'
        super().__init__(project_dir)
        self.setWindowTitle('Ananno 2025 · PyQt5版 v0.1.0 · 开放方向约束研究实现')
        self.findChild(W.QLabel,'brand').setText('Ananno 2025 装箱与开放方向约束')
        self.findChild(W.QLabel,'subtitle').setText('继承2024基线 · 轻量接近模型 · 可追溯研究实现 v0.1.0')
        self.output_dir=self.project_dir/'output/robot2025_results'
        self.mode_combo.insertItem(0,'2025 可达性');self.mode_combo.setCurrentText('2025 可达性')
        for widget in self.findChildren(W.QLabel):
            if '当前不计算机械臂可达性或吸盘碰撞' in widget.text():
                widget.setText('2025模式在勾选的开放侧中逐箱选择接近方向，检查箱体遮挡。界面尚未启用机械臂IK和完整关节轨迹；详见“算法 / 约束记录”。')
        self.refresh_history()
        self._log('独立2025工程：支持勾选多个开放侧，逐箱选择可行方向；界面尚未启用机械臂IK和关节轨迹验证。')

    def _job_options(self):
        if self.mode_combo.currentText()=='2025 可达性':
            return {'algorithm':'robot2025','paper_config':self._paper_config(self.paper_parameters),
                    'approach_config':ApproachConfig(open_directions=self.approach_directions)}
        return super()._job_options()

    def _mode_changed(self,*args):
        super()._mode_changed(*args)
        if hasattr(self,'method_note') and self.mode_combo.currentText()=='2025 可达性':
            self.method_note.setText(f'2025轻量开放方向模型\n允许来向 {"、".join(self.approach_directions)}\n逐箱选侧；IK/完整关节轨迹未验证。')

    def _result_identity(self):
        super()._result_identity()
        selected=self.mode_combo.currentText()
        audit=(self.document or {}).get('robot_diagnostics')
        if isinstance(audit,dict):
            loaded='2025 可达性'
            status='开放方向检查通过' if audit.get('passed') else '开放方向检查未通过'
            loaded_directions=audit.get('open_directions') or [audit.get('open_direction')]
            self.result_summary.setText(f"结果：2025轻量模型\n允许来向 {'、'.join(str(d) for d in loaded_directions)} · {status}\n机械臂IK/关节轨迹未验证。")
        else:loaded='论文两阶段' if (self.document or {}).get('paper_diagnostics') else '基础模式' if self.document else '尚无结果'
        mismatch=' ｜ 模式不同，需重新计算' if self.document is not None and selected!=loaded else ''
        if selected==loaded=='2025 可达性' and set(loaded_directions)!=set(self.approach_directions):
            mismatch=' ｜ 来向已改，需重新计算'
        if selected=='2025 可达性':selected+=f'（来向{"、".join(self.approach_directions)}）'
        self.mode_banner.setText(f'2025版 v0.1.0  当前计算：{selected} ｜ 当前结果：{loaded}{mismatch}')

    def show_settings(self):
        dialog=W.QDialog(self);dialog.setWindowTitle('2025放置策略 / 装箱设置')
        layout=W.QVBoxLayout(dialog)
        layout.addWidget(label('勾选允许接近的开放侧，每箱从中选择可行方向。至少勾选一项。',wrap=True))
        boxes={};group=W.QGroupBox('允许的接近方向');options=W.QVBoxLayout(group)
        for direction,title in [('+Z','+Z：上方接近（从上向下）'),('+X','+X：X正侧接近'),('-X','-X：X负侧接近'),('+Y','+Y：Y正侧接近'),('-Y','-Y：Y负侧接近')]:
            checkbox=W.QCheckBox(title);checkbox.setProperty('direction',direction)
            checkbox.setChecked(direction in self.approach_directions);options.addWidget(checkbox);boxes[direction]=checkbox
        layout.addWidget(group)
        layout.addWidget(button('托盘尺寸、算法参数与输出目录…',lambda:super(RobotWorkbench,self).show_settings()))
        layout.addWidget(label('采用刚性箱体直线接近模型；机械臂、夹具、臂展和完整搬运轨迹未建模。',wrap=True))
        controls=W.QDialogButtonBox(W.QDialogButtonBox.Ok|W.QDialogButtonBox.Cancel)
        def validate_selection():
            controls.button(W.QDialogButtonBox.Ok).setEnabled(any(b.isChecked() for b in boxes.values()))
        for checkbox in boxes.values():checkbox.toggled.connect(validate_selection)
        validate_selection()
        controls.accepted.connect(dialog.accept);controls.rejected.connect(dialog.reject);layout.addWidget(controls)
        if dialog.exec_()==W.QDialog.Accepted:
            self.approach_directions=tuple(d for d,b in boxes.items() if b.isChecked());self._mode_changed()
            self._log('允许的开放方向设置为 '+'、'.join(self.approach_directions))

    def display_document(self,document,path=None):
        super().display_document(document,path)
        if document.get('robot_diagnostics'):
            self.audit_box.setPlainText(json.dumps({'robot_diagnostics':document['robot_diagnostics'],
                'provenance':document.get('provenance'),'paper_diagnostics':document.get('paper_diagnostics')},ensure_ascii=False,indent=2))


def launch_workbench():
    app=W.QApplication.instance()
    if app is None:
        C.QCoreApplication.setAttribute(C.Qt.AA_EnableHighDpiScaling,True)
        C.QCoreApplication.setAttribute(C.Qt.AA_UseHighDpiPixmaps,True)
        app=W.QApplication(sys.argv[:1])
    app.setStyle('Fusion');window=RobotWorkbench();window.showMaximized()
    return app.exec_()
