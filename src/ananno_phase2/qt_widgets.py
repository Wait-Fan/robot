"""Reusable PyQt5 workbench widgets with independent pallet playback."""
from __future__ import annotations

from PyQt5.QtCore import QPointF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QSlider, QVBoxLayout, QWidget, QStyledItemDelegate, QStyle,
)

from .native_scene import project_scene


VIVID_PALETTE = (
    "#ff3434", "#00e844", "#ff8500", "#00e5eb",
    "#a63fff", "#ff27ec", "#ffdf00", "#348bff",
)

WORKBENCH_STYLE = """
QMainWindow, QDialog { background: #f0f3f7; }
QWidget { color: #26364d; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 12px; }
QFrame#header, QWidget#header { background: #111e36; border: 0; }
#header QLabel { background: transparent; color: #f3f7ff; }
QFrame#darktoolbar, QWidget#darktoolbar, QFrame#toolbar, QWidget#toolbar {
    background: #192a47; border: 0;
}
#darktoolbar QLabel, #toolbar QLabel { color: #d0d9e9; background: transparent; }
QFrame#panel, QFrame#palletCard, QFrame#metricCard {
    background: white; border: 1px solid #dfe6ee; border-radius: 9px;
}
QFrame#palletCard[selected="true"] { border: 2px solid #2788ff; }
QFrame#metricCard[tint="true"] { background: #effaf3; border-color: #d2ebdb; }
QFrame#metricCard QLabel { background: transparent; border: 0; }
QLabel#metricTitle, QLabel#metricFoot, QLabel#caption { color: #7b899d; }
QLabel#metricValue { color: #172a43; font-size: 24px; font-weight: 700; }
QFrame#metricCard[tint="true"] QLabel#metricValue { color: #23935d; }
QLabel#cardTitle { font-size: 14px; font-weight: 700; color: #1b2b43; }
QLabel#caption { font-size: 10px; }
QLabel#palletStatus { color: #278856; font-size: 10px; }
QPushButton { background: #eef2f7; color: #40516a; border: 1px solid #dce3ec;
    border-radius: 5px; padding: 5px 10px; min-height: 19px; }
QPushButton:hover { background: #e5edf9; border-color: #a7c6ee; }
QPushButton:pressed { background: #dce8f8; }
QPushButton:disabled { color: #aab4c2; background: #f3f5f8; }
QPushButton#primary { background: #2678e9; color: white; border-color: #2678e9; }
QPushButton#primary:hover { background: #1768d7; }
QPushButton#danger { color: #c64d4d; background: #fff0f0; border-color: #efcece; }
QPushButton#compact, QPushButton#expand { font-size: 10px; padding: 1px 4px; min-height: 20px; }
QPushButton#expand { background: #f6f8fb; min-width: 21px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #fafbfd; border: 1px solid #d9e1eb; border-radius: 5px;
    padding: 4px 6px; min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #4998ee; }
QComboBox#compact { font-size: 10px; min-height: 17px; padding: 1px 5px; }
QComboBox QAbstractItemView { background: white; color: #26364d; selection-background-color: #e1edfc; }
QCheckBox { spacing: 4px; background: transparent; }
QCheckBox#compact { font-size: 10px; }
QSlider::groove:horizontal { height: 3px; border-radius: 1px; background: #dce5ef; }
QSlider::sub-page:horizontal { background: #4591eb; }
QSlider::handle:horizontal { width: 10px; height: 10px; margin: -4px 0;
    background: #2f83e8; border: 1px solid white; border-radius: 5px; }
QTabWidget::pane { border: 1px solid #dfe6ee; background: white; border-radius: 5px; }
QTabBar::tab { background: #edf1f6; color: #718097; padding: 7px 15px; border: 0; }
QTabBar::tab:selected { color: #2678e9; background: white; border-bottom: 2px solid #2678e9; }
QTableWidget, QTableView { background: white; alternate-background-color: #f7f9fc;
    gridline-color: #edf0f5; border: 1px solid #e4e9f0; selection-background-color: #e3efff;
    selection-color: #1c4b82; }
QHeaderView::section { background: #f1f5fa; color: #64758c; padding: 6px;
    border: 0; border-bottom: 1px solid #e0e6ef; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { width: 8px; background: #f0f3f7; }
QScrollBar::handle:vertical { background: #c3cede; border-radius: 4px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QPlainTextEdit, QTextEdit { background: #f7f9fc; color: #53647d;
    border: 1px solid #e0e6ee; border-radius: 5px; }
QProgressBar { background: #e9eff6; border: 0; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: #3386e9; border-radius: 4px; }
QToolTip { background: #172a43; color: white; border: 0; padding: 5px; }
"""


