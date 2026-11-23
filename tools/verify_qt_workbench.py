"""运行真实Qt工作线程，导出该应用自身的离屏布局用于视觉检查。"""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from PyQt5 import QtCore as C,QtGui as G,QtWidgets as W
from ananno_phase2.qt_workbench import PackingWorkbench,APP_VERSION


def main():
    app=W.QApplication.instance() or W.QApplication([])
    app.setStyle("Fusion")
    # Windows离屏插件不枚举系统字体，显式载入仅用于本脚本的排版验证。
    fonts=[]
    if not G.QFontDatabase().families():
        for name in ("msyh.ttc","segoeui.ttf","seguisb.ttf"):
            path=Path("C:/Windows/Fonts")/name
            if path.exists():
                identifier=G.QFontDatabase.addApplicationFont(str(path))
                fonts.extend(G.QFontDatabase.applicationFontFamilies(identifier))
    folder=ROOT/"output/qt_workbench_validation";folder.mkdir(parents=True,exist_ok=True)
    window=PackingWorkbench(ROOT)
    try:
        window.output_dir=folder/"results"
        window.load_input_file(ROOT/"examples/paper_two_phase.json")
        window.show()
        window.start_packing()
        deadline=time.monotonic()+20
        while window.running and time.monotonic()<deadline:
            app.processEvents();time.sleep(.005)
        assert not window.running,"Qt工作线程超时"
        assert window.document is not None,"\n".join(window.log_lines)
        summary=window.document["summary"]
        audit=window.document["paper_diagnostics"]
        assert summary["packed_box_count"]==9
        assert audit["phase1"]["phase1_box_count"]==8 and audit["residual_box_count"]==1
        assert audit["all_hard_constraints_pass"]
        assert "tkinter" not in sys.modules
        report={"python":sys.executable,"gui":"PyQt5","version":APP_VERSION,"pyqt":C.PYQT_VERSION_STR,
            "qt":C.QT_VERSION_STR,"render_platform":app.platformName(),"application_fonts":fonts,
            "default_mode":window.mode_combo.currentText(),"paper_worker_summary":summary,
            "phase1_boxes":8,"ga_boxes":1,"result":str(window.result_path),"tkinter_imported":False,"renders":[]}
        # 用已完成的真实WCS基础模式结果检验四宫格排版，不冒称论文整单新结果。
        preview=ROOT/"output/wcs_import_validation/raw2147_basic_full/order_全部箱子_plan.json"
        if preview.exists():
            window.mode_combo.setCurrentText("基础模式")
            window.load_input_file(ROOT/"examples/imported/20260720_171800_all_uniform_pallet.json")
            window.load_result_file(preview)
        for width,height in ((1920,1080),(1600,960),(1120,720)):
            window.resize(width,height)
            for _ in range(3):app.processEvents()
            path=folder/f"qt_workbench_{width}x{height}.png"
            assert window.grab().save(str(path))
            report["renders"].append(str(path))
        (folder/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        (folder/"run.log").write_text("\n".join(window.log_lines),encoding="utf-8")
        print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        if window.running:
            window.stop_packing()
            while window.running:app.processEvents();time.sleep(.005)
        window.close();window.deleteLater();app.processEvents()


if __name__=="__main__":main()
