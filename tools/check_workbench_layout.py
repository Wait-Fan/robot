"""检查真实 Tk 控件边界；透明测试窗口不会遮挡用户工作。"""
import json
import sys
import tkinter as tk
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ananno_phase2.tk_workbench import PackingWorkbench
from ananno_phase2.ui_widgets import ActionButton

root=tk.Tk()
root.attributes("-alpha",0)
window=PackingWorkbench(root,ROOT)
report=ROOT/"output/native_workbench_validation/validation_report.json"
if report.exists():
    window.load_result_file(json.loads(report.read_text(encoding="utf-8"))["result_path"])

def descendants(parent):
    for child in parent.winfo_children():
        yield child
        yield from descendants(child)

checks=[]
try:
    for width,height in ((1456,764),(1366,768),(1120,680)):
        root.geometry(f"{width}x{height}+0+0")
        for tab in (0,window.tabs.index(window.detail_tab)):
            window.tabs.select(tab)
            root.update()
            violations=[]
            for widget in descendants(root):
                if not widget.winfo_ismapped():
                    continue
                if isinstance(widget,ActionButton):
                    parent=widget.master
                    if widget.winfo_x()<0 or widget.winfo_x()+widget.winfo_width()>parent.winfo_width()+1:
                        violations.append(f"按钮超出父区域：{widget._text}")
                    if widget.winfo_width()<widget._font.measure(widget._text)+14:
                        violations.append(f"按钮文字被压缩：{widget._text}")
            checks.append({"size":f"{width}x{height}","tab":tab,
                           "workspace_width":window.tabs.winfo_width(),"violations":violations})
    output=ROOT/"output/native_workbench_validation/layout_report.json"
    output.write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(checks,ensure_ascii=False,indent=2))
    assert not any(check["violations"] for check in checks)
finally:
    window.destroy()
