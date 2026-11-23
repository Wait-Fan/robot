# PyQt5 workbench migration

**Goal:** Replace the default Tkinter desktop with a real PyQt5 workbench using the approved zhuang screenshot layout.
**Spec:** User explicitly requested migration to PyQt; this supersedes the earlier no-PyQt5 preference. Existing algorithms, input formats, no database and research disclaimers remain.
**Architecture:** New qt_workbench.py calls the existing workbench_service. A QObject worker in QThread emits progress/log/result signals; cancellation remains cooperative. Separate qt_widgets.py contains the QPainter 3D canvas, independent pallet playback cards and metric cards. gui.py defaults to Qt without silently falling back to Tk.
**Tech:** Python3.13, PyQt5; optional DEAP for paper mode. No Matplotlib/Pillow requirement for display/export.

## Task boundaries and shared interfaces

- [x] Add tests for actual Qt startup, JSON/WCS reading, worker calculation/cancel/close, filtering, pagination and old-result identity.
- [x] qt_widgets.py: PalletCanvas(QWidget) exposes render(pallet,step=None,color_mode='box',labels=False), reset_view(), selected signal; PalletCard(pallet,parent=None) exposes selected(int), expand_requested(int), step, playing, timer, canvas, play/pause/reset/final/next/previous/set_selected. MetricCard(title,foot='',tint=False,parent=None).set_value(str). Export WORKBENCH_STYLE QSS. Independent widget implementation/test domain.
- [x] qt_workbench.py: main Qt window, two-level dark header, left status/filter/global metrics, 2x2 pallet overview, right current-pallet metrics, tables/detail/audit and collapsible log. Main window version0.4.0 PyQt5.
- [x] Switch gui.launch_gui and visualize viewer to Qt; install Qt in the actual E:/program/python3.13 interpreter. Preserve old Tk module as historical source, not default.
- [x] Run backend + Qt tests and render the real widget layout with sample data for visual checking; independent review of threading/data consistency.
- [x] Back up and sync only needed E-drive files, run actual Qt GUI worker smoke test and package.

Review focus: queued GUI updates only, timer cleanup, close while worker runs, unchanged result on bad import/cancel, default paper mode, explicit WCS dimensions, no hidden order filtering or fabricated metrics.

Verification: 110 tests pass in Python3.13.7, PyQt5.15.11/Qt5.15.2. Real Qt worker packs9 sampleboxes (8Phase1+1GA); main-entry subprocess forbidsTkinter and confirms QMainWindow. Actual Qt widget renders reviewed at1920x1080,1600x960,1120x720; screenshots of the user's desktop are not claimed. Independent review found malformed optional result fields could break import atomicity; weights/types now validated before accepting a result, with reproduced red-to-green regression. Existing-result load explicitly resets stale runtime/progress text.

E-drive verification completed: default paper mode, real Qt thread,9/9packed,8layer+1GA, noTkimport; backup_before_pyqt5_20261029_170500_166. Existing algorithm sources were not replaced; only GUI/dependency/docs/tests/validation-related files were synced. Package: ananno2024_pyqt5_workbench.zip.
