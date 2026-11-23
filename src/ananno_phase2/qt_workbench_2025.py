"""独立2025桌面入口；复用2024工作台布局和异步运行服务。"""
import json
import sys
from PyQt5 import QtCore as C,QtWidgets as W

from .qt_workbench import PackingWorkbench,button,label
from .robot_approach import ApproachConfig


class RobotWorkbench(PackingWorkbench):
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
                widget.setText('2025模式检查固定来向的箱体遮挡。机械臂本体、夹具、IK和完整关节轨迹未验证；详见“算法 / 约束记录”。')
        self.refresh_history()
        self._log('独立2025工程：固定开放方向接近模型；IK、关节轨迹、RobotStudio尚未验证。')

    def _job_options(self):
        if self.mode_combo.currentText()=='2025 可达性':
            return {'algorithm':'robot2025','paper_config':self._paper_config(self.paper_parameters),
                    'approach_config':ApproachConfig(self.approach_direction)}
        return super()._job_options()

    def _mode_changed(self,*args):
        super()._mode_changed(*args)
        if hasattr(self,'method_note') and self.mode_combo.currentText()=='2025 可达性':
            self.method_note.setText(f'2025轻量开放方向模型\n固定来向 {self.approach_direction}\nIK/完整关节轨迹未验证。')

    def _result_identity(self):
        super()._result_identity()
        selected=self.mode_combo.currentText()
        audit=(self.document or {}).get('robot_diagnostics')
        if isinstance(audit,dict):
            loaded='2025 可达性'
            status='开放方向检查通过' if audit.get('passed') else '开放方向检查未通过'
            self.result_summary.setText(f"结果：2025轻量模型\n来向 {audit.get('open_direction')} · {status}\n机械臂IK/关节轨迹未验证。")
        else:loaded='论文两阶段' if (self.document or {}).get('paper_diagnostics') else '基础模式' if self.document else '尚无结果'
        mismatch=' ｜ 模式不同，需重新计算' if self.document is not None and selected!=loaded else ''
        if selected==loaded=='2025 可达性' and audit.get('open_direction')!=self.approach_direction:
            mismatch=' ｜ 来向已改，需重新计算'
        if selected=='2025 可达性':selected+=f'（来向{self.approach_direction}）'
        self.mode_banner.setText(f'2025版 v0.1.0  当前计算：{selected} ｜ 当前结果：{loaded}{mismatch}')

    def show_settings(self):
        dialog=W.QDialog(self);dialog.setWindowTitle('2025放置策略 / 装箱设置')
        layout=W.QVBoxLayout(dialog)
        layout.addWidget(label('开放方向表示从哪一侧向目标接近：+Z为从上向下，-X为从X负侧接近。',wrap=True))
        combo=W.QComboBox();combo.addItems(['+Z','+X','-X','+Y','-Y']);combo.setCurrentText(self.approach_direction)
        layout.addWidget(combo)
        layout.addWidget(button('托盘尺寸、算法参数与输出目录…',lambda:super(RobotWorkbench,self).show_settings()))
        layout.addWidget(label('采用刚性箱体直线接近模型；机械臂、夹具、臂展和完整搬运轨迹未建模。',wrap=True))
        controls=W.QDialogButtonBox(W.QDialogButtonBox.Ok|W.QDialogButtonBox.Cancel)
        controls.accepted.connect(dialog.accept);controls.rejected.connect(dialog.reject);layout.addWidget(controls)
        if dialog.exec_()==W.QDialog.Accepted:
            self.approach_direction=combo.currentText();self._mode_changed()
            self._log('固定开放方向设置为 '+self.approach_direction)

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
