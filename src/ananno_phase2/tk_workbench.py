"""仅使用 Python 标准库的本地装箱工作台。"""
from __future__ import annotations

import csv
import gc
import json
import math
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .native_scene import project_scene
from .ui_widgets import ActionButton, Card
from .pallet_card import PalletCard
from .paper_config import PaperConfig
from .workbench_service import PackingCancelled, finite_number, inspect_input, load_result, run_packing_job

BACKGROUND = "#f3f6fa"
WHITE = "#ffffff"
TEXT = "#1e293b"
MUTED = "#64748b"
APP_VERSION = "0.3.2"


class ScrollFrame(ttk.Frame):
    def __init__(self, parent, width=None):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, background=BACKGROUND, highlightthickness=0,
                                width=width or 400)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.body = ttk.Frame(self.canvas)
        self.item = self.canvas.create_window((0,0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.item, width=event.width))


class PalletCanvas(tk.Canvas):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, background="#f8fafc", highlightthickness=0, **kwargs)
        self.pallet = None
        self.step = None
        self.yaw, self.pitch, self.zoom = 35, 28, 1
        self.color_mode, self.labels = "box", False
        self._mouse = None
        self._draw_id = None
        self.bind("<Configure>", self.schedule_draw)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<MouseWheel>", self._wheel)

    def _press(self, event):
        self._mouse = (event.x,event.y)

    def _drag(self, event):
        if self._mouse:
            self.yaw += (event.x-self._mouse[0])*.5
            self.pitch = max(5,min(85,self.pitch+(event.y-self._mouse[1])*.4))
            self._mouse = (event.x,event.y)
            self.schedule_draw()

    def _wheel(self, event):
        self.zoom = max(.35,min(3,self.zoom*(1.1 if event.delta>0 else 1/1.1)))
        self.schedule_draw()

    def reset_view(self):
        self.yaw,self.pitch,self.zoom = 35,28,1
        self.schedule_draw()

    def render(self, pallet, *, step=None, color_mode="box", labels=False):
        self.pallet,self.step,self.color_mode,self.labels = pallet,step,color_mode,labels
        self.schedule_draw()

    def schedule_draw(self, event=None):
        if self._draw_id is None:
            self._draw_id = self.after_idle(self.draw_scene)

    def draw_scene(self):
        self._draw_id = None
        self.delete("all")
        width,height = max(self.winfo_width(),200),max(self.winfo_height(),80)
        if not self.pallet:
            self.create_text(width/2,height/2,text="等待装箱结果",fill=MUTED,font=("Microsoft YaHei UI",12))
            return
        polygons,lines,texts = project_scene(self.pallet,width,height,step=self.step,
            yaw=self.yaw,pitch=self.pitch,zoom=self.zoom,color_mode=self.color_mode,labels=self.labels,
            palette=("#ff3434","#00e844","#ff8500","#00e5eb","#a63fff","#ff27ec","#ffdf00","#348bff"))
        for start,end in lines:
            self.create_line(*start,*end,fill="#cbd5e1",dash=(3,3))
        for _,points,color in polygons:
            self.create_polygon(*[v for point in points for v in point],fill=color,outline="white",width=1)
        for x,y,text in texts:
            self.create_text(x,y,text=text,fill=TEXT,font=("Segoe UI",8))

    def destroy(self):
        if self._draw_id:
            self.after_cancel(self._draw_id)
            self._draw_id = None
        super().destroy()


