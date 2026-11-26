"""PyQt5桌面工作台：本地文件输入，复用现有算法与导出服务。"""
from __future__ import annotations

import csv
import gc
import json
import math
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from PyQt5 import QtCore as C,QtGui as G,QtWidgets as W

from .paper_config import PaperConfig
from .run_control import PackingTimedOut
from .models import Pallet
from .qt_widgets import MetricCard,PalletCanvas,PalletCard,WORKBENCH_STYLE,HistoryItemDelegate
from .workbench_service import PackingCancelled,finite_number,inspect_input,load_result,run_packing_job

APP_VERSION="0.4.1"


def button(text,callback,name=""):
    widget=W.QPushButton(text)
    widget.clicked.connect(callback)
    if name: widget.setObjectName(name)
    return widget


def label(text="",*,wrap=False,name=""):
    widget=W.QLabel(text)
    widget.setWordWrap(wrap)
    if name: widget.setObjectName(name)
    return widget


def panel(title=""):
    frame=W.QFrame()
    frame.setObjectName("panel")
    layout=W.QVBoxLayout(frame)
    layout.setContentsMargins(12,10,12,10)
    layout.setSpacing(7)
    if title: layout.addWidget(label(title,name="sectionTitle"))
    return frame,layout


def scroll(content):
    area=W.QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(W.QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(C.Qt.ScrollBarAlwaysOff)
    area.setWidget(content)
    return area


class PackingWorker(C.QObject):
    progress=C.pyqtSignal(int,int)
    log=C.pyqtSignal(str)
    result=C.pyqtSignal(object)
    stopped=C.pyqtSignal()
    expired=C.pyqtSignal(str)
    failed=C.pyqtSignal(str)
    finished=C.pyqtSignal()

    def __init__(self,args,options,cancel_event):
        super().__init__()
        self.args,self.options,self.cancel_event=args,options,cancel_event
        self.completed=threading.Event()

    @C.pyqtSlot()
    def run(self):
        try:
            result=run_packing_job(*self.args,**self.options,cancelled=self.cancel_event.is_set,
                                   progress=self.progress.emit,log=self.log.emit)
        except PackingTimedOut as exc:
            self.expired.emit(str(exc))
        except PackingCancelled:
            self.stopped.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.completed.set()
            self.result.emit(result)
        finally:
            self.finished.emit()


class PackingWorkbench(W.QMainWindow):
    def __init__(self,project_dir=None):
        super().__init__()
        self.project_dir=Path(project_dir or Path(__file__).resolve().parents[2])
        self.input_path=self.input_info=self.document=self.result_path=None
        self.dimensions=["1200","800","1400"]
        self.support="1.0"
        self.max_job_minutes=60.
        self.paper_parameters={"pallet_weight":"25","com_deviation_fraction":"0.25",
                               "corner_inset_fraction":"0.01","seed":"42"}
        self.output_dir=self.project_dir/"output"
        self._thread=self._worker=None
        self.cancel_event=threading.Event()
        self._close_pending=False
        self._selected_index=None
        self._applied_search=""
        self._history_paths={}
        self.page=self.step=0
        self.overview_cards=[]
        self._motion_windows={}
        self._view_revision=0;self._job_start_view_revision=0;self._pending_result_path=None
        self.log_lines=[]
        self.table_rows=[]
        self.setWindowTitle(f"Ananno 2024 · PyQt5版 v{APP_VERSION} · 三维装箱工作台")
        self.resize(1600,960)
        self.setMinimumSize(1100,680)
        self.setFont(G.QFont("Microsoft YaHei UI",9))
        self.setStyleSheet(WORKBENCH_STYLE+"""
            QFrame#header {background:#111827;border:0;border-radius:0;}
            QFrame#toolbar {background:#1b2637;border:1px solid #344155;border-radius:9px;}
            QLabel#brand {color:white;font-size:23px;font-weight:700;}
            QLabel#subtitle {color:#94a3b8;font-size:11px;}
            QLabel#modeBanner {background:#172554;color:#bfdbfe;padding:6px 10px;border-radius:6px;}
            QLabel#statusBadge {background:#dcfce7;color:#166534;padding:8px 18px;border-radius:17px;font-weight:700;}
            QLabel#statusBadge[statusTone="idle"] {background:#263244;color:#cbd5e1;}
            QLabel#statusBadge[statusTone="busy"] {background:#2563eb;color:white;}
            QLabel#statusBadge[statusTone="error"] {background:#fee2e2;color:#991b1b;}
            QLabel#statusBadge[statusTone="stopped"] {background:#fef3c7;color:#92400e;}
            QLabel#sectionTitle {color:#991b1b;font-weight:700;}
            QLabel#currentTitle {font-size:26px;font-weight:700;color:#111827;}
            QLabel#muted {color:#64748b;font-size:11px;}
            QFrame#panel {background:white;border:1px solid #e1e7ef;border-radius:10px;}
            QFrame#panel QLabel {border:0;background:transparent;}
            QPushButton#primaryButton {background:#2563eb;color:white;border:1px solid #2563eb;font-weight:600;}
            QPushButton#primaryButton:hover {background:#1d4ed8;}
            QPushButton#dangerButton {background:#dc2626;color:white;border:1px solid #dc2626;}
            QPushButton:disabled {color:#94a3b8;background:#e2e8f0;border-color:#e2e8f0;}
            QPushButton#dangerButton:disabled, QPushButton#primaryButton:disabled {
                color:#738399;background:#263244;border-color:#3a4a60;}
            QFrame#toolbar QLabel {color:#94a3b8;background:transparent;}
            QFrame#toolbar QComboBox {background:#111827;color:#dbeafe;border:1px solid #475569;}
            QFrame#header QPushButton#darkButton {background:#263244;color:#e2e8f0;border:1px solid #475569;}
            QTextEdit#logBox {background:#172235;color:#dbeafe;font-family:Consolas;border-radius:8px;}
        """)
        self.play_timer=C.QTimer(self)
        self.play_timer.timeout.connect(self.next_step)
        self._build()
        self._mode_changed()
        self.refresh_history()
        self.refresh_overview()
        self._log(f"PyQt5工作台 v{APP_VERSION} 已就绪。论文模式使用DEAP；本地计算不需要数据库。")

    @property
    def running(self): return self._thread is not None

    def _build(self):
        base=W.QWidget()
        self.setCentralWidget(base)
        outer=W.QVBoxLayout(base)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        splitter=W.QSplitter(C.Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(5)
        self.left_panel=self._build_left()
        self.tabs=W.QTabWidget()
        self._build_center()
        self.right_panel=self._build_right()
        splitter.addWidget(scroll(self.left_panel))
        splitter.addWidget(self.tabs)
        splitter.addWidget(scroll(self.right_panel))
        splitter.widget(0).setMinimumWidth(235)
        splitter.widget(2).setMinimumWidth(235)
        splitter.setStretchFactor(0,0)
        splitter.setStretchFactor(1,1)
        splitter.setStretchFactor(2,0)
        splitter.setSizes([280,1000,285])
        outer.addWidget(splitter,1)
        self._build_log(outer)

    def _build_header(self):
        header=W.QFrame();header.setObjectName("header")
        layout=W.QVBoxLayout(header)
        layout.setContentsMargins(18,14,18,10)
        layout.setSpacing(10)
        top=W.QHBoxLayout()
        brand=W.QVBoxLayout()
        brand.addWidget(label("Ananno 2024 智能装箱规划系统",name="brand"))
        brand.addWidget(label(f"PyQt5 桌面版 v{APP_VERSION}  ·  两阶段研究实现  ·  三维回放",name="subtitle"))
        top.addLayout(brand,1)
        self.status_label=label("空闲",name="statusBadge")
        self.status_label.setProperty("statusTone","idle")
        self.status_label.setFixedHeight(36)
        self.status_label.setAlignment(C.Qt.AlignCenter)
        self.input_button=button("选择文件",self.choose_input,"darkButton")
        self.start_button=button("一键装箱",self.start_packing,"primaryButton")
        self.stop_button=button("停止",self.stop_packing,"dangerButton")
        self.stop_button.setEnabled(False)
        for widget in (self.status_label,self.input_button,self.start_button,self.stop_button):top.addWidget(widget)
        layout.addLayout(top)
        toolbar=W.QFrame();toolbar.setObjectName("toolbar")
        row=W.QHBoxLayout(toolbar);row.setContentsMargins(10,7,10,7);row.setSpacing(8)
        row.addWidget(label("范围"))
        self.order_combo=W.QComboBox();self.order_combo.setMinimumWidth(105);self.order_combo.setEnabled(False)
        self.order_combo.currentTextChanged.connect(self._input_summary)
        row.addWidget(self.order_combo)
        row.addWidget(label("算法"))
        self.mode_combo=W.QComboBox();self.mode_combo.addItems(["论文两阶段","基础模式"])
        self.mode_combo.currentTextChanged.connect(self._mode_changed)
        row.addWidget(self.mode_combo)
        self.settings_button=button("装箱设置",self.show_settings,"darkButton")
        self.open_button=button("打开结果",self.choose_result,"darkButton")
        row.addWidget(self.settings_button);row.addWidget(self.open_button)
        row.addWidget(label("历史结果"))
        self.history=W.QComboBox();self.history.setObjectName('historyCombo');self.history.setMinimumWidth(120)
        self.history.setItemDelegate(HistoryItemDelegate(self.history))
        history_view=self.history.view()
        history_view.setMinimumWidth(620)
        history_view.setStyleSheet('QAbstractItemView {background:#ffffff;color:#1f2937;selection-background-color:#2563eb;selection-color:#ffffff;font-size:12px;border:1px solid #64748b;} QAbstractItemView::item {min-height:28px;padding:3px 8px;} QAbstractItemView::item:selected {background:#2563eb;color:#ffffff;}')
        palette=history_view.palette();palette.setColor(G.QPalette.Text,G.QColor('#1f2937'));palette.setColor(G.QPalette.Base,G.QColor('#ffffff'))
        palette.setColor(G.QPalette.Highlight,G.QColor('#2563eb'));palette.setColor(G.QPalette.HighlightedText,G.QColor('#ffffff'));history_view.setPalette(palette)
        self.history.setMaxVisibleItems(12)
        self.history.setSizePolicy(W.QSizePolicy.Ignored,W.QSizePolicy.Fixed)
        self.history.activated.connect(self._open_history)
        row.addWidget(self.history,1)
        layout.addWidget(toolbar)
        self.mode_banner=label("",wrap=True,name="modeBanner")
        layout.addWidget(self.mode_banner)
        return header

    def _build_left(self):
        widget=W.QWidget();layout=W.QVBoxLayout(widget)
        layout.setContentsMargins(10,10,4,10);layout.setSpacing(9)
        self.file_name=label("尚未选择文件",wrap=True,name="muted");layout.addWidget(self.file_name)
        box,items=panel("❶ 运行状态")
        self.progress_text=label("等待运行",wrap=True,name="muted")
        self.result_summary=label("尚无结果",wrap=True)
        self.progress_bar=W.QProgressBar();self.progress_bar.setRange(0,100);self.progress_bar.setValue(0)
        items.addWidget(self.progress_text);items.addWidget(self.progress_bar);items.addWidget(self.result_summary)
        self.computation_time=label("算法计算时间：—",wrap=True)
        self.computation_time.setToolTip("装箱求解及求解器初始化耗时，包含启用的机器人验证；不含输入读取和结果导出。")
        items.addWidget(self.computation_time)
        self.latest_result_button=button('查看本次结果',self.show_latest_result,'primaryButton')
        self.latest_result_button.hide();items.addWidget(self.latest_result_button)
        layout.addWidget(box)
        box,items=panel("❷ 筛选托盘")
        self.input_summary=label("支持CSV、标准JSON和zhuang接口JSON。",wrap=True,name="muted")
        items.addWidget(self.input_summary)
        self.pallet_filter=W.QComboBox();self.pallet_filter.addItem("全部托盘")
        self.pallet_filter.currentTextChanged.connect(self.apply_filter)
        items.addWidget(self.pallet_filter)
        self.search=W.QLineEdit();self.search.setPlaceholderText("托盘号 / 箱号 / 箱型")
        self.search.returnPressed.connect(self.apply_filter)
        items.addWidget(self.search)
        items.addWidget(button("筛选",self.apply_filter))
        self.filter_count=label("可选托盘：0",name="muted");items.addWidget(self.filter_count)
        layout.addWidget(box)
        grid=W.QGridLayout();grid.setSpacing(7)
        self.metrics={}
        for i,(key,title,foot,tint) in enumerate((("pallet_count","总托盘数","本次结果",False),
            ("packed_box_count","已装箱数","已放置箱体",True),("unplaced_box_count","未装箱数","需要检查",False),
            ("volume_utilization","总体填充率","全部已用托盘",True))):
            card=MetricCard(title,foot,tint);self.metrics[key]=card
            card.set_value("—");grid.addWidget(card,i//2,i%2)
        layout.addLayout(grid)
        box,items=panel("输入与结果")
        self.result_info=label("尚未加载结果",wrap=True,name="muted")
        self.method_note=label("",wrap=True,name="muted")
        items.addWidget(self.result_info)
        items.addWidget(button("导出当前坐标 CSV",self.export_csv))
        items.addWidget(button("打开结果目录",self.open_output_folder))
        items.addWidget(self.method_note)
        layout.addWidget(box);layout.addStretch(1)
        return widget

    def _build_center(self):
        overview=W.QWidget();layout=W.QVBoxLayout(overview)
        layout.setContentsMargins(10,10,10,10);layout.setSpacing(8)
        box,items=panel()
        items.addWidget(label("播放顺序：统一执行顺序（seq）  ·  拖动旋转 / 滚轮缩放 / 点击联动右侧",wrap=True,name="muted"))
        layout.addWidget(box)
        bar=W.QHBoxLayout()
        bar.addWidget(label("垛型总览（每页4个）",name="sectionTitle"));bar.addStretch(1)
        self.prev_page_button=button("上一页",lambda:self.change_page(-1))
        self.next_page_button=button("下一页",lambda:self.change_page(1))
        self.page_label=label("0 / 0",name="muted")
        for item in (self.prev_page_button,self.next_page_button,self.page_label):bar.addWidget(item)
        layout.addLayout(bar)
        self.overview_body=W.QWidget();self.overview_grid=W.QGridLayout(self.overview_body)
        self.overview_grid.setContentsMargins(0,0,0,0);self.overview_grid.setSpacing(8)
        self.overview_grid.setColumnStretch(0,1);self.overview_grid.setColumnStretch(1,1)
        layout.addWidget(scroll(self.overview_body),1)
        self.tabs.addTab(overview,"3D装箱视图")
        self.box_table=self._table_tab("箱子列表",["顺序","托盘","箱号","箱型","X","Y","Z","姿态","长","宽","高"])
        self.unplaced_table=self._table_tab("失败列表",["箱号","箱型","长","宽","高","未放置原因"])
        self.detail_tab=W.QWidget();detail=W.QVBoxLayout(self.detail_tab)
        bar=W.QHBoxLayout()
        self.pallet_combo=W.QComboBox();self.pallet_combo.currentIndexChanged.connect(self._detail_selection)
        self.color_combo=W.QComboBox();self.color_combo.addItems(["按箱子着色","按箱型着色","按高度着色"])
        self.color_combo.currentTextChanged.connect(self.render_detail)
        self.labels_check=W.QCheckBox("显示序号");self.labels_check.toggled.connect(self.render_detail)
        self.motion_detail_button=button('机械臂回放',lambda:self.open_robot_replay(self._selected_index))
        bar.addWidget(self.pallet_combo);bar.addWidget(self.motion_detail_button);bar.addStretch(1);bar.addWidget(self.labels_check);bar.addWidget(self.color_combo)
        detail.addLayout(bar)
        self.detail_canvas=PalletCanvas();detail.addWidget(self.detail_canvas,1)
        controls=W.QHBoxLayout();self.animation_buttons=[]
        for text,action in (("最终",self.final_state),("播放",self.play_animation),("暂停",self.pause_animation),
            ("前一步",self.previous_step),("后一步",self.next_step),("重置",self.reset_animation),
            ("复位视角",self.detail_canvas.reset_view)):
            btn=button(text,action);controls.addWidget(btn);self.animation_buttons.append(btn)
        detail.addLayout(controls)
        line=W.QHBoxLayout()
        self.step_slider=W.QSlider(C.Qt.Horizontal);self.step_slider.setRange(0,0)
        self.step_slider.valueChanged.connect(self._slider_changed)
        self.step_label=label("0 / 0 箱")
        self.speed_spin=W.QSpinBox();self.speed_spin.setRange(100,3000);self.speed_spin.setValue(450);self.speed_spin.setSuffix(" ms")
        self.speed_spin.valueChanged.connect(self.play_timer.setInterval)
        line.addWidget(self.step_slider,1);line.addWidget(self.step_label);line.addWidget(self.speed_spin)
        detail.addLayout(line)
        self.tabs.addTab(self.detail_tab,"单托盘 / 回放")
        self.audit_box=W.QPlainTextEdit();self.audit_box.setReadOnly(True)
        self.audit_box.setFont(G.QFont("Consolas",9))
        self.tabs.addTab(self.audit_box,"算法 / 约束记录")
        self._enable_animation(False)

    def _table_tab(self,title,headings):
        table=W.QTableWidget(0,len(headings));table.setHorizontalHeaderLabels(headings)
        table.setAlternatingRowColors(True);table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        for i,text in enumerate(headings):table.setColumnWidth(i,120 if text in ("箱号","箱型") else 75)
        self.tabs.addTab(table,title)
        return table

    def _build_right(self):
        widget=W.QWidget();layout=W.QVBoxLayout(widget)
        layout.setContentsMargins(4,10,10,10);layout.setSpacing(9)
        box,items=panel("当前托盘")
        self.selected_title=label("等待装箱",name="currentTitle")
        self.selected_subtitle=label("点击托盘卡片查看",wrap=True,name="muted")
        items.addWidget(self.selected_title);items.addWidget(self.selected_subtitle);layout.addWidget(box)
        grid=W.QGridLayout();grid.setSpacing(7);self.pallet_metrics={}
        for i,(key,title,foot) in enumerate((("box_count","箱子数量","当前托盘"),("types","箱型数量","标签与尺寸分类"),
            ("fill","填充率","托盘空间利用率"),("height_util","高度利用率","最高箱顶 / 限高"),
            ("height","已用高度","与输入尺寸同单位"),("weight","总重量","输入重量合计"),
            ("volume","已装体积","长×宽×高合计"),("remaining","剩余体积","容量减箱体体积"))):
            card=MetricCard(title,foot,i not in (4,5));card.set_value("—");self.pallet_metrics[key]=card
            grid.addWidget(card,i//2,i%2)
        layout.addLayout(grid)
        box,items=panel("托盘信息")
        self.current_info=label("尚无结果",wrap=True,name="muted");items.addWidget(self.current_info)
        items.addWidget(label("参数与约束依据见“算法 / 约束记录”。当前不计算机械臂可达性或吸盘碰撞。",wrap=True,name="muted"))
        layout.addWidget(box);layout.addStretch(1)
        return widget

    def _build_log(self,layout):
        holder=W.QWidget();items=W.QVBoxLayout(holder);items.setContentsMargins(12,5,12,6)
        line=W.QHBoxLayout();line.addWidget(label("运行消息",name="sectionTitle"))
        self.last_log=label("工作台已就绪",wrap=True,name="muted");line.addWidget(self.last_log,1)
        self.log_toggle=button("展开日志",self.toggle_log);line.addWidget(self.log_toggle)
        line.addWidget(button("清空",self.clear_log));items.addLayout(line)
        self.log_box=W.QTextEdit();self.log_box.setObjectName("logBox");self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(150);self.log_box.setVisible(False);items.addWidget(self.log_box)
        items.addWidget(label("离线装箱 · 本地文件 · 研究实现，尚未验证论文数值等价",name="muted"))
        layout.addWidget(holder)

    def toggle_log(self):
        showing=not self.log_box.isVisible()
        self.log_box.setVisible(showing);self.log_toggle.setText("收起日志" if showing else "展开日志")

    def clear_log(self): self.log_lines.clear();self.log_box.clear()

    @C.pyqtSlot(str)
    def _log(self,text):
        self.log_lines.append(f"[{datetime.now():%H:%M:%S}] {text}")
        self.log_lines=self.log_lines[-1500:]
        self.last_log.setText(text[:120])
        self.log_box.append(self.log_lines[-1])
        if self.running and text.startswith(("Phase 1","Phase 2","GA 第","GA 候选","机器人验证","任务进度","详细验证")):self.progress_text.setText(text)

    def _view_error(self,message):
        self._log('读取结果失败：'+message+('；后台计算仍在继续。' if self.running else ''))
        W.QMessageBox.warning(self,'无法打开结果',message)

    def _error(self,message):
        self._set_status("运行失败");self._log("错误："+message)
        if not self._close_pending:W.QMessageBox.critical(self,"无法完成操作",message)

    def _set_status(self,text):
        self.status_label.setText(text)
        tone=("busy" if text in ("计算中","正在载入") else "error" if text=="运行失败" else
              "stopped" if text in ("正在停止","已停止","已超时（未完成）") else "idle" if text=="空闲" else "done")
        self.status_label.setProperty("statusTone",tone)
        self.status_label.style().unpolish(self.status_label);self.status_label.style().polish(self.status_label)

    def choose_input(self):
        path,_=W.QFileDialog.getOpenFileName(self,"选择装箱输入",str(self.project_dir),"装箱输入 (*.xlsx *.csv *.json);;Excel 工作簿 (*.xlsx);;CSV (*.csv);;JSON (*.json)")
        if path:
            try:self.load_input_file(path)
            except Exception as exc:self._error(str(exc))

    def load_input_file(self,path):
        info=inspect_input(path)
        self.input_path,self.input_info=Path(path),info
        self.file_name.setText(self.input_path.name);self.file_name.setToolTip(str(path))
        self.order_combo.blockSignals(True);self.order_combo.clear();self.order_combo.addItems(list(info["summaries"]))
        self.order_combo.blockSignals(False);self.order_combo.setEnabled(info["kind"]=="paper" and not self.running)
        if info["pallet"]:self.dimensions=[str(v) for v in info["pallet"]]
        self._input_summary()
        self._log(f"已选择输入：{path}")
        if info.get('pallet_axes_swapped'):
            self._log(f'托盘已按长边X、短边Y调整：X={self.dimensions[0]}，Y={self.dimensions[1]}，Z限高={self.dimensions[2]}。')
        if info["kind"]=="wcs_json":self._log(f"接口JSON全部读取：{info['case_types']}；统一托盘规格须在装箱设置中确认。")
        if info["kind"]=="xlsx":
            self._log(f"Excel 工作表：{info['worksheet']}；箱内零件数量与订单字段不参与箱数展开。")
            for warning in info["warnings"]:self._log(warning)

    def _input_summary(self,*args):
        if not self.input_info:return
        data=self.input_info["summaries"].get(self.order_combo.currentText())
        if not data:return
        method="同型成层，剩余箱按箱型排列搜索。" if self.mode_combo.currentText()!="基础模式" else "输入行顺序即固定装箱顺序。"
        text=f"{data['box_types']} 种箱型 · {data['boxes']} 箱\n{method}"
        text+=f'\n本次托盘：X长边 {self.dimensions[0]} × Y短边 {self.dimensions[1]} × Z限高 {self.dimensions[2]}'
        if self.input_info["kind"]=="wcs_json":text+="\n接口JSON全部读取；请确认统一托盘尺寸，不按订单自动分组。"
        if self.input_info["kind"]=="xlsx":
            text+=f"\nExcel：{self.input_info['worksheet']}；不按订单分组。"
            if self.input_info["warnings"]:text+="\n"+"\n".join(self.input_info["warnings"])
        self.input_summary.setText(text)

    def _mode_changed(self,*args):
        if not hasattr(self,"method_note"):return
        self.method_note.setText("论文两阶段研究实现\n层/块 + NSGA-II GA + EP\n参数假设见结果记录。" if self.mode_combo.currentText()=="论文两阶段" else
                                "基础模式：固定序列 + 简化EP；未执行层/块与GA。")
        self._input_summary();self._result_identity()

    def _result_identity(self):
        selected=self.mode_combo.currentText()
        if self.document is None:
            loaded="尚无结果";self.result_summary.setText("请选择文件后点击一键装箱。")
        else:
            audit=self.document.get("paper_diagnostics")
            if isinstance(audit,dict) and audit:
                loaded="论文两阶段";phase=audit.get("phase1",{})
                count=phase.get("phase1_box_count","—") if isinstance(phase,dict) else "—"
                passed="6项硬约束通过" if audit.get("all_hard_constraints_pass") else "硬约束状态见记录"
                self.result_summary.setText(f"结果：论文两阶段\n层/块 {count} 箱 · GA 剩余箱 {audit.get('residual_box_count','—')} 箱\n文件记录：{passed}")
            else:
                loaded="基础模式";self.result_summary.setText("结果：基础模式\n固定序列 + 简化EP\n未执行层/块与GA。")
        mismatch=" ｜ 模式不同，需重新计算" if self.document is not None and loaded!=selected else ""
        self.mode_banner.setText(f"PyQt5版 v{APP_VERSION}  当前计算：{selected} ｜ 当前结果：{loaded}{mismatch}")

    def show_settings(self):
        dialog=W.QDialog(self);dialog.setWindowTitle("装箱设置");dialog.resize(470,540)
        layout=W.QVBoxLayout(dialog);form=W.QFormLayout()
        fields={}
        for key,value,title in [(f"dim{i}",v,t) for i,(v,t) in enumerate(zip(self.dimensions,("托盘长边 / X","托盘短边 / Y","最大高 / Z")))]+[
            ("support",self.support,"基础模式最小支撑率"),*[(k,v,t) for (k,v),t in zip(self.paper_parameters.items(),
             ("空托盘质量","重心偏移比例","角点内缩比例","随机种子"))]]:
            entry=W.QLineEdit(value);fields[key]=entry;form.addRow(title,entry)
        budget=W.QDoubleSpinBox();budget.setObjectName('maxJobMinutes');budget.setRange(.1,1440.);budget.setDecimals(1);budget.setValue(self.max_job_minutes);budget.setSuffix(' 分钟')
        form.addRow('整次计算总时限',budget)
        fields["support"].setEnabled(self.mode_combo.currentText()=="基础模式")
        layout.addLayout(form)
        layout.addWidget(label("X沿托盘长边，Y沿短边，Z向上；输入反了会自动交换两条底边尺寸。尺寸单位须与箱体一致。论文支撑使用40%+4角 / 50%+3角 / 75%+2角组合。",wrap=True,name="muted"))
        output=W.QLineEdit(str(self.output_dir));layout.addWidget(label("结果保存目录"));layout.addWidget(output)
        def choose():
            folder=W.QFileDialog.getExistingDirectory(dialog,"选择保存目录",output.text())
            if folder:output.setText(folder)
        layout.addWidget(button("选择目录",choose))
        controls=W.QDialogButtonBox(W.QDialogButtonBox.Ok|W.QDialogButtonBox.Cancel)
        def accept():
            try:
                dims=[fields[f"dim{i}"].text() for i in range(3)]
                for v in dims:finite_number(v,"托盘尺寸",positive=True)
                pallet=Pallet(*map(float,dims)).with_long_side_x()
                dims=[str(v) for v in (pallet.length,pallet.width,pallet.max_height)]
                support=fields["support"].text()
                if self.mode_combo.currentText()=="基础模式" and finite_number(support,"支撑率")>1:raise ValueError("支撑率必须位于[0,1]")
                parameters={k:fields[k].text() for k in self.paper_parameters}
                self._paper_config(parameters)
                if not output.text().strip():raise ValueError("请选择保存目录")
            except ValueError as exc:W.QMessageBox.warning(dialog,"参数错误",str(exc));return
            self.dimensions,self.support,self.paper_parameters=dims,support,parameters
            self.max_job_minutes=budget.value()
            self._input_summary()
            self._log(f'托盘坐标：X长边={dims[0]}，Y短边={dims[1]}，Z限高={dims[2]}。')
            self.output_dir=Path(output.text());self.refresh_history();dialog.accept()
        controls.accepted.connect(accept);controls.rejected.connect(dialog.reject);layout.addWidget(controls)
        dialog.exec_()

    @staticmethod
    def _paper_config(parameters):
        return PaperConfig(**{k:(int(v) if k=="seed" else float(v)) for k,v in parameters.items()})

    def _busy(self,busy):
        # The worker owns its captured inputs/options. Browsing only updates the view.
        for widget in (self.input_button,self.start_button,self.settings_button,self.mode_combo):widget.setEnabled(not busy)
        self.open_button.setEnabled(True);self.history.setEnabled(True)
        self.settings_button.setToolTip('本次计算参数已锁定，计算结束后可修改。' if busy else '')
        self.order_combo.setEnabled(not busy and bool(self.input_info) and self.input_info["kind"]=="paper")
        self.stop_button.setEnabled(busy)

    def _job_options(self):
        return ({"algorithm":"paper","paper_config":self._paper_config(self.paper_parameters),"max_seconds":self.max_job_minutes*60}
                if self.mode_combo.currentText()=="论文两阶段" else {"algorithm":"basic","max_seconds":self.max_job_minutes*60})

    def start_packing(self):
        if self.running:return
        if self.input_path is None:W.QMessageBox.information(self,"请选择文件","请先选择CSV或JSON输入文件。");return
        try:
            dims=[finite_number(v,"托盘尺寸",positive=True) for v in self.dimensions]
            pallet=Pallet(*dims).with_long_side_x()
            dims=[pallet.length,pallet.width,pallet.max_height]
            self.dimensions=[str(v) for v in dims]
            self._input_summary()
            paper=self.mode_combo.currentText()!="基础模式"
            support=1.0 if paper else finite_number(self.support,"支撑率")
            if support>1:raise ValueError("支撑率必须位于[0,1]")
            options=self._job_options()
        except ValueError as exc:self._error(str(exc));return
        self.pause_animation()
        for card in self.overview_cards:card.pause()
        target=self.output_dir/datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
        args=(self.input_path,self.order_combo.currentText(),*dims,support,target)
        self._job_start_view_revision=self._view_revision
        self._pending_result_path=None;self.latest_result_button.hide()
        self.cancel_event=threading.Event()
        gc.collect()
        self._thread=C.QThread(self)
        self._worker=PackingWorker(args,options,self.cancel_event)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._log)
        self._worker.result.connect(self._on_result)
        self._worker.stopped.connect(self._on_stopped)
        self._worker.expired.connect(self._on_timed_out)
        self._worker.failed.connect(self._error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._job_finished)
        self._busy(True);self.progress_bar.setValue(0);self.progress_text.setText("正在读取输入……");self._set_status("计算中")
        self._log(f"开始：{self.input_path.name}，范围：{self.order_combo.currentText()}，算法：{self.mode_combo.currentText()}")
        self._log(f"本次运行目录：{target}；总时限 {self.max_job_minutes:g} 分钟。")
        self._thread.start()

    def stop_packing(self):
        if not self.running:return
        if self._worker.completed.is_set():self._set_status("正在载入");return
        self.cancel_event.set();self.stop_button.setEnabled(False);self._set_status("正在停止")
        self._log("已请求停止，等待当前操作安全结束。")

    @C.pyqtSlot(int,int)
    def _on_progress(self,done,total):
        self.progress_bar.setValue(min(99,int(done/max(1,total)*100)))
        self.progress_text.setText(f"已处理 {done} / {total} 箱"+("，正在保存……" if done==total else ""))

    @C.pyqtSlot(object)
    def _on_result(self,result):
        preserve_view=self._view_revision!=self._job_start_view_revision
        if preserve_view:
            self._pending_result_path=Path(result['paths']['json'])
            self.latest_result_button.show()
        else:
            try:self.load_result_file(result["paths"]["json"])
            except Exception as exc:self._error(str(exc));return
        self.progress_bar.setValue(100)
        self.progress_text.setText(f"完成，总处理时间 {result['elapsed_seconds']:.3f} 秒（含读取和导出）"+
            ('\n已保留当前历史画面，可点击“查看本次结果”。' if preserve_view else ''))
        self._set_status("已完成");self.refresh_history()
        self._log(f"完成：{result['packed_box_count']} 箱，{result['pallet_count']} 托盘；算法计算时间 {result['algorithm_seconds']:.3f} 秒，总处理时间 {result['elapsed_seconds']:.3f} 秒。")

    @C.pyqtSlot(str)
    def _on_timed_out(self,message):
        self._set_status('已超时（未完成）');self.progress_text.setText(message)
        self._log(message)

    @C.pyqtSlot()
    def _on_stopped(self):
        self._set_status("已停止");self.progress_text.setText("本次已停止；保留此前结果。")
        self._log("本次任务已取消，未发布完成方案。")

    @C.pyqtSlot()
    def _job_finished(self):
        old=self._thread;self._thread=self._worker=None
        if old:old.deleteLater()
        self._busy(False)
        if self._close_pending:self.close()

    def choose_result(self):
        path,_=W.QFileDialog.getOpenFileName(self,"打开装箱方案",str(self.output_dir),"装箱方案 (*.json)")
        if path:
            try:self.load_result_file(path)
            except Exception as exc:self._view_error(str(exc))

    def show_latest_result(self):
        if self._pending_result_path is None:return
        try:self.load_result_file(self._pending_result_path)
        except Exception as exc:self._view_error(str(exc));return
        self._pending_result_path=None;self.latest_result_button.hide()

    def load_result_file(self,path):self.display_document(load_result(path),Path(path))

    def display_document(self,document,path=None):
        self._view_revision+=1
        for dialog in list(self._motion_windows.values()):dialog.close()
        self._motion_windows.clear()
        self.pause_animation();self.document,self.result_path=document,Path(path) if path else None
        self.page=0;self._applied_search="";self.search.clear()
        self.pallet_filter.blockSignals(True);self.pallet_filter.clear();self.pallet_filter.addItem("全部托盘")
        self.pallet_filter.addItems([f"托盘 {p['pallet_index']}" for p in document["pallets"]]);self.pallet_filter.blockSignals(False)
        self._selected_index=None
        for key,card in self.metrics.items():
            value=document["summary"][key];card.set_value(f"{value:.1%}" if key=="volume_utilization" else str(value))
        seconds=document.get("timing",{}).get("algorithm_seconds")
        self.computation_time.setText(f"算法计算时间：{seconds:.3f} 秒" if seconds is not None else "算法计算时间：未记录（旧结果）")
        self.result_info.setText(f"{path.parent.name}\n{path.name}" if path else "当前计算结果")
        audit=document.get("paper_diagnostics") or {"mode":"基础模式","checks":["Z0/Z90","边界","AABB","支撑面积"],"note":"没有执行论文完整两阶段算法"}
        self.audit_box.setPlainText(json.dumps(audit,ensure_ascii=False,indent=2))
        self._result_identity();self.apply_filter();self.tabs.setCurrentIndex(0)
        if not self.running:
            self._set_status("已加载");self.progress_bar.setValue(100)
            self.progress_text.setText("已加载已有结果，未重新计算。")
        if self._pending_result_path is not None and path is not None and Path(path).resolve()==self._pending_result_path.resolve():
            self._pending_result_path=None;self.latest_result_button.hide()
        self._log(f"已加载结果：{path or '当前计算结果'}")

    def refresh_history(self):
        self._history_paths={};candidates=[]
        if self.output_dir.exists():
            for path in self.output_dir.rglob("*.json"):
                if ".packing_" in str(path) or not (path.name.endswith("_plan.json") or path.name.startswith("packing_plan")):continue
                try:candidates.append((path.stat().st_mtime,path))
                except OSError:pass
        self.history.clear();self.history.addItem("选择历史结果…")
        for i,(_,path) in enumerate(sorted(candidates,reverse=True)[:100],1):
            title=f"{i}. {path.parent.name}/{path.stem}";self.history.addItem(title);self.history.setItemData(i,str(path),C.Qt.ToolTipRole);self._history_paths[title]=path

    def _open_history(self,*args):
        path=self._history_paths.get(self.history.currentText())
        if path:
            try:self.load_result_file(path)
            except Exception as exc:self._view_error(str(exc))

    def filtered_pallets(self):
        if not self.document:return []
        name=self.pallet_filter.currentText();query=self._applied_search
        return [p for p in self.document["pallets"] if (name=="全部托盘" or name==f"托盘 {p['pallet_index']}") and
            (not query or query in f"托盘 {p['pallet_index']} pallet-{p['pallet_index']:03d}".casefold() or
             any(query in f"{i['id']} {i.get('box_type','')}".casefold() for i in p["packed_items"]))]

    def apply_filter(self,*args):
        self.page=0;self._applied_search=self.search.text().strip().casefold()
        pallets=self.filtered_pallets()
        self.pallet_combo.blockSignals(True);self.pallet_combo.clear()
        for p in pallets:self.pallet_combo.addItem(f"托盘 {p['pallet_index']}",p['pallet_index'])
        self.pallet_combo.blockSignals(False)
        indices=[p["pallet_index"] for p in pallets]
        self.select_pallet(self._selected_index if self._selected_index in indices else (indices[0] if indices else None))
        self.refresh_overview()

    def change_page(self,delta):
        self.page=max(0,min(max(0,math.ceil(len(self.filtered_pallets())/4)-1),self.page+delta))
        self.refresh_overview()

    def refresh_overview(self):
        for card in self.overview_cards:card.pause()
        self.overview_cards=[]
        while self.overview_grid.count():
            item=self.overview_grid.takeAt(0)
            if item.widget():item.widget().deleteLater()
        pallets=self.filtered_pallets();pages=math.ceil(len(pallets)/4)
        self.page=min(self.page,max(0,pages-1));self.page_label.setText(f"{self.page+1 if pages else 0} / {pages}")
        self.filter_count.setText(f"可选托盘：{len(pallets)}")
        self.prev_page_button.setEnabled(self.page>0);self.next_page_button.setEnabled(self.page+1<pages)
        if not pallets:
            empty=label("尚无托盘可显示\n\n选择输入文件开始装箱，或打开历史结果。",wrap=True)
            empty.setAlignment(C.Qt.AlignCenter);self.overview_grid.addWidget(empty,0,0,1,2);return
        for i,pallet in enumerate(pallets[self.page*4:self.page*4+4]):
            card=PalletCard(pallet);card.selected.connect(self.select_pallet);card.expand_requested.connect(self.focus_pallet)
            card.motion_requested.connect(self.open_robot_replay)
            card.set_selected(pallet["pallet_index"]==self._selected_index)
            self.overview_cards.append(card);self.overview_grid.addWidget(card,i//2,i%2)

    def current_pallet(self):
        return next((p for p in (self.document or {}).get("pallets",[]) if p["pallet_index"]==self._selected_index),None)

    def _detail_selection(self,*args):self.select_pallet(self.pallet_combo.currentData())

    def select_pallet(self,index):
        changed=index!=self._selected_index;self._selected_index=index
        self.pallet_combo.blockSignals(True);self.pallet_combo.setCurrentIndex(self.pallet_combo.findData(index));self.pallet_combo.blockSignals(False)
        pallet=self.current_pallet()
        if changed or pallet is None:
            self.pause_animation();self.step=len(pallet["packed_items"]) if pallet else 0
        self.step_slider.blockSignals(True);self.step_slider.setRange(0,len(pallet["packed_items"]) if pallet else 0)
        self.step_slider.setValue(self.step);self.step_slider.blockSignals(False)
        self._enable_animation(pallet is not None)
        for card in self.overview_cards:card.set_selected(card.pallet["pallet_index"]==index)
        self._current_metrics(pallet);self.render_detail();self.refresh_tables()
        self.motion_detail_button.setEnabled(pallet is not None)

    def focus_pallet(self,index):self.select_pallet(index);self.tabs.setCurrentWidget(self.detail_tab)

    def open_robot_replay(self,index):
        if index is None or self.document is None:return
        self.select_pallet(index)
        existing=self._motion_windows.get(index)
        if existing is not None:
            existing.show();existing.raise_();existing.activateWindow();return
        try:
            from .robot_replay import load_replay_bundle,RobotReplayDialog
            bundle=load_replay_bundle(self.project_dir,self.document,self.result_path,index)
            dialog=RobotReplayDialog(bundle,self)
        except Exception as exc:
            self._log('机械臂回放无法打开：'+str(exc))
            W.QMessageBox.information(self,'机械臂回放',str(exc));return
        self._motion_windows[index]=dialog
        def forget_dialog(_=None,key=index,instance=dialog):
            if self._motion_windows.get(key) is instance:self._motion_windows.pop(key,None)
        dialog.destroyed.connect(forget_dialog)
        dialog.show();dialog.play()
        self._log(f'打开托盘 {index} 的已保存机械臂轨迹回放。')

    def _current_metrics(self,pallet):
        if not pallet:
            self.selected_title.setText("没有托盘");self.selected_subtitle.setText("当前筛选下没有结果")
            self.current_info.setText("尚无选中托盘")
            for card in self.pallet_metrics.values():card.set_value("—")
            return
        items,dims=pallet["packed_items"],pallet["pallet"]
        height=max((i["position"]["z"]+i["placed_size"]["height"] for i in items),default=0)
        volume=sum(math.prod(i["placed_size"][k] for k in ("length","width","height")) for i in items)
        capacity=math.prod(dims[k] for k in ("length","width","height"))
        weight=sum(i.get("weight",0) or 0 for i in items)
        def box_type(item):
            if item.get("box_type"):return ("type",item["box_type"])
            size=item["placed_size"];l,w=size["length"],size["width"]
            if item.get("orientation")=="Z90":l,w=w,l
            return ("size",l,w,size["height"])
        values={"box_count":str(len(items)),"types":str(len({box_type(i) for i in items})),
                "fill":f"{pallet['volume_utilization']:.1%}","height_util":f"{height/dims['height']:.1%}",
                "height":f"{height:g}","weight":f"{weight:.5g}" if weight else "未提供 / 0",
                "volume":f"{volume:.3g}","remaining":f"{max(0,capacity-volume):.3g}"}
        self.selected_title.setText(f"PALLET-{pallet['pallet_index']:03d}")
        self.selected_subtitle.setText(f"已装 {len(items)} 箱 | 填充率 {pallet['volume_utilization']:.1%}")
        convention=(self.document or {}).get('coordinate_system',{}).get('pallet_axis_convention')
        note='X沿长边，Y沿短边，Z向上。' if convention=='long_side_x' else '历史/输入坐标：X=length，Y=width，Z向上。'
        self.current_info.setText(f"X {dims['length']:g} × Y {dims['width']:g} × Z {dims['height']:g}\n{note}")
        for key,card in self.pallet_metrics.items():card.set_value(values[key])

    def _enable_animation(self,enabled):
        for widget in self.animation_buttons:widget.setEnabled(enabled)
        self.step_slider.setEnabled(enabled)

    def render_detail(self,*args):
        pallet=self.current_pallet();maximum=len(pallet["packed_items"]) if pallet else 0
        self.step_label.setText(f"{self.step} / {maximum} 箱")
        mode={"按箱子着色":"box","按箱型着色":"type","按高度着色":"height"}.get(self.color_combo.currentText(),"box")
        self.detail_canvas.render(pallet,step=self.step,color_mode=mode,labels=self.labels_check.isChecked())

    def _set_step(self,value):
        pallet=self.current_pallet();maximum=len(pallet["packed_items"]) if pallet else 0
        self.step=max(0,min(maximum,value));self.step_slider.blockSignals(True);self.step_slider.setValue(self.step)
        self.step_slider.blockSignals(False);self.render_detail()

    def _slider_changed(self,value):self.pause_animation();self._set_step(value)
    def pause_animation(self):self.play_timer.stop()
    def reset_animation(self):self.pause_animation();self._set_step(0)
    def final_state(self):self.pause_animation();self._set_step(len(self.current_pallet()["packed_items"]) if self.current_pallet() else 0)
    def previous_step(self):self.pause_animation();self._set_step(self.step-1)
    def next_step(self):
        self._set_step(self.step+1)
        if self.step>=self.step_slider.maximum():self.pause_animation()
    def play_animation(self):
        if not self.current_pallet():return
        if self.step>=self.step_slider.maximum():self._set_step(0)
        self.play_timer.start(self.speed_spin.value())

    @staticmethod
    def _fill_table(table,rows):
        table.setRowCount(len(rows))
        for row,values in enumerate(rows):
            for col,value in enumerate(values):table.setItem(row,col,W.QTableWidgetItem(f"{value:g}" if isinstance(value,float) else str(value)))

    def refresh_tables(self):
        rows=[]
        selected=self.current_pallet()
        for pallet in ([selected] if selected is not None else []):
            for item in pallet["packed_items"]:
                rows.append([item["sequence"],pallet["pallet_index"],item["id"],item.get("box_type",""),
                    *(item["position"][k] for k in ("x","y","z")),item["orientation"],
                    *(item["placed_size"][k] for k in ("length","width","height"))])
        self.table_rows=sorted(rows,key=lambda row:row[0]);self._fill_table(self.box_table,self.table_rows)
        title=f"箱子列表 · 托盘 {selected['pallet_index']}（{len(rows)}箱）" if selected is not None else "箱子列表 · 未选托盘"
        self.tabs.setTabText(self.tabs.indexOf(self.box_table),title)
        failed=(self.document or {}).get("unplaced_items",[])
        self._fill_table(self.unplaced_table,[[i["id"],i.get("box_type",""),
            *(i["size"][k] for k in ("length","width","height")),i["reason"]] for i in failed])

    def export_csv(self):
        if not self.document:return
        path,_=W.QFileDialog.getSaveFileName(self,"导出选中托盘坐标",str(self.output_dir/"filtered_positions.csv"),"CSV (*.csv)")
        if path:
            try:
                with Path(path).open("w",encoding="utf-8-sig",newline="") as handle:
                    writer=csv.writer(handle);writer.writerow(["order","pallet","box_id","box_type","x","y","z","orientation","length","width","height"])
                    writer.writerows(self.table_rows)
                self._log(f"已导出：{path}")
            except OSError as exc:self._error(str(exc))

    def open_output_folder(self):
        folder=self.result_path.parent if self.result_path else self.output_dir
        folder.mkdir(parents=True,exist_ok=True);G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(str(folder.resolve())))

    def closeEvent(self,event):
        for dialog in list(self._motion_windows.values()):dialog.close()
        self._motion_windows.clear()
        self.pause_animation()
        for card in self.overview_cards:card.pause()
        if self.running:
            self._close_pending=True;self.stop_packing();event.ignore()
        else:event.accept()


def launch_workbench():
    app=W.QApplication.instance()
    if app is None:
        C.QCoreApplication.setAttribute(C.Qt.AA_EnableHighDpiScaling,True)
        C.QCoreApplication.setAttribute(C.Qt.AA_UseHighDpiPixmaps,True)
        app=W.QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    window=PackingWorkbench();window.showMaximized()
    return app.exec_()
