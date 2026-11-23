"""用指定 Python 的真实 Tk 事件循环验证工作台，不需要第三方包。"""
import json
import sys
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ananno_phase2.tk_workbench import PackingWorkbench


def main():
    root = tk.Tk()
    root.withdraw()
    window = PackingWorkbench(root,ROOT,default_algorithm="基础模式")
    target = ROOT/"output"/"native_workbench_validation"
    target.mkdir(parents=True,exist_ok=True)
    window.output_dir.set(str(target/"results"))
    window.load_input_file(ROOT/"data"/"Dataset1000.csv")
    window.order_combo.set("35430")
    window.update_input_summary()
    window.start_packing()
    deadline = time.monotonic()+60
    while window.worker is not None and time.monotonic()<deadline:
        root.update()
        time.sleep(.01)
    if window.worker is not None:
        window.stop_packing()
        while window.worker is not None:
            root.update()
            time.sleep(.01)
        raise RuntimeError("装箱计算超时")
    if window.result_path is None:
        raise RuntimeError("\n".join(window.log_lines))
    window.focus_pallet(1)
    window.reset_animation()
    for _ in range(12):
        window.next_step()
    root.update()
    unexpected = sorted(m for m in ("PyQt5","matplotlib","numpy","PIL") if m in sys.modules)
    report = {"python_executable":sys.executable,"python_version":sys.version,
        "gui":"tkinter","third_party_graphics_imported":unexpected,
        "summary":window.document["summary"],"result_path":str(window.result_path),
        "coordinate_rows":len(window.box_table.get_children()),
        "unplaced_rows":len(window.unplaced_table.get_children()),
        "status":window.status.get(),"playback_step_checked":window.step}
    assert not unexpected,unexpected
    assert window.step==12
    (target/"validation_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    (target/"run.log").write_text("\n".join(window.log_lines),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    window.destroy()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