class HistoryItemDelegate(QStyledItemDelegate):
    """Popup rows must not inherit the dark toolbar combo's pale text palette."""
    def paint(self,painter,option,index):
        painter.save()
        selected=bool(option.state & QStyle.State_Selected)
        painter.fillRect(option.rect,QColor('#2563eb') if selected else QColor('#ffffff'))
        painter.setPen(QColor('#ffffff') if selected else QColor('#1f2937'))
        painter.setFont(option.font)
        bounds=option.rect.adjusted(8,0,-8,0)
        text=painter.fontMetrics().elidedText(str(index.data(Qt.DisplayRole) or ''),Qt.ElideMiddle,bounds.width())
        painter.drawText(bounds,Qt.AlignVCenter|Qt.AlignLeft,text)
        painter.restore()

    def sizeHint(self,option,index):
        size=super().sizeHint(option,index);size.setHeight(max(32,size.height()));return size


class PalletCanvas(QWidget):
    """Orthographic 3D scene painted from the actual box placements."""

    selected = pyqtSignal()

    def __init__(self, parent=None, *, yaw=35, pitch=28, zoom=1, **options):
        super().__init__(parent)
        self._initial_camera = (float(yaw), float(pitch), float(zoom))
        self.yaw, self.pitch, self.zoom = self._initial_camera
        self.pallet = None
        self.step = None
        self.color_mode = "box"
        self.labels = False
        self._drag_position = None
        self.setMinimumSize(180, 120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("拖动旋转 · 滚轮缩放 · 双击恢复视角")
        if "width" in options or "height" in options:
            self.resize(int(options.get("width", 400)), int(options.get("height", 240)))

    def render(self, pallet, step=None, color_mode="box", labels=False):
        self.pallet = pallet
        count = len(pallet["packed_items"]) if pallet is not None else 0
        self.step = None if step is None else max(0, min(int(step), count))
        self.color_mode = color_mode
        self.labels = bool(labels)
        self.update()

    def reset_view(self):
        self.yaw, self.pitch, self.zoom = self._initial_camera
        self.update()

    def view_top(self):
        self.yaw,self.pitch,self.zoom=0.,90.,1.;self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        if self.pallet is None:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(self.rect(), Qt.AlignCenter, "暂无托盘方案")
            return
        faces, lines, texts = project_scene(
            self.pallet, max(80, self.width()), max(70, self.height()),
            step=self.step, yaw=self.yaw, pitch=self.pitch, zoom=self.zoom,
            color_mode=self.color_mode, labels=self.labels, palette=VIVID_PALETTE,
        )
        painter.setPen(QPen(QColor("#c3cedc"), 1, Qt.DashLine))
        for start, end in lines:
            painter.drawLine(QPointF(*start), QPointF(*end))
        painter.setPen(QPen(QColor("#ffffff"), 1.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for _, points, color in faces:
            painter.setBrush(QColor(color))
            painter.drawPolygon(QPolygonF([QPointF(*point) for point in points]))
        # Draw deck/height limits over the boxes so packed faces do not hide them.
        for n,(start,end) in enumerate(lines):
            painter.setPen(QPen(QColor('#315e89') if n<4 else QColor('#718ba5'),2.2 if n<4 else 1.4,Qt.SolidLine if n<4 else Qt.DashLine))
            painter.drawLine(QPointF(*start),QPointF(*end))
        painter.setFont(QFont("Segoe UI", 9))
        for x, y, text in texts:
            painter.setPen(QColor("#304b67") if text.startswith(("X ", "Y ", "Z ","X+","Y+","Z+","O "))
                           else QColor("#172a43"))
            bounds = QFontMetricsF(painter.font()).boundingRect(text)
            painter.drawText(QPointF(x - bounds.width() / 2, y), text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selected.emit()
            self._drag_position = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_position is not None and event.buttons() & Qt.LeftButton:
            delta = event.pos() - self._drag_position
            self._drag_position = event.pos()
            self.yaw = (self.yaw + delta.x() * .6) % 360
            self.pitch = max(5, min(85, self.pitch + delta.y() * .4))
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_position = None
            self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.reset_view()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        self.zoom = max(.35, min(3, self.zoom * (1.12 ** (event.angleDelta().y() / 120))))
        self.update()
        event.accept()


class PalletCard(QFrame):
    """A selectable pallet preview with a separately owned playback timer."""

    selected = pyqtSignal(int)
    expand_requested = pyqtSignal(int)
    motion_requested = pyqtSignal(int)

    def __init__(self, pallet, parent=None):
        super().__init__(parent)
        self.setObjectName("palletCard")
        self.setProperty("selected", False)
        self.pallet = pallet
        self.step = len(pallet["packed_items"])
        self.playing = False
        self.timer = QTimer(self)
        self.timer.setInterval(450)
        self.timer.timeout.connect(self.tick)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 7)
        layout.setSpacing(4)
        top = QHBoxLayout()
        self.title = QLabel(f"PALLET-{int(pallet['pallet_index']):03d}")
        self.title.setObjectName("cardTitle")
        top.addWidget(self.title)
        top.addStretch(1)
        self.status_label = QLabel("已装载")
        self.status_label.setObjectName("palletStatus")
        top.addWidget(self.status_label)
        self.motion_button=QPushButton('机械臂回放')
        self.motion_button.setObjectName('compact')
        self.motion_button.setToolTip('播放该托盘计算时保存的机器人抓取、搬运与放置轨迹')
        self.motion_button.clicked.connect(lambda:self.motion_requested.emit(int(self.pallet['pallet_index'])))
        top.addWidget(self.motion_button)
        expand = QPushButton("↗")
        expand.setObjectName("expand")
        expand.setToolTip("展开托盘")
        expand.clicked.connect(lambda: self.expand_requested.emit(int(self.pallet["pallet_index"])))
        top.addWidget(expand)
        layout.addLayout(top)
        self.caption = QLabel()
        self.caption.setObjectName("caption")
        layout.addWidget(self.caption)
        controls = QHBoxLayout()
        controls.setSpacing(3)
        for text, action in (("最终", self.final), ("播放", self.play), ("暂停", self.pause),
                             ("<", self.previous), (">", self.next), ("重置", self.reset)):
            button = QPushButton(text)
            button.setObjectName("compact")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(action)
            controls.addWidget(button)
        layout.addLayout(controls)
        options = QHBoxLayout()
        options.setSpacing(5)
        options.addWidget(QLabel("着色"))
        self.colors = QComboBox()
        self.colors.setObjectName("compact")
        for title, mode in (("分箱", "box"), ("箱型", "type"), ("高度", "height")):
            self.colors.addItem(title, mode)
        self.colors.currentIndexChanged.connect(self.render)
        options.addWidget(self.colors, 1)
        self.labels = QCheckBox("序号")
        self.labels.setObjectName("compact")
        self.labels.toggled.connect(self.render)
        options.addWidget(self.labels)
        layout.addLayout(options)
        speed_row = QHBoxLayout()
        speed_row.setSpacing(5)
        speed_row.addWidget(QLabel("速度"))
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(25, 300)
        self.speed.setValue(100)
        self.speed.valueChanged.connect(self.rate_changed)
        speed_row.addWidget(self.speed, 1)
        self.rate_label = QLabel("1×")
        self.rate_label.setMinimumWidth(29)
        speed_row.addWidget(self.rate_label)
        layout.addLayout(speed_row)
        self.canvas = PalletCanvas(self)
        top_view=QPushButton('俯视');top_view.setObjectName('compact');top_view.clicked.connect(self.canvas.view_top)
        top.insertWidget(top.count()-1,top_view)
        self.canvas.selected.connect(self.select)
        layout.addWidget(self.canvas, 1)
        self.render()

    def select(self):
        self.selected.emit(int(self.pallet["pallet_index"]))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.select()
        super().mousePressEvent(event)

    def set_selected(self, selected):
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def render(self, *_):
        count = len(self.pallet["packed_items"])
        utilization = self.pallet.get("volume_utilization")
        if utilization is None:
            capacity = self.pallet["pallet"]
            volume = capacity["length"] * capacity["width"] * capacity["height"]
            utilization = sum(item["placed_size"]["length"] * item["placed_size"]["width"] *
                              item["placed_size"]["height"] for item in self.pallet["packed_items"]) / volume
        self.caption.setText(f"箱数 {count}  |  填充率 {utilization:.1%}  |  步骤 {self.step}/{count}")
        self.status_label.setText("播放中" if self.playing else ("已装载" if self.step == count else "逐箱预览"))
        self.canvas.render(self.pallet, self.step, self.colors.currentData(), self.labels.isChecked())

    def rate_changed(self, value):
        self.rate_label.setText(f"{value / 100:g}×")
        self.timer.setInterval(max(80, round(450 / (value / 100))))

    def play(self):
        self.select()
        self.pause()
        count = len(self.pallet["packed_items"])
        if not count:
            return
        if self.step >= count:
            self.step = 0
        self.playing = True
        self.render()
        self.timer.start()

    def pause(self):
        self.timer.stop()
        self.playing = False
        self.render()

    def tick(self):
        if not self.playing:
            return
        self.step = min(self.step + 1, len(self.pallet["packed_items"]))
        if self.step >= len(self.pallet["packed_items"]):
            self.pause()
        else:
            self.render()

    def move(self, value):
        self.select()
        self.timer.stop()
        self.playing = False
        self.step = max(0, min(int(value), len(self.pallet["packed_items"])))
        self.render()

    def previous(self):
        self.move(self.step - 1)

    def next(self):
        self.move(self.step + 1)

    def final(self):
        self.move(len(self.pallet["packed_items"]))

    def reset(self):
        self.move(0)

    def closeEvent(self, event):
        self.pause()
        super().closeEvent(event)


class MetricCard(QFrame):
    """Compact readout shared by the global and selected-pallet panels."""

    def __init__(self, title, foot="", tint=False, parent=None):
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setProperty("tint", bool(tint))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("metricTitle")
        self.value_label = QLabel("—")
        self.value_label.setObjectName("metricValue")
        self.foot_label = QLabel(foot)
        self.foot_label.setObjectName("metricFoot")
        self.foot_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        if foot:
            layout.addWidget(self.foot_label)

    def set_value(self, value):
        self.value_label.setText(str(value))
