"""按默认启动路径验证GUI实际调用论文算法，而非只检查下拉框。"""
import json
import sys
import time
import tkinter as tk
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ananno_phase2.tk_workbench import PackingWorkbench


def main():
    root=tk.Tk()
    root.withdraw()
    window=PackingWorkbench(root,ROOT)
    folder=ROOT/"output/default_mode_validation"
    folder.mkdir(parents=True,exist_ok=True)
    try:
        assert window.algorithm.get()=="论文两阶段"
        window.output_dir.set(str(folder/"results"))
        window.load_input_file(ROOT/"examples/paper_two_phase.json")
        window.start_packing()
        deadline=time.monotonic()+15
        while window.worker and time.monotonic()<deadline:
            root.update()
            time.sleep(.01)
        assert window.worker is None,"默认模式计算超时"
        assert window.document is not None,"\n".join(window.log_lines)
        audit=window.document["paper_diagnostics"]
        assert audit["phase1"]["phase1_box_count"]==8
        assert audit["residual_box_count"]==1
        assert audit["all_hard_constraints_pass"]
        report={"python":sys.executable,"title":root.title(),"selected_mode":window.algorithm.get(),
                "banner":window.mode_banner.get(),"visible_result_summary":window.result_summary.get(),
                "summary":window.document["summary"],"result":str(window.result_path)}
        (folder/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        if window.worker:
            window.stop_packing()
            while window.worker:
                root.update()
                time.sleep(.01)
        window.destroy()


if __name__=="__main__": main()