class PackingWorkbench:
    def __init__(self, root, project_dir=None,*,default_algorithm="论文两阶段"):
        if default_algorithm not in ("基础模式","论文两阶段"):
            raise ValueError("未知默认算法模式")
        self.root = root
        self.project_dir = Path(project_dir or Path(__file__).resolve().parents[2])
        self.input_path = self.input_info = self.document = self.result_path = None
        self.worker = None
        self.cancel_event = threading.Event()
        self.events = queue.Queue()
        self._completed = False
        self._alive = True
        self._close_pending = False
        self._poll_id = self._play_id = None
        self._fit_id = None
        self.playing = False
        self.step, self.page = 0,0
        self._progress_bucket = -1
        self._history_paths = {}
        self._controls = []
        self.overview_cards = []
        self.root.title(f"Ananno 2024 · 两阶段研究版 v{APP_VERSION} · 三维装箱工作台")
        width = min(1520,self.root.winfo_screenwidth()-80)
        height = min(920,self.root.winfo_screenheight()-100)
        self.root.geometry(f"{width}x{height}+40+30")
        self.root.minsize(1120,680)
        self.root.configure(background=BACKGROUND)
        self.root.protocol("WM_DELETE_WINDOW",self.close)
        self.status = tk.StringVar(value="空闲")
        self.file_name = tk.StringVar(value="尚未选择文件")
        self.input_summary = tk.StringVar(value="支持论文 CSV、普通箱体 CSV 和精简 JSON。")
        self.dimensions = [tk.StringVar(value=str(v)) for v in (1200,800,1400)]
        self.support = tk.StringVar(value="1.0")
        self.algorithm = tk.StringVar(value=default_algorithm)
        self.method_note = tk.StringVar(value="")
        self.mode_banner = tk.StringVar(value="")
        self.result_summary = tk.StringVar(value="尚未加载结果")
        self.paper_parameters={name:tk.StringVar(value=str(value)) for name,value in
            (("pallet_weight",25),("com_deviation_fraction",.25),("corner_inset_fraction",.01),("seed",42))}
        self.output_dir = tk.StringVar(value=str(self.project_dir/"output"))
        self.progress_text = tk.StringVar(value="等待运行")
        self.page_text = tk.StringVar(value="0 / 0")
        self.step_text = tk.StringVar(value="0 / 0 箱")
        self.speed = tk.StringVar(value="450")
        self.labels = tk.BooleanVar(value=False)
        self.current_info = tk.StringVar(value="等待装箱结果")
        self.result_info = tk.StringVar(value="尚未加载结果")
        self.search = tk.StringVar(value="")
        self._applied_search = ""
        self.filter_count = tk.StringVar(value="结果  可选托盘：0")
        self.selected_title = tk.StringVar(value="等待装箱")
        self.selected_subtitle = tk.StringVar(value="选择文件后点击一键装箱")
        self.metrics = {}
        self.pallet_metrics = {}
        self.last_log = tk.StringVar(value="工作台已就绪")
        self.log_lines = []
        self._style()
        self._build()
        self.algorithm.trace_add("write",self.algorithm_changed)
        self.algorithm_changed()
        self.refresh_history()
        self.refresh_overview()
        self._log(f"研究版 v{APP_VERSION} 已就绪；当前计算模式：{self.algorithm.get()}。")
        self._poll_id = self.root.after(40,self._drain_events)

    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".",font=("Microsoft YaHei UI",10),foreground=TEXT)
        style.configure("TFrame",background=BACKGROUND)
        style.configure("TLabel",background=BACKGROUND)
        style.configure("White.TFrame",background=WHITE)
        style.configure("White.TLabel",background=WHITE)
        style.configure("Muted.TLabel",background=WHITE,foreground=MUTED,font=("Microsoft YaHei UI",9))
        style.configure("Section.TLabel",background=WHITE,foreground="#27364b",font=("Microsoft YaHei UI",10,"bold"))
        style.configure("Metric.TLabel",background=WHITE,foreground="#111827",font=("Segoe UI",27,"bold"))
        style.configure("White.TLabelframe",background=WHITE,borderwidth=1,relief="solid")
        style.configure("White.TLabelframe.Label",background=BACKGROUND,foreground="#475569",font=("Microsoft YaHei UI",9,"bold"))
        style.configure("TButton",padding=(10,7),background="#e2e8f0",borderwidth=0)
        style.configure("Blue.TButton",background="#2563eb",foreground=WHITE)
        style.map("Blue.TButton",background=[("active","#1d4ed8"),("disabled","#94a3b8")])
        style.configure("Dark.TButton",background="#334155",foreground=WHITE)
        style.configure("Danger.TButton",background="#b91c1c",foreground=WHITE)
        style.configure("TNotebook",background=BACKGROUND,borderwidth=0)
        style.configure("TNotebook.Tab",padding=(18,12),background="#e8edf4",borderwidth=0,font=("Microsoft YaHei UI",10))
        style.map("TNotebook.Tab",background=[("selected",WHITE)],foreground=[("selected","#1d4ed8")])
        style.configure("Treeview",rowheight=34,background=WHITE,fieldbackground=WHITE,borderwidth=0)
        style.configure("Treeview.Heading",padding=(10,10),background="#edf2f8",foreground="#52637a",font=("Microsoft YaHei UI",9,"bold"),relief="flat")
        style.configure("TEntry",fieldbackground="#f8fafc",bordercolor="#dbe3ed",lightcolor="#dbe3ed",darkcolor="#dbe3ed",padding=(9,8),borderwidth=1)
        style.configure("TCombobox",fieldbackground=WHITE,background="#f8fafc",bordercolor="#dbe3ed",lightcolor="#dbe3ed",darkcolor="#dbe3ed",padding=(9,7),arrowsize=12,borderwidth=1)
        style.configure("Compact.TCombobox",padding=(4,2),arrowsize=10)
        style.map("TCombobox",fieldbackground=[("readonly",WHITE),("disabled","#f1f5f9")],foreground=[("disabled","#94a3b8")])
        style.configure("Dark.TCombobox",fieldbackground="#263244",background="#263244",foreground="#e5e7eb",arrowcolor="#b7c5d9",bordercolor="#3a4a60",lightcolor="#3a4a60",darkcolor="#3a4a60")
        style.map("Dark.TCombobox",fieldbackground=[("readonly","#263244")],selectbackground=[("readonly","#263244")],selectforeground=[("readonly","#e5e7eb")])
        style.configure("TProgressbar",background="#60a5fa",troughcolor="#e2e8f0")

    @staticmethod
    def label(parent,text=None,variable=None,muted=False,wrap=220):
        widget = ttk.Label(parent,text=text,textvariable=variable,
            style="Muted.TLabel" if muted else "White.TLabel",wraplength=wrap,justify="left")
        widget.pack(fill="x",pady=4)
        return widget

    @staticmethod
    def group(parent,title):
        card = Card(parent,title=title)
        card.pack(fill="x",pady=(0,14))
        return card.content

    def _build(self):
        self.root.columnconfigure(1,weight=1)
        self.root.rowconfigure(1,weight=1)
        self._build_header()
        left = ScrollFrame(self.root,width=245)
        left.grid(row=1,column=0,sticky="nsew",padx=(10,4),pady=10)
        self._build_left(left.body)
        self.tabs = ttk.Notebook(self.root)
        self.tabs.grid(row=1,column=1,sticky="nsew",pady=10)
        self._build_center()
        right = ScrollFrame(self.root,width=245)
        right.grid(row=1,column=2,sticky="nsew",padx=(4,10),pady=10)
        self._build_right(right.body)
        self._build_log()

    def _build_header(self):
        header = tk.Frame(self.root,background="#111827",padx=18,pady=12)
        header.grid(row=0,column=0,columnspan=3,sticky="ew")
        top = tk.Frame(header,background="#111827")
        top.pack(fill="x")
        brand = tk.Frame(top,bg="#111827")
        brand.pack(side="left",fill="x",expand=True)
        tk.Label(brand,text="Ananno 2024 智能装箱规划系统",background="#111827",foreground=WHITE,
            font=("Microsoft YaHei UI",18,"bold"),anchor="w").pack(fill="x")
        tk.Label(brand,text="一键装箱 · 结果分析 · 托盘切换 · 逐箱回放",background="#111827",foreground="#94a3b8",
            font=("Microsoft YaHei UI",9),anchor="w").pack(fill="x",pady=(3,0))
        actions = tk.Frame(top,bg="#111827")
        actions.pack(side="right",padx=(10,0))
        self.input_button = ActionButton(actions,text="选择文件",command=self.choose_input,style="Dark.TButton")
        self.start_button = ActionButton(actions,text="一键装箱",command=self.start_packing,style="Blue.TButton")
        self.stop_button = ActionButton(actions,text="停止",command=self.stop_packing,style="Danger.TButton",state="disabled")
        self.status_badge = tk.Label(top,textvariable=self.status,background="#dcfce7",foreground="#166534",
            padx=19,pady=6,font=("Microsoft YaHei UI",10,"bold"))
        self.status_badge.pack(in_=actions,side="left",padx=(0,8))
        for widget in (self.input_button,self.start_button,self.stop_button):
            widget.pack(side="left",padx=(0,6))
        self.status.trace_add("write",self._paint_status)
        self._paint_status()
        bar = tk.Frame(header,background="#1b2637",highlightbackground="#344155",highlightthickness=1,padx=10,pady=7)
        bar.pack(fill="x",pady=(12,0))
        tk.Label(bar,text="运行",bg="#1b2637",fg="#94a3b8",font=("Microsoft YaHei UI",9)).pack(side="left",padx=(0,8))
        tk.Label(bar,text="文件单次运行",bg="#111827",fg="#dbeafe",padx=12,pady=7,
                 font=("Microsoft YaHei UI",9)).pack(side="left")
        tk.Label(bar,text="  范围  ",bg="#1b2637",fg="#94a3b8",font=("Microsoft YaHei UI",9)).pack(side="left")
        self.order_combo = ttk.Combobox(bar,state="disabled",width=12,style="Dark.TCombobox")
        self.order_combo.pack(side="left",padx=(0,8))
        self.order_combo.bind("<<ComboboxSelected>>",lambda event:self.update_input_summary())
        self.mode_combo=ttk.Combobox(bar,state="readonly",textvariable=self.algorithm,
                                   values=["基础模式","论文两阶段"],width=11,style="Dark.TCombobox")
        self.mode_combo.pack(side="left",padx=(0,8))
        self.settings_button = ActionButton(bar,text="装箱设置 ▾",command=self.show_settings,style="Dark.TButton")
        self.settings_button.pack(side="left",padx=(0,6))
        self.open_button = ActionButton(bar,text="打开结果",command=self.choose_result,style="Dark.TButton")
        self.open_button.pack(side="left",padx=(0,8))
        self.history = ttk.Combobox(bar,state="readonly",width=20,style="Dark.TCombobox")
        self.history.pack(side="right",fill="x",expand=True)
        self.history.bind("<<ComboboxSelected>>",self._open_history)
        tk.Label(bar,text="历史结果  ",background="#1b2637",foreground="#94a3b8",font=("Microsoft YaHei UI",9)).pack(side="right")
        self._controls.extend((self.input_button,self.start_button,self.open_button,self.settings_button,self.history,self.mode_combo))
        tk.Label(header,textvariable=self.mode_banner,bg="#172554",fg="#bfdbfe",anchor="w",
                 font=("Microsoft YaHei UI",9,"bold"),padx=10,pady=6).pack(fill="x",pady=(7,0))

    def _paint_status(self,*args):
        state = self.status.get()
        if state in ("已完成","已加载"):
            fill,foreground = "#dcfce7","#166534"
        elif state=="运行失败":
            fill,foreground = "#fee2e2","#991b1b"
        elif state in ("正在停止","已停止"):
            fill,foreground = "#fef3c7","#92400e"
        elif state in ("计算中","正在载入"):
            fill,foreground = "#2563eb","white"
        else:
            fill,foreground = "#334155","#e2e8f0"
        self.status_badge.configure(background=fill,foreground=foreground)

    def _build_left(self, parent):
        tk.Label(parent,textvariable=self.file_name,bg=BACKGROUND,fg=MUTED,anchor="w",
                 font=("Microsoft YaHei UI",8),wraplength=225).pack(fill="x",pady=(0,5))
        status = Card(parent,title="1  运行状态",fill="#f0fdf4",border="#86efac",padding=10)
        status.pack(fill="x",pady=(0,6))
        tk.Label(status.content,textvariable=self.progress_text,bg="#f0fdf4",fg=MUTED,
                 font=("Microsoft YaHei UI",9),anchor="w",wraplength=215).pack(fill="x")
        tk.Label(status.content,textvariable=self.result_summary,bg="#f0fdf4",fg="#166534",
                 font=("Microsoft YaHei UI",9),anchor="w",justify="left",wraplength=215).pack(fill="x",pady=(5,0))
        self.progress = ttk.Progressbar(parent,maximum=100)
        self.progress.pack(fill="x",pady=(0,8))
        box = self.group(parent,"2  筛选托盘")
        self.label(box,variable=self.input_summary,muted=True,wrap=215)
        line = tk.Frame(box,bg="white")
        line.pack(fill="x",pady=3)
        tk.Label(line,text="托盘",bg="white",fg=TEXT).pack(side="left",padx=(0,6))
        self.pallet_filter = ttk.Combobox(line,state="readonly",values=["全部托盘"],width=12)
        self.pallet_filter.set("全部托盘")
        self.pallet_filter.pack(side="left",fill="x",expand=True)
        self.pallet_filter.bind("<<ComboboxSelected>>",lambda event:self.filter_changed())
        self.label(box,"搜索托盘 / 箱体 ID / 箱型",muted=True)
        entry = ttk.Entry(box,textvariable=self.search,width=15)
        entry.pack(fill="x",pady=(0,5))
        entry.bind("<Return>",lambda event:self.filter_changed())
        ActionButton(box,text="筛选",command=self.filter_changed,style="Mini.TButton").pack(fill="x")
        self.label(box,variable=self.filter_count,muted=True)
        grid = tk.Frame(parent,bg=BACKGROUND)
        grid.pack(fill="x")
        for col in (0,1): grid.columnconfigure(col,weight=1,uniform="stats")
        for i,(key,title,fill,border) in enumerate((
            ("pallet_count","总托盘数","white","#e1e7ef"),
            ("packed_box_count","已装箱数","#f0fdf4","#86efac"),
            ("unplaced_box_count","未装箱数","#fff1f2","#fda4af"),
            ("volume_utilization","总体填充率","#fffbeb","#fde68a"))):
            var = tk.StringVar(value="—")
            self.metrics[key] = var
            self.metric_card(grid,title,var,fill,border).grid(row=i//2,column=i%2,sticky="nsew",padx=3,pady=3)
        box = self.group(parent,"输入与结果")
        self.label(box,variable=self.result_info,muted=True,wrap=215)
        ActionButton(box,text="导出坐标 CSV",command=self.export_csv).pack(fill="x",pady=3)
        ActionButton(box,text="打开结果目录",command=self.open_output_folder).pack(fill="x",pady=3)
        self.label(box,variable=self.method_note,muted=True,wrap=215)

    def algorithm_changed(self,*args):
        self.method_note.set("论文两阶段研究实现\n层/块 + GA + EP\n参数假设与约束记录见结果。" if self.algorithm.get()=="论文两阶段" else
                             "Phase 2 阶段性复现\n固定序列 + 简化 EP\n尚未包含全部论文约束。")
        self.update_input_summary()
        self.refresh_result_identity()

    def refresh_result_identity(self):
        selected=self.algorithm.get()
        if self.document is None:
            loaded="尚无结果"
            self.result_summary.set("尚未计算；请选择文件后点击一键装箱。")
        else:
            audit=self.document.get("paper_diagnostics")
            if isinstance(audit,dict) and audit:
                loaded="论文两阶段"
                phase1=audit.get("phase1",{})
                count=phase1.get("phase1_box_count","—") if isinstance(phase1,dict) else "—"
                residual=audit.get("residual_box_count","—")
                check="6 项硬约束通过" if audit.get("all_hard_constraints_pass") else "硬约束状态见记录"
                self.result_summary.set(f"结果：论文两阶段\n层/块 {count} 箱 · GA 剩余箱 {residual} 箱\n文件记录：{check}")
            else:
                loaded="基础模式"
                self.result_summary.set("结果：基础模式\n固定序列 + 简化 EP\n未执行层/块与 GA。")
        mismatch="  ｜ 模式不同，需重新计算" if self.document is not None and selected!=loaded else ""
        self.mode_banner.set(f"v{APP_VERSION}  当前计算：{selected}  ｜ 当前结果：{loaded}{mismatch}")

    @staticmethod
    def metric_card(parent,title,var,fill="white",border="#e1e7ef",foot=""):
        card = Card(parent,padding=10,fill=fill,border=border)
        tk.Label(card.content,text=title,bg=fill,fg="#64748b",font=("Microsoft YaHei UI",8),anchor="w").pack(fill="x")
        tk.Label(card.content,textvariable=var,bg=fill,fg="#111827",font=("Segoe UI",20,"bold"),anchor="w").pack(fill="x",pady=3)
        if foot:
            tk.Label(card.content,text=foot,bg=fill,fg="#7c8da8",font=("Microsoft YaHei UI",8),anchor="w").pack(fill="x")
        return card

    def show_settings(self):
        if self.worker:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("装箱设置")
        dialog.geometry("490x650")
        dialog.resizable(False,False)
        dialog.transient(self.root)
        dialog.configure(bg=BACKGROUND)
        host=ScrollFrame(dialog)
        host.pack(fill="both",expand=True,padx=8,pady=8)
        box = self.group(host.body,"基础尺寸与支撑")
        for row,(name,var) in enumerate(zip(("托盘长 / X","托盘宽 / Y","最大高 / Z"),self.dimensions)):
            line = ttk.Frame(box,style="White.TFrame")
            line.pack(fill="x",pady=5)
            ttk.Label(line,text=name,style="White.TLabel",width=11).pack(side="left")
            entry = ttk.Entry(line,textvariable=var,width=12)
            entry.pack(side="right",fill="x",expand=True)
        line = ttk.Frame(box,style="White.TFrame")
        line.pack(fill="x",pady=5)
        ttk.Label(line,text="最小支撑率",style="White.TLabel",width=11).pack(side="left")
        entry = ttk.Entry(line,textvariable=self.support,width=12)
        entry.pack(side="right",fill="x",expand=True)
        self.label(box,"尺寸单位与输入一致。基础模式使用上方面积阈值；论文模式使用40%+4角 / 50%+3角 / 75%+2角组合规则。",muted=True,wrap=410)
        box=self.group(host.body,"论文模式参数（实现假设，可调整）")
        for name,title in (("pallet_weight","空托盘质量"),("com_deviation_fraction","重心偏移比例"),
                           ("corner_inset_fraction","支撑角点内缩比例"),("seed","随机种子")):
            line=tk.Frame(box,bg="white")
            line.pack(fill="x",pady=4)
            tk.Label(line,text=title,bg="white",fg=TEXT,width=19,anchor="w").pack(side="left")
            ttk.Entry(line,textvariable=self.paper_parameters[name],width=12).pack(side="left",fill="x",expand=True)
        self.label(box,"这些默认数值不是作者公开的实验原值。质量单位须与箱体一致；重心偏移以托盘长宽为基准。默认倾倒检查仅为准静态重力条件。",muted=True,wrap=410)
        box = self.group(host.body,"保存位置")
        ttk.Entry(box,textvariable=self.output_dir,state="readonly",width=24).pack(fill="x",pady=4)
        choose = ActionButton(box,text="选择保存目录",command=self.choose_output)
        choose.pack(fill="x",pady=5)
        self.label(box,"每次计算独立保存，完成后自动载入结果。",muted=True)
        ActionButton(dialog,text="完成",command=dialog.destroy,style="Blue.TButton").pack(pady=5)
        dialog.grab_set()

    def _build_center(self):
        overview = ttk.Frame(self.tabs,padding=8)
        self.tabs.add(overview,text="3D装箱视图")
        playback = Card(overview,padding=8)
        playback.pack(fill="x",pady=(0,6))
        tk.Label(playback.content,text="播放顺序   统一执行顺序（seq）    ·    拖动旋转 / 滚轮缩放 / 点击联动右侧",
                 bg="white",fg=MUTED,font=("Microsoft YaHei UI",9),anchor="w").pack(fill="x")
        bar = ttk.Frame(overview)
        bar.pack(fill="x",pady=(0,5))
        ttk.Label(bar,text="垛型总览（每页 4 个）",foreground="#991b1b",font=("Microsoft YaHei UI",9,"bold")).pack(side="left")
        ttk.Label(bar,textvariable=self.page_text,foreground=MUTED).pack(side="right",padx=4)
        self.next_page_button = ActionButton(bar,text="下一页",command=lambda:self.change_page(1),style="Mini.TButton")
        self.next_page_button.pack(side="right")
        self.prev_page_button = ActionButton(bar,text="上一页",command=lambda:self.change_page(-1),style="Mini.TButton")
        self.prev_page_button.pack(side="right",padx=4)
        host = ScrollFrame(overview)
        host.pack(fill="both",expand=True)
        self.overview_body = host.body
        self.overview_viewport = host.canvas
        host.canvas.bind("<Configure>",self.fit_overview,add="+")
        self.detail_tab = ttk.Frame(self.tabs,padding=10)
        self.tabs.add(self.detail_tab,text="单托盘 / 播放")
        bar = ttk.Frame(self.detail_tab)
        bar.pack(fill="x")
        self.pallet_combo = ttk.Combobox(bar,state="readonly",width=11)
        self.pallet_combo.pack(side="left")
        self.pallet_combo.bind("<<ComboboxSelected>>",lambda event:self.pallet_changed())
        self.color_combo = ttk.Combobox(bar,state="readonly",values=["按箱子着色","按箱型着色","按高度着色"],width=13)
        self.color_combo.current(0)
        self.color_combo.pack(side="right")
        self.color_combo.bind("<<ComboboxSelected>>",lambda event:self.render_detail())
        ttk.Checkbutton(bar,text="显示序号",variable=self.labels,command=self.render_detail).pack(side="right",padx=8)
        self.detail_canvas = PalletCanvas(self.detail_tab,width=640,height=430)
        self.detail_canvas.pack(fill="both",expand=True,pady=10)
        controls = ttk.Frame(self.detail_tab)
        controls.pack(fill="x")
        self.animation_buttons = []
        for text,callback in (("最终状态",self.final_state),("播放",self.play_animation),("暂停",self.pause_animation),
             ("前一步",self.previous_step),("后一步",self.next_step),("重置",self.reset_animation)):
            widget = ActionButton(controls,text=text,command=callback,width=5)
            widget.pack(side="left",padx=(0,4))
            self.animation_buttons.append(widget)
        ActionButton(controls,text="复位视角",command=self.detail_canvas.reset_view,width=6).pack(side="right")
        line = ttk.Frame(self.detail_tab)
        line.pack(fill="x",pady=8)
        self.slider_value = tk.DoubleVar(value=0)
        self.step_slider = ttk.Scale(line,from_=0,to=0,variable=self.slider_value,command=self._slider_changed)
        self.step_slider.pack(side="left",fill="x",expand=True)
        ttk.Label(line,textvariable=self.step_text).pack(side="right",padx=8)
        bottom = ttk.Frame(self.detail_tab)
        bottom.pack(fill="x")
        ttk.Label(bottom,text="播放间隔 / ms").pack(side="left")
        ttk.Entry(bottom,textvariable=self.speed,width=6).pack(side="left",padx=8)
        ttk.Label(bottom,text="拖动旋转 · 滚轮缩放 · 播放仅展示放置顺序",foreground=MUTED).pack(side="right")
        self.box_table = self._table_tab("箱子列表",["顺序","托盘","箱号","箱型","X","Y","Z","姿态","长","宽","高"])
        self.unplaced_table = self._table_tab("失败列表",["箱号","箱型","长","宽","高","未放置原因"])
        self.tabs.insert(1,self.box_table.master)
        self.tabs.insert(2,self.unplaced_table.master)
        audit_tab=ttk.Frame(self.tabs,padding=8)
        self.tabs.add(audit_tab,text="算法 / 约束记录")
        self.audit_box=tk.Text(audit_tab,wrap="word",font=("Consolas",9),bg="white",fg=TEXT,
                               relief="flat",state="disabled",width=35)
        scrollbar=ttk.Scrollbar(audit_tab,command=self.audit_box.yview)
        self.audit_box.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right",fill="y")
        self.audit_box.pack(fill="both",expand=True)
        self._set_animation_enabled(False)

    def _table_tab(self,title,headings):
        panel = ttk.Frame(self.tabs)
        self.tabs.add(panel,text=title)
        panel.rowconfigure(0,weight=1)
        panel.columnconfigure(0,weight=1)
        table = ttk.Treeview(panel,columns=[str(i) for i in range(len(headings))],show="headings")
        for i,text in enumerate(headings):
            table.heading(str(i),text=text)
            table.column(str(i),width=100 if text in ("箱号","箱型") else (250 if text=="未放置原因" else 65),anchor="w",stretch=True)
        table.grid(row=0,column=0,sticky="nsew")
        vertical = ttk.Scrollbar(panel,orient="vertical",command=table.yview)
        vertical.grid(row=0,column=1,sticky="ns")
        horizontal = ttk.Scrollbar(panel,orient="horizontal",command=table.xview)
        horizontal.grid(row=1,column=0,sticky="ew")
        table.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        table.tag_configure("alternate",background="#f1f5f9")
        return table

    def _build_right(self,parent):
        hero = Card(parent,padding=12)
        hero.pack(fill="x",pady=(0,5))
        self.label(hero.content,"当前托盘",muted=True)
        tk.Label(hero.content,textvariable=self.selected_title,bg="white",fg="#111827",
                 font=("Segoe UI",23,"bold"),anchor="w").pack(fill="x",pady=4)
        tk.Label(hero.content,textvariable=self.selected_subtitle,bg="white",fg=MUTED,
                 font=("Microsoft YaHei UI",8),wraplength=220,anchor="w",justify="left").pack(fill="x")
        grid = tk.Frame(parent,bg=BACKGROUND)
        grid.pack(fill="x")
        for col in (0,1): grid.columnconfigure(col,weight=1,uniform="palletstats")
        for i,(key,title,foot) in enumerate((
            ("box_count","箱子数量","当前托盘"),("types","箱型数量","输入箱型分类"),
            ("fill","填充率","托盘空间利用率"),("height_util","高度利用率","最高箱顶 / 限高"),
            ("height","已用高度","与输入尺寸同单位"),("weight","总重量","输入重量合计"),
            ("volume","已装体积","长 × 宽 × 高合计"),("remaining","剩余体积","容量减去箱体体积"))):
            var = tk.StringVar(value="—")
            self.pallet_metrics[key] = var
            fill = "#f0fdf4" if i not in (4,5) else "white"
            self.metric_card(grid,title,var,fill,"#86efac" if fill!="white" else "#e1e7ef",foot).grid(
                row=i//2,column=i%2,sticky="nsew",padx=3,pady=3)
        box = self.group(parent,"托盘信息")
        self.label(box,variable=self.current_info,muted=True,wrap=215)
        self.label(box,"约束依据请查看“算法 / 约束记录”。两个模式均不计算机械臂可达性或吸盘碰撞。",muted=True,wrap=215)

    def _build_log(self):
        holder = ttk.Frame(self.root)
        holder.grid(row=2,column=0,columnspan=3,sticky="ew",padx=12,pady=(0,8))
        bar = ttk.Frame(holder)
        bar.pack(fill="x")
        ttk.Label(bar,text="运行消息",foreground="#991b1b",font=("Microsoft YaHei UI",9,"bold")).pack(side="left",padx=5)
        self.log_toggle = ActionButton(bar,text="展开日志",command=self.toggle_log,style="Mini.TButton")
        self.log_toggle.pack(side="right",padx=5)
        ttk.Label(bar,textvariable=self.last_log,foreground=MUTED).pack(side="left",padx=10,fill="x",expand=True)
        ActionButton(bar,text="清空",command=self.clear_log,style="Mini.TButton").pack(side="right")
        self.log_box = tk.Text(holder,height=7,background="#172235",foreground="#c5d5ec",
                               font=("Consolas",9),state="disabled",wrap="word",relief="flat")
        ttk.Label(self.root,text="离线装箱 · 本地文件 · 研究实现，尚未验证论文数值等价",foreground=MUTED).grid(row=3,column=0,columnspan=3,sticky="w",padx=12,pady=(0,7))

    def toggle_log(self):
        if self.log_box.winfo_manager():
            self.log_box.pack_forget()
            self.log_toggle.configure(text="展开运行日志")
        else:
            self.log_box.pack(fill="x",pady=(8,0))
            self.log_toggle.configure(text="收起运行日志")

    def clear_log(self):
        self.log_lines.clear()
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0","end")
        self.log_box.configure(state="disabled")

    def _log(self,text):
        line = f"[{datetime.now():%H:%M:%S}] {text}"
        self.log_lines.append(line)
        self.last_log.set(text[:95])
        if self.worker and text.startswith(("Phase 1","Phase 2","GA 第")):
            self.progress_text.set(text)
        self.log_box.configure(state="normal")
        self.log_box.insert("end",line+"\n")
        if len(self.log_lines)>1500:
            self.log_lines.pop(0)
            self.log_box.delete("1.0","2.0")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _error(self,message):
        self.status.set("运行失败")
        self._log("错误："+message)
        if not self._close_pending:
            messagebox.showerror("无法完成操作",message,parent=self.root)

    def choose_input(self):
        path = filedialog.askopenfilename(parent=self.root,title="选择装箱输入",initialdir=self.project_dir,
            filetypes=[("装箱输入","*.csv *.json"),("CSV","*.csv"),("JSON","*.json")])
        if path:
            try:
                self.load_input_file(path)
            except Exception as exc:
                self._error(str(exc))

    def load_input_file(self,path):
        info = inspect_input(path)
        self.input_path,self.input_info = Path(path),info
        self.file_name.set(self.input_path.name)
        self.order_combo.configure(values=list(info["summaries"]),state="readonly" if info["kind"]=="paper" else "disabled")
        self.order_combo.set(next(iter(info["summaries"])))
        if info["pallet"]:
            for var,value in zip(self.dimensions,info["pallet"]):
                var.set(str(value))
        self.update_input_summary()
        self._log(f"已选择输入：{path}")
        if info["kind"]=="wcs_json":
            self._log(f"识别zhuang接口JSON：全部读取，型号记录数{info['case_types']}；所有箱体使用装箱设置中的同一托盘规格。")

    def update_input_summary(self):
        if self.input_info:
            info = self.input_info["summaries"].get(self.order_combo.get())
            if info:
                method="同型成层；剩余箱按箱型排列搜索。" if self.algorithm.get()=="论文两阶段" else "输入行顺序即固定装箱顺序。"
                self.input_summary.set(f"{info['box_types']} 种箱型 · {info['boxes']} 箱\n{method}")
                if self.input_info["kind"]=="wcs_json":
                    self.input_summary.set(self.input_summary.get()+"\n接口JSON全部读取；请确认装箱设置中的统一托盘尺寸。")

    def choose_output(self):
        path = filedialog.askdirectory(parent=self.root,initialdir=self.output_dir.get(),title="选择保存目录")
        if path:
            self.output_dir.set(path)
            self.refresh_history()

    def _busy(self,busy):
        for widget in self._controls:
            widget.configure(state="disabled" if busy else ("readonly" if widget in (self.history,self.mode_combo) else "normal"))
        paper = self.input_info and self.input_info["kind"]=="paper"
        self.order_combo.configure(state="readonly" if not busy and paper else "disabled")
        self.stop_button.configure(state="normal" if busy else "disabled")

    def start_packing(self):
        if self.worker:
            return
        if self.input_path is None:
            messagebox.showinfo("请选择输入","请先选择 CSV 或 JSON 文件。",parent=self.root)
            return
        try:
            dims = [finite_number(v.get(),"托盘尺寸",positive=True) for v in self.dimensions]
            support = 1.0 if self.algorithm.get()=="论文两阶段" else finite_number(self.support.get(),"支撑率")
            if support>1:
                raise ValueError("支撑率必须在 0 到 1 之间")
            options={"algorithm":"basic"}
            if self.algorithm.get()=="论文两阶段":
                parameters={name:float(var.get()) for name,var in self.paper_parameters.items() if name!="seed"}
                parameters["seed"]=int(self.paper_parameters["seed"].get())
                options={"algorithm":"paper","paper_config":PaperConfig(**parameters)}
        except ValueError as exc:
            self._error(str(exc))
            return
        self.pause_animation()
        target = Path(self.output_dir.get())/datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
        args = (self.input_path,self.order_combo.get(),*dims,support,target)
        self.cancel_event = threading.Event()
        self._completed = False
        self._progress_bucket = -1
        self._busy(True)
        self.progress["value"] = 0
        self.progress_text.set("正在读取输入……")
        self.status.set("计算中")
        self._log(f"开始装箱：{self.input_path.name}，范围：{self.order_combo.get()}，算法：{self.algorithm.get()}")
        # Tk 对象必须由主线程析构。先回收此前已销毁窗口的循环引用，
        # 避免工作线程的内存分配触发这些 Tcl 变量在错误线程中被回收。
        gc.collect()
        self.worker = threading.Thread(target=self._run_worker,args=(args,options),daemon=True)
        self.worker.start()

    def _run_worker(self,args,options=None):
        # 工作线程只写队列，禁止从后台线程调用 Tk。
        try:
            result = run_packing_job(*args,**(options or {}),cancelled=self.cancel_event.is_set,
                progress=lambda done,total:self.events.put(("progress",(done,total))),
                log=lambda text:self.events.put(("log",text)))
        except PackingCancelled:
            self.events.put(("stopped",None))
        except Exception as exc:
            self.events.put(("error",str(exc)))
        else:
            self._completed = True
            self.events.put(("done",result))
        finally:
            self.events.put(("finished",None))

    def _drain_events(self):
        self._poll_id = None
        while True:
            try:
                kind,payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind=="progress":
                done,total = payload
                value = int(done*100/total) if total else 100
                self.progress["value"] = min(99,value)
                self.progress_text.set(f"已处理 {done} / {total} 箱"+("，正在保存……" if done==total else ""))
                if value//10 != self._progress_bucket:
                    self._progress_bucket = value//10
                    self._log(f"装箱进度：{done} / {total}")
            elif kind=="log":
                self._log(payload)
            elif kind=="done":
                try:
                    self.load_result_file(payload["paths"]["json"])
                    self.progress["value"] = 100
                    self.progress_text.set(f"完成，用时 {payload['elapsed_seconds']:.2f} 秒")
                    self.status.set("已完成")
                    self.refresh_history()
                    self._log(f"完成：{payload['packed_box_count']} 箱，{payload['pallet_count']} 托盘。")
                except Exception as exc:
                    self._error(str(exc))
            elif kind=="stopped":
                self.status.set("已停止")
                self.progress_text.set("已停止；保留之前加载的结果")
                self._log("已停止，本次未发布完成方案。")
            elif kind=="error":
                self._error(payload)
            elif kind=="finished":
                self.worker = None
                self._busy(False)
                if self._close_pending:
                    self.destroy()
                    return
        if self._alive:
            self._poll_id = self.root.after(40,self._drain_events)

    def stop_packing(self):
        if self.worker:
            if self._completed or not self.worker.is_alive():
                self.status.set("正在载入")
                return
            self.cancel_event.set()
            self.status.set("正在停止")
            self.stop_button.configure(state="disabled")
            self._log("已请求停止，等待当前操作结束。")

    def choose_result(self):
        path = filedialog.askopenfilename(parent=self.root,title="打开装箱方案",initialdir=self.output_dir.get(),filetypes=[("JSON 方案","*.json")])
        if path:
            try:
                self.load_result_file(path)
            except Exception as exc:
                self._error(str(exc))

    def load_result_file(self,path):
        document = load_result(path)
        self.display_document(document,Path(path))

    def display_document(self,document,path=None):
        self.pause_animation()
        self.document,self.result_path = document,path
        self.refresh_result_identity()
        names = [f"托盘 {p['pallet_index']}" for p in document["pallets"]]
        self.pallet_filter.configure(values=["全部托盘"]+names)
        self.pallet_filter.set("全部托盘")
        self.search.set("")
        self._applied_search = ""
        self.pallet_combo.configure(values=names)
        self.pallet_combo.set(names[0] if names else "")
        for key,var in self.metrics.items():
            value = document["summary"][key]
            var.set(f"{value:.1%}" if key=="volume_utilization" else str(value))
        self.result_info.set(f"{path.parent.name}\n{path.name}" if path else "命令行计算结果")
        audit=document.get("paper_diagnostics") or {"mode":"基础模式","implemented":["Z0/Z90","托盘边界","AABB非碰撞","基础支撑面积"],
                   "note":"没有执行论文完整两阶段流程，也未验证论文全部约束。"}
        self.audit_box.configure(state="normal")
        self.audit_box.delete("1.0","end")
        self.audit_box.insert("end",json.dumps(audit,ensure_ascii=False,indent=2))
        self.audit_box.configure(state="disabled")
        self.page = 0
        self.refresh_overview()
        self.refresh_tables()
        self.pallet_changed()
        self.tabs.select(0)
        self.status.set("已加载")
        self._log(f"已加载方案：{path or '当前计算结果'}")

    def refresh_history(self):
        self._history_paths.clear()
        folder = Path(self.output_dir.get())
        candidates = []
        if folder.exists():
            for path in folder.rglob("*.json"):
                if ".packing_" in str(path) or not (path.name.endswith("_plan.json") or path.name.startswith("packing_plan")):
                    continue
                try:
                    candidates.append((path.stat().st_mtime,path))
                except OSError:
                    continue
        for index,(_,path) in enumerate(sorted(candidates,reverse=True)[:100],1):
            self._history_paths[f"{index}. {path.parent.name}/{path.stem}"] = path
        self.history.configure(values=list(self._history_paths))
        self.history.set("选择历史结果…")

    def _open_history(self,event=None):
        path = self._history_paths.get(self.history.get())
        if path:
            try:
                self.load_result_file(path)
            except Exception as exc:
                self._error(str(exc))

    def filtered_pallets(self):
        if not self.document:
            return []
        name = self.pallet_filter.get()
        query = self._applied_search
        return [p for p in self.document["pallets"]
                if (name=="全部托盘" or name==f"托盘 {p['pallet_index']}")
                and (not query or query in f"托盘 {p['pallet_index']} pallet-{p['pallet_index']:03d}".casefold()
                     or any(query in f"{item['id']} {item.get('box_type','')}".casefold() for item in p["packed_items"]))]

    def filter_changed(self):
        self.page = 0
        self._applied_search = self.search.get().strip().casefold()
        if self.pallet_filter.get()!="全部托盘":
            self.pallet_combo.set(self.pallet_filter.get())
            self.pallet_changed()
        self.refresh_overview()
        self.refresh_tables()
        pallets = self.filtered_pallets()
        self.pallet_combo.configure(values=[f"托盘 {p['pallet_index']}" for p in pallets])
        if self.current_pallet() not in pallets:
            self.pallet_combo.set(f"托盘 {pallets[0]['pallet_index']}" if pallets else "")
            self.pallet_changed()

    def change_page(self,delta):
        maximum = max(0,math.ceil(len(self.filtered_pallets())/4)-1)
        self.page = max(0,min(maximum,self.page+delta))
        self.refresh_overview()

    def refresh_overview(self):
        for child in self.overview_body.winfo_children():
            child.destroy()
        self.overview_cards = []
        pallets = self.filtered_pallets()
        pages = math.ceil(len(pallets)/4)
        self.page = min(self.page,max(0,pages-1))
        self.filter_count.set(f"结果  可选托盘：{len(pallets)}")
        self.page_text.set(f"{self.page+1 if pages else 0} / {pages}")
        self.prev_page_button.configure(state="normal" if self.page>0 else "disabled")
        self.next_page_button.configure(state="normal" if self.page+1<pages else "disabled")
        if not pallets:
            ttk.Label(self.overview_body,text="尚无托盘可显示\n\n选择输入文件并开始装箱，或打开已有结果。",
                justify="center",padding=50).grid(row=0,column=0,columnspan=2,sticky="nsew")
            return
        for col in (0,1):
            self.overview_body.columnconfigure(col,weight=1,uniform="cards")
        for i,pallet in enumerate(pallets[self.page*4:self.page*4+4]):
            card = PalletCard(self.overview_body,pallet,PalletCanvas,self.select_overview_pallet,self.focus_pallet)
            card.grid(row=i//2,column=i%2,sticky="nsew",padx=4,pady=4)
            self.overview_cards.append(card)
        self.highlight_selection()
        if self._fit_id:
            self.root.after_cancel(self._fit_id)
        self._fit_id = self.root.after_idle(self.fit_overview)

    def fit_overview(self,event=None):
        if event is None:
            self._fit_id = None
        if not self._alive or not self.overview_cards:
            return
        rows = math.ceil(len(self.overview_cards)/2)
        room = self.overview_viewport.winfo_height()/rows-12
        for card in self.overview_cards:
            chrome = card.content.winfo_reqheight()-int(card.canvas.cget("height"))+2*card.padding
            height = max(100,min(230,int(room-chrome)))
            if int(card.canvas.cget("height"))!=height:
                card.canvas.configure(height=height)

    def select_overview_pallet(self,index):
        if self.pallet_combo.get()!=f"托盘 {index}":
            self.pallet_combo.set(f"托盘 {index}")
            self.pallet_changed()
        self.highlight_selection()

    def highlight_selection(self):
        for card in self.overview_cards:
            card.set_selected(self.pallet_combo.get()==f"托盘 {card.pallet['pallet_index']}")

    def focus_pallet(self,index):
        self.pallet_combo.set(f"托盘 {index}")
        self.pallet_changed()
        self.tabs.select(self.detail_tab)

    def current_pallet(self):
        if self.document:
            return next((p for p in self.document["pallets"] if f"托盘 {p['pallet_index']}"==self.pallet_combo.get()),None)
        return None

    def _set_animation_enabled(self,enabled):
        for widget in self.animation_buttons:
            widget.configure(state="normal" if enabled else "disabled")

    def pallet_changed(self):
        self.pause_animation()
        pallet = self.current_pallet()
        self.step = len(pallet["packed_items"]) if pallet else 0
        self.step_slider.configure(to=self.step)
        self.slider_value.set(self.step)
        self._set_animation_enabled(pallet is not None)
        if pallet:
            dims = pallet["pallet"]
            self.current_info.set(f"托盘 {pallet['pallet_index']}\n{pallet['box_count']} 箱\n利用率 {pallet['volume_utilization']:.1%}\n"
                f"{dims['length']:g} × {dims['width']:g} × {dims['height']:g}")
        else:
            self.current_info.set("没有已装箱托盘")
        self.update_pallet_metrics(pallet)
        self.highlight_selection()
        self.render_detail()

    def update_pallet_metrics(self,pallet):
        if not pallet:
            self.selected_title.set("没有托盘")
            self.selected_subtitle.set("当前筛选下没有已装箱托盘")
            for var in self.pallet_metrics.values(): var.set("—")
            return
        items,dims = pallet["packed_items"],pallet["pallet"]
        height = max((i["position"]["z"]+i["placed_size"]["height"] for i in items),default=0)
        volume = sum(math.prod(i["placed_size"][k] for k in ("length","width","height")) for i in items)
        capacity = math.prod(dims[k] for k in ("length","width","height"))
        weight = sum(i.get("weight",0) or 0 for i in items)
        def box_type(item):
            if item.get("box_type"):
                return ("type",item["box_type"])
            size = item["placed_size"]
            # Z90 还原原始尺寸，避免把同一箱型的两个姿态计成两类。
            length,width = size["length"],size["width"]
            if item.get("orientation")=="Z90": length,width = width,length
            return ("size",length,width,size["height"])
        values = {"box_count":str(len(items)),"types":str(len({box_type(i) for i in items})),
                  "fill":f"{pallet['volume_utilization']:.1%}","height_util":f"{height/dims['height']:.1%}",
                  "height":f"{height:g}","weight":f"{weight:g}" if weight else "未提供 / 0",
                  "volume":f"{volume:.3g}","remaining":f"{max(0,capacity-volume):.3g}"}
        self.selected_title.set(f"PALLET-{pallet['pallet_index']:03d}")
        self.selected_subtitle.set(f"已装 {len(items)} 箱  |  填充率 {pallet['volume_utilization']:.1%}")
        for key,var in self.pallet_metrics.items(): var.set(values[key])

    def render_detail(self):
        pallet = self.current_pallet()
        maximum = len(pallet["packed_items"]) if pallet else 0
        self.step_text.set(f"{self.step} / {maximum} 箱")
        mode = {"按箱子着色":"box","按箱型着色":"type","按高度着色":"height"}.get(self.color_combo.get(),"box")
        self.detail_canvas.render(pallet,step=self.step,color_mode=mode,labels=self.labels.get())

    def _slider_changed(self,value):
        self.step = round(float(value))
        self.render_detail()

    def _set_step(self,value):
        pallet = self.current_pallet()
        maximum = len(pallet["packed_items"]) if pallet else 0
        self.step = max(0,min(maximum,value))
        self.slider_value.set(self.step)
        self.render_detail()

    def play_animation(self):
        self.pause_animation()
        pallet = self.current_pallet()
        if not pallet:
            return
        if self.step>=len(pallet["packed_items"]):
            self._set_step(0)
        self.playing = True
        self._schedule_play()

    def _schedule_play(self):
        try:
            delay = max(100,min(3000,int(self.speed.get())))
        except ValueError:
            delay = 450
        self._play_id = self.root.after(delay,self._tick)

    def _tick(self):
        self._play_id = None
        self.next_step()
        if self.playing:
            self._schedule_play()

    def pause_animation(self):
        self.playing = False
        if self._play_id:
            self.root.after_cancel(self._play_id)
            self._play_id = None

    def reset_animation(self):
        self.pause_animation()
        self._set_step(0)

    def final_state(self):
        self.pause_animation()
        pallet = self.current_pallet()
        self._set_step(len(pallet["packed_items"]) if pallet else 0)

    def previous_step(self):
        self.pause_animation()
        self._set_step(self.step-1)

    def next_step(self):
        self._set_step(self.step+1)
        pallet = self.current_pallet()
        if not pallet or self.step>=len(pallet["packed_items"]):
            self.pause_animation()

    @staticmethod
    def fill_table(table,rows):
        children = table.get_children()
        if children:
            table.delete(*children)
        for index,row in enumerate(rows):
            values = [f"{v:g}" if isinstance(v,float) else str(v) for v in row]
            table.insert("","end",values=values,tags=("alternate",) if index%2 else ())

    def refresh_tables(self):
        rows = []
        for pallet in self.filtered_pallets():
            for item in pallet["packed_items"]:
                rows.append([item["sequence"],pallet["pallet_index"],item["id"],item.get("box_type",""),
                    *(item["position"][axis] for axis in ("x","y","z")),item["orientation"],
                    *(item["placed_size"][key] for key in ("length","width","height"))])
        rows.sort(key=lambda row:row[0])
        self.fill_table(self.box_table,rows)
        failed = self.document["unplaced_items"] if self.document else []
        self.fill_table(self.unplaced_table,[[item["id"],item.get("box_type",""),
            *(item["size"][key] for key in ("length","width","height")),item["reason"]] for item in failed])

    def open_output_folder(self):
        folder = self.result_path.parent if self.result_path else Path(self.output_dir.get())
        folder.mkdir(parents=True,exist_ok=True)
        if hasattr(os,"startfile"):
            os.startfile(folder)

    def export_csv(self):
        if not self.document:
            return
        path = filedialog.asksaveasfilename(parent=self.root,title="导出当前筛选坐标",defaultextension=".csv",filetypes=[("CSV","*.csv")])
        if path:
            try:
                with Path(path).open("w",encoding="utf-8-sig",newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["order","pallet","box_id","box_type","x","y","z","orientation","length","width","height"])
                    writer.writerows(self.box_table.item(item,"values") for item in self.box_table.get_children())
                self._log(f"已导出坐标：{path}")
            except OSError as exc:
                self._error(str(exc))

    def close(self):
        self.pause_animation()
        if self.worker:
            self._close_pending = True
            self.stop_packing()
        else:
            self.destroy()

    def destroy(self):
        if not self._alive:
            return
        self._alive = False
        self.pause_animation()
        for card in self.overview_cards:
            card.pause()
        if self._fit_id:
            self.root.after_cancel(self._fit_id)
            self._fit_id = None
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        self.root.destroy()


def launch_workbench():
    root = tk.Tk()
    PackingWorkbench(root)
    if os.name=="nt":
        root.state("zoomed")
    root.mainloop()
    return 0
