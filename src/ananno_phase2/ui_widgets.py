"""标准库绘制的工作台卡片与按钮，不引入界面依赖。"""
import tkinter as tk
from tkinter import font as tkfont, ttk

BG = "#f3f6fa"


def rounded(canvas,x0,y0,x1,y1,radius,**kwargs):
    r = min(radius,(x1-x0)/2,(y1-y0)/2)
    points = [x0+r,y0,x1-r,y0,x1,y0,x1,y0+r,x1,y1-r,x1,y1,
              x1-r,y1,x0+r,y1,x0,y1,x0,y1-r,x0,y0+r,x0,y0]
    return canvas.create_polygon(points,smooth=True,splinesteps=32,**kwargs)


def background_of(widget):
    try:
        return widget.cget("background")
    except tk.TclError:
        return ttk.Style(widget).lookup(widget.cget("style") or "TFrame","background") or BG


class Card(tk.Frame):
    def __init__(self,parent,*,title=None,padding=14,fill="white",border="#e1e7ef"):
        super().__init__(parent,background=BG,borderwidth=0)
        self.padding = padding
        self.fill,self.border,self.selected = fill,border,False
        self.surface = tk.Canvas(self,background=BG,highlightthickness=0,borderwidth=0,height=100)
        self.surface.pack(fill="both",expand=True)
        self.content = tk.Frame(self.surface,background=fill)
        self.window = self.surface.create_window(padding,padding,window=self.content,anchor="nw")
        if title:
            heading = tk.Frame(self.content,background=fill)
            heading.pack(fill="x",pady=(0,10))
            parts = title.split("  ",1)
            if len(parts)==2 and parts[0].isdigit():
                badge = tk.Canvas(heading,width=26,height=26,background=fill,highlightthickness=0)
                badge.pack(side="left",padx=(0,9))
                badge.create_oval(0,0,26,26,fill="#2563eb",outline="")
                badge.create_text(13,13,text=str(int(parts[0])),fill="white",font=("Segoe UI",10,"bold"))
                title = parts[1]
            tk.Label(heading,text=title,bg=fill,fg="#991b1b",font=("Microsoft YaHei UI",9,"bold")).pack(side="left",pady=3)
        self.surface.bind("<Configure>",self._layout)
        self.content.bind("<Configure>",self._resize)

    def _resize(self,event=None):
        height = self.content.winfo_reqheight()+2*self.padding
        if int(float(self.surface.cget("height")))!=height:
            self.surface.configure(height=height)
        self._draw()

    def _layout(self,event):
        self.surface.itemconfigure(self.window,width=max(20,event.width-2*self.padding))
        self._draw()

    def _draw(self):
        self.surface.delete("background")
        width,height = self.surface.winfo_width(),int(float(self.surface.cget("height")))
        if width>2:
            rounded(self.surface,1,1,width-1,height-1,10,fill=self.fill,
                    outline="#2563eb" if self.selected else self.border,
                    width=2 if self.selected else 1,tags="background")
            self.surface.tag_lower("background")

    def set_selected(self,selected):
        self.selected = selected
        self._draw()


class ActionButton(tk.Canvas):
    def __init__(self,parent,*,text="",command=None,style="TButton",width=None,state="normal",**kwargs):
        self._text,self._command,self._kind = text,command,style
        self._button_state,self._hover = state,False
        root = parent.winfo_toplevel()
        if not hasattr(root,"_workbench_button_fonts"):
            root._workbench_button_fonts = {
                weight:tkfont.Font(root=root,family="Microsoft YaHei UI",size=9,weight=weight)
                for weight in ("normal","bold")}
        self._font = root._workbench_button_fonts["bold" if style=="Blue.TButton" else "normal"]
        self.compact = style=="Mini.TButton"
        self._height = 26 if self.compact else 36
        measured = self._font.measure(text)+(14 if self.compact else 28)
        target = max(measured,self._font.measure("0")*width+22) if width else measured
        super().__init__(parent,width=target,height=self._height,background=background_of(parent),
                         highlightthickness=0,borderwidth=0,takefocus=True,**kwargs)
        self.bind("<Configure>",lambda event:self._draw())
        self.bind("<Enter>",lambda event:self._enter(True))
        self.bind("<Leave>",lambda event:self._enter(False))
        self.bind("<Button-1>",lambda event:self.invoke())
        self.bind("<Return>",lambda event:self.invoke())
        self.bind("<space>",lambda event:self.invoke())
        self.bind("<FocusIn>",lambda event:self._draw())
        self.bind("<FocusOut>",lambda event:self._draw())
        self._draw()

    def _enter(self,hover):
        self._hover = hover
        self._draw()

    def _draw(self):
        self.delete("all")
        width,height = self.winfo_width(),self._height
        if width<=1:
            width = int(float(self.cget("width")))
        dark = self._kind=="Dark.TButton"
        if self._button_state=="disabled":
            fill,foreground,border = ("#2b3648","#738399","#2b3648") if dark or background_of(self.master)=="#111827" else ("#e8edf3","#a0aab8","#e8edf3")
        elif self._kind=="Blue.TButton":
            fill,foreground,border = ("#1d4ed8" if self._hover else "#2563eb"),"white","#2563eb"
        elif self._kind=="Danger.TButton":
            fill,foreground,border = ("#b91c1c" if self._hover else "#dc2626"),"white","#dc2626"
        elif dark:
            fill,foreground,border = ("#334155" if self._hover else "#263244"),"#e5e7eb","#3a4a60"
        else:
            fill,foreground,border = ("#dbe4f0" if self._hover else "#e5e7eb"),"#27364b","#e5e7eb"
        rounded(self,1,1,width-1,height-1,8,fill=fill,outline=border)
        self.create_text(width/2,height/2,text=self._text,font=self._font,fill=foreground)
        self.configure(cursor="arrow" if self._button_state=="disabled" else "hand2")

    def configure(self,cnf=None,**kwargs):
        if cnf:
            kwargs.update(cnf)
        redraw = False
        for key in ("state","text","command"):
            if key in kwargs:
                value = kwargs.pop(key)
                setattr(self,{"state":"_button_state","text":"_text","command":"_command"}[key],value)
                redraw = True
        result = super().configure(**kwargs) if kwargs else None
        if redraw:
            self._draw()
        return result

    config = configure

    def instate(self,states):
        return all((self._button_state=="disabled") if value=="disabled" else
                   (self._button_state!="disabled") if value=="!disabled" else False for value in states)

    def invoke(self):
        if self._button_state!="disabled" and self._command:
            self.focus_set()
            return self._command()
