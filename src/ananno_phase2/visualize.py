from pathlib import Path

from .io import write_packing_plan_json
from .models import PackingResult, Pallet
from .native_scene import save_overview


def plot_result(result: PackingResult, pallet: Pallet, output_path: str | Path | None = None,
                show: bool = True,document=None) -> None:
    """PNG使用标准库生成；交互查看使用PyQt5。"""
    document = document if document is not None else write_packing_plan_json(None,result)
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True,exist_ok=True)
        save_overview(document,target)
    if show:
        from PyQt5 import QtWidgets as W
        from .qt_workbench import PackingWorkbench
        app=W.QApplication.instance() or W.QApplication([])
        app.setStyle("Fusion")
        window = PackingWorkbench()
        window.display_document(document)
        window.show()
        app.exec_()
