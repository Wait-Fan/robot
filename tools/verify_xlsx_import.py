"""通过真实 Qt 工作线程验证 Excel 导入，不改写输入表。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PyQt5 import QtWidgets as W
from ananno_phase2.qt_workbench import APP_VERSION, PackingWorkbench
from ananno_phase2.workbench_service import load_result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--algorithm", choices=("basic", "paper"), default="paper")
    parser.add_argument("--timeout", type=float, default=240)
    args = parser.parse_args()
    before = hashlib.sha256(args.input.read_bytes()).hexdigest()
    app = W.QApplication.instance() or W.QApplication([])
    window = PackingWorkbench(ROOT)
    folder = ROOT / "output/xlsx_validation" / args.algorithm
    folder.mkdir(parents=True, exist_ok=True)
    window.output_dir = folder / "results"
    try:
        window.mode_combo.setCurrentText("论文两阶段" if args.algorithm == "paper" else "基础模式")
        window.load_input_file(args.input)
        info = window.input_info
        assert info["kind"] == "xlsx"
        assert info["pallet"] is not None, "此验证脚本要求文件含统一托盘尺寸"
        window.start_packing()
        deadline = time.monotonic() + args.timeout
        while window.running and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.01)
        if window.running:
            window.stop_packing()
            raise TimeoutError(f"Excel {args.algorithm} 模式验证超时，已请求取消")
        assert window.document is not None, "\n".join(window.log_lines)
        doc = load_result(window.result_path)
        count = info["summaries"]["全部箱子"]["boxes"]
        assert doc["summary"]["input_box_count"] == count
        assert before == hashlib.sha256(args.input.read_bytes()).hexdigest()
        report = {"version": APP_VERSION, "python": sys.executable, "input": str(args.input),
            "input_sha256_unchanged": before, "input_info": info, "algorithm": args.algorithm,
            "summary": doc["summary"], "result": str(window.result_path), "status": window.status_label.text()}
        if args.algorithm == "paper":
            audit = doc["paper_diagnostics"]
            report.update(phase1_boxes=audit["phase1"]["phase1_box_count"],
                          residual_boxes=audit["residual_box_count"],
                          hard_constraints_pass=audit["all_hard_constraints_pass"])
            assert report["hard_constraints_pass"]
        (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        if window.running:
            window.stop_packing()
            while window.running:
                app.processEvents(); time.sleep(.01)
        (folder / "run.log").write_text("\n".join(window.log_lines), encoding="utf-8")
        window.close(); window.deleteLater(); app.processEvents()


if __name__ == "__main__": main()
