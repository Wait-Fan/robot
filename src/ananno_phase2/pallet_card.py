"""托盘缩略卡片；每张卡片独立播放，销毁时释放定时器。"""
import tkinter as tk
from tkinter import ttk

from .ui_widgets import ActionButton, Card


class PalletCard(Card):
    def __init__(self,parent,pallet,canvas_factory,on_select,on_expand):
        super().__init__(parent,padding=8)
        self.pallet = pallet
        self.on_select = on_select
        self.step = len(pallet["packed_items"])
        self.playing,self.timer = False,None
        self.rate = tk.DoubleVar(self,value=1)
        self.labels = tk.BooleanVar(self,value=False)
        self.caption = tk.StringVar(self)
        top = tk.Frame(self.content,bg="white")
        top.pack(fill="x")
        title = tk.Label(top,text=f"PALLET-{pallet['pallet_index']:03d}",bg="white",fg="#111827",
                         font=("Microsoft YaHei UI",11,"bold"),anchor="w")
        title.pack(side="left",fill="x",expand=True)
        title.bind("<Button-1>",lambda event:self.select())
        ActionButton(top,text="⛶",style="Mini.TButton",command=lambda:on_expand(pallet["pallet_index"])).pack(side="right")
        tk.Label(self.content,textvariable=self.caption,bg="white",fg="#7c8da8",
                 font=("Microsoft YaHei UI",8),anchor="w").pack(fill="x",pady=(2,4))
        controls = tk.Frame(self.content,bg="white")
        controls.pack(fill="x")
        for col,(text,action) in enumerate((("最终",self.final),("播放",self.play),("暂停",self.pause),
                                            ("◀",self.previous),("▶",self.next),("重置",self.reset))):
            controls.columnconfigure(col,weight=1,uniform="buttons")
            ActionButton(controls,text=text,command=action,style="Mini.TButton").grid(row=0,column=col,sticky="ew",padx=1)
        line = tk.Frame(self.content,bg="white")
        line.pack(fill="x",pady=(4,1))
        tk.Label(line,text="着色",bg="white",fg="#64748b",font=("Microsoft YaHei UI",8)).pack(side="left")
        self.colors = ttk.Combobox(line,state="readonly",values=["分箱","箱型","高度"],width=5,style="Compact.TCombobox")
        self.colors.current(0)
        self.colors.pack(side="left",fill="x",expand=True,padx=4)
        self.colors.bind("<<ComboboxSelected>>",lambda event:self.render())
        tk.Checkbutton(line,text="序号",variable=self.labels,command=self.render,bg="white",
                       font=("Microsoft YaHei UI",8),highlightthickness=0).pack(side="right")
        speed = tk.Frame(self.content,bg="white")
        speed.pack(fill="x",pady=(0,3))
        tk.Label(speed,text="速度",bg="white",fg="#64748b",font=("Microsoft YaHei UI",8)).pack(side="left")
        self.rate_label = tk.Label(speed,text="1×",bg="white",fg="#2563eb",width=4,font=("Segoe UI",8))
        self.rate_label.pack(side="right")
        ttk.Scale(speed,from_=.25,to=3,variable=self.rate,command=self.rate_changed).pack(side="left",fill="x",expand=True,padx=4)
        self.canvas = canvas_factory(self.content,width=280,height=150)
        self.canvas.pack(fill="both",expand=True)
        self.canvas.bind("<ButtonPress-1>",lambda event:self.select(),add="+")
        self.render()

    def select(self):
        self.on_select(self.pallet["pallet_index"])

    def render(self):
        self.caption.set(f"箱数 {len(self.pallet['packed_items'])}  |  填充率 {self.pallet['volume_utilization']:.1%}  |  {self.step}/{len(self.pallet['packed_items'])}")
        self.canvas.render(self.pallet,step=self.step,
                           color_mode={"分箱":"box","箱型":"type","高度":"height"}[self.colors.get()],labels=self.labels.get())

    def rate_changed(self,value):
        self.rate_label.configure(text=f"{float(value):.1f}×")

    def pause(self):
        self.playing = False
        if self.timer:
            self.after_cancel(self.timer)
            self.timer = None

    def schedule(self):
        self.timer = self.after(max(80,round(450/self.rate.get())),self.tick)

    def play(self):
        self.select()
        self.pause()
        if self.step>=len(self.pallet["packed_items"]):
            self.step = 0
        self.playing = True
        self.render()
        self.schedule()

    def tick(self):
        if self.timer:
            self.after_cancel(self.timer)
            self.timer = None
        if not self.playing:
            return
        self.step = min(self.step+1,len(self.pallet["packed_items"]))
        self.render()
        if self.step>=len(self.pallet["packed_items"]):
            self.pause()
        else:
            self.schedule()

    def move(self,value):
        self.select()
        self.pause()
        self.step = max(0,min(value,len(self.pallet["packed_items"])))
        self.render()

    def previous(self): self.move(self.step-1)
    def next(self): self.move(self.step+1)
    def final(self): self.move(len(self.pallet["packed_items"]))
    def reset(self): self.move(0)

    def destroy(self):
        self.pause()
        super().destroy()
