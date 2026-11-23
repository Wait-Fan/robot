"""Real offscreen Qt widgets: geometry, interaction and playback ownership."""
import copy
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent, QWheelEvent
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication, QCheckBox, QComboBox, QPushButton, QSlider

from ananno_phase2.qt_widgets import MetricCard, PalletCanvas, PalletCard, WORKBENCH_STYLE


PALLET = {
    "pallet_index": 1, "pallet": {"length": 10, "width": 8, "height": 6},
    "volume_utilization": .2, "box_count": 2,
    "packed_items": [
        {"id": "A", "box_type": "small", "sequence": 1,
         "position": {"x": 0, "y": 0, "z": 0},
         "placed_size": {"length": 4, "width": 4, "height": 3}},
        {"id": "B", "box_type": "small", "sequence": 2,
         "position": {"x": 4, "y": 0, "z": 0},
         "placed_size": {"length": 4, "width": 4, "height": 3}},
    ],
}


class QtWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widgets = []

    def keep(self, widget):
        self.widgets.append(widget)
        return widget

    def tearDown(self):
        for widget in self.widgets:
            if not sip.isdeleted(widget):
                widget.close()
                widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_canvas_projects_real_faces_and_step_changes_visible_geometry(self):
        canvas = self.keep(PalletCanvas())
        canvas.resize(420, 300)
        canvas.render(copy.deepcopy(PALLET), step=0)
        empty = canvas.grab().toImage()
        canvas.render(PALLET, step=2)
        full = canvas.grab().toImage()
        vivid_pixels = sum(full.pixelColor(x, y).red() > 180
                           and full.pixelColor(x, y).green() < 100
                           for y in range(0, 300, 3) for x in range(0, 420, 3))
        self.assertGreater(vivid_pixels, 40)
        self.assertNotEqual(empty, full)
        moved = copy.deepcopy(PALLET)
        moved["packed_items"][0]["position"]["z"] = 3
        canvas.render(moved)
        self.assertNotEqual(full, canvas.grab().toImage())

    def test_camera_drag_wheel_and_reset_remain_responsive(self):
        canvas = self.keep(PalletCanvas())
        canvas.resize(420, 300)
        canvas.render(PALLET)
        selected = QSignalSpy(canvas.selected)
        original = (canvas.yaw, canvas.pitch, canvas.zoom)
        QTest.mousePress(canvas, Qt.LeftButton, pos=QPoint(100, 100))
        move = QMouseEvent(QEvent.MouseMove, QPointF(150, 120), Qt.NoButton,
                           Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(canvas, move)
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=QPoint(150, 120))
        self.assertEqual(len(selected), 1)
        self.assertNotEqual((canvas.yaw, canvas.pitch), original[:2])
        wheel = QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(),
                            QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                            Qt.NoScrollPhase, False)
        QApplication.sendEvent(canvas, wheel)
        self.assertGreater(canvas.zoom, original[2])
        canvas.reset_view()
        self.assertEqual((canvas.yaw, canvas.pitch, canvas.zoom), original)

    def test_empty_selection_clears_a_previously_rendered_canvas(self):
        canvas = self.keep(PalletCanvas())
        canvas.resize(420, 300)
        canvas.render(PALLET)
        full = canvas.grab().toImage()
        canvas.render(None, step=0)
        self.assertIsNone(canvas.pallet)
        self.assertEqual(canvas.step, 0)
        empty = canvas.grab().toImage()
        self.assertNotEqual(full, empty)
        canvas.render(None)
        self.assertIsNone(canvas.step)

    def test_playback_steps_are_bounded_and_keep_other_cards_independent(self):
        first = self.keep(PalletCard(PALLET))
        second = self.keep(PalletCard(dict(PALLET, pallet_index=2)))
        first.reset()
        self.assertEqual((first.step, second.step), (0, 2))
        first.previous()
        self.assertEqual(first.step, 0)
        first.next()
        self.assertEqual(first.step, 1)
        first.play()
        first.timer.setInterval(5)
        QTest.qWait(40)
        self.assertEqual((first.step, second.step), (2, 2))
        self.assertFalse(first.playing)
        self.assertFalse(first.timer.isActive())
        first.play()
        self.assertEqual(first.step, 0)
        self.assertTrue(first.playing)
        first.pause()
        self.assertFalse(first.timer.isActive())
        first.final()
        first.next()
        self.assertEqual(first.step, 2)

    def test_card_controls_change_color_labels_speed_and_emit_identity(self):
        card = self.keep(PalletCard(PALLET))
        card.resize(460, 430)
        selected, expanded = QSignalSpy(card.selected), QSignalSpy(card.expand_requested)
        QTest.mouseClick(card.canvas, Qt.LeftButton, pos=QPoint(50, 50))
        self.assertEqual(list(selected[-1]), [1])
        buttons = {b.text(): b for b in card.findChildren(QPushButton)}
        self.assertTrue({"最终", "播放", "暂停", "<", ">", "重置"} <= buttons.keys())
        QTest.mouseClick(card.findChild(QPushButton, "expand"), Qt.LeftButton)
        self.assertEqual(list(expanded[-1]), [1])
        colors = card.findChild(QComboBox)
        colors.setCurrentIndex(1)
        self.assertEqual(card.canvas.color_mode, "type")
        labels = card.findChild(QCheckBox)
        labels.setChecked(True)
        self.assertTrue(card.canvas.labels)
        speed = card.findChild(QSlider)
        initial = card.timer.interval()
        speed.setValue(speed.maximum())
        self.assertLess(card.timer.interval(), initial)
        card.set_selected(True)
        self.assertTrue(card.property("selected"))

    def test_empty_card_does_not_start_timer_and_deletion_owns_active_timer(self):
        empty = self.keep(PalletCard(dict(PALLET, packed_items=[], box_count=0)))
        empty.play()
        self.assertFalse(empty.playing)
        self.assertFalse(empty.timer.isActive())
        card = self.keep(PalletCard(PALLET))
        card.play()
        timer = card.timer
        card.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertTrue(sip.isdeleted(timer))
        QTest.qWait(20)

    def test_metric_card_displays_actual_value_with_shared_styles(self):
        card = self.keep(MetricCard("装载率", "体积利用率", tint=True))
        card.setStyleSheet(WORKBENCH_STYLE)
        card.set_value("83.5%")
        self.assertEqual(card.value_label.text(), "83.5%")
        self.assertTrue(card.property("tint"))


if __name__ == "__main__":
    unittest.main()
