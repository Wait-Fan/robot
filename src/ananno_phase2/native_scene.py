"""标准库正交三维投影与 PNG 输出；专用于正交长方体装箱方案。"""
from __future__ import annotations

import hashlib
import math
import struct
import zlib
from pathlib import Path

from .packer import check_cancelled

COLORS = ("#60a5fa", "#fbbf24", "#34d399", "#f87171", "#a78bfa", "#fb923c",
          "#22d3ee", "#f472b6", "#a3e635", "#94a3b8", "#818cf8", "#2dd4bf")


def shade(color, factor):
    rgb = [int(color[i:i+2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{max(0, min(255, round(v * factor))):02x}" for v in rgb)


def box_vertices(x, y, z, length, width, height):
    return [(x,y,z),(x+length,y,z),(x+length,y+width,z),(x,y+width,z),
            (x,y,z+height),(x+length,y,z+height),(x+length,y+width,z+height),(x,y+width,z+height)]


def _clip_polygon(points,axis,plane,positive):
    clipped = []
    for start,end in zip(points,points[1:]+points[:1]):
        start_in = start[axis]>=plane if positive else start[axis]<=plane
        end_in = end[axis]>=plane if positive else end[axis]<=plane
        if start_in:
            clipped.append(start)
        if start_in != end_in:
            ratio = (plane-start[axis])/(end[axis]-start[axis])
            clipped.append(tuple(a+ratio*(b-a) for a,b in zip(start,end)))
    return clipped


def _painter_order(faces,direction):
    """BSP 平面分割：面深度平均值不足以正确处理大小不同的相邻箱。"""
    if not faces:
        return []
    root = {}
    pending = [(root,faces)]
    while pending:
        node,polygons = pending.pop()
        axis,plane,_,_ = polygons[len(polygons)//2]
        back,front,coplanar = [],[],[]
        for face_axis,face_plane,points,color in polygons:
            low,high = min(p[axis] for p in points),max(p[axis] for p in points)
            face = (face_axis,face_plane,points,color)
            if low>=plane-1e-9 and high<=plane+1e-9:
                coplanar.append(face)
            elif high<=plane+1e-9:
                back.append(face)
            elif low>=plane-1e-9:
                front.append(face)
            else:
                back.append((face_axis,face_plane,_clip_polygon(points,axis,plane,False),color))
                front.append((face_axis,face_plane,_clip_polygon(points,axis,plane,True),color))
        node.update(axis=axis,faces=coplanar,back=None,front=None)
        for name,parts in (("back",back),("front",front)):
            if parts:
                child = {}
                node[name] = child
                pending.append((child,parts))
    ordered,stack = [],[(root,False)]
    while stack:
        node,visit = stack.pop()
        if visit:
            ordered.extend(node["faces"])
            continue
        first,last = ((node["back"],node["front"]) if direction[node["axis"]]>=0
                      else (node["front"],node["back"]))
        if last is not None:
            stack.append((last,False))
        stack.append((node,True))
        if first is not None:
            stack.append((first,False))
    return ordered


def project_scene(pallet, width, height, *, step=None, yaw=35, pitch=28, zoom=1,
                  color_mode="box", labels=False, palette=COLORS):
    """返回画布多边形、容器线框和标签；相同数据可在 Tk 与 PNG 中绘制。"""
    length, breadth, tall = (float(pallet["pallet"][k]) for k in ("length", "width", "height"))
    angle, elevation = math.radians(yaw), math.radians(pitch)
    ca, sa, ce, se = math.cos(angle), math.sin(angle), math.cos(elevation), math.sin(elevation)
    def camera(point):
        x, y, z = point[0]-length/2, point[1]-breadth/2, point[2]-tall/2
        rx, ry = ca*x-sa*y, sa*x+ca*y
        return rx, se*ry-ce*z, ce*ry+se*z
    corners = box_vertices(0, 0, 0, length, breadth, tall)
    raw = [camera(v) for v in corners]
    xmin, xmax = min(v[0] for v in raw), max(v[0] for v in raw)
    ymin, ymax = min(v[1] for v in raw), max(v[1] for v in raw)
    scale = min((width-70)/max(xmax-xmin, 1e-12), (height-60)/max(ymax-ymin, 1e-12)) * zoom
    def projected(point):
        rx, ry, depth = camera(point)
        return ((rx-(xmin+xmax)/2)*scale+width/2,
                (ry-(ymin+ymax)/2)*scale+height/2-5, depth)
    frame = [projected(v) for v in corners]
    lines = [(frame[a][:2], frame[b][:2]) for a,b in
             ((0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7))]
    polygons, texts, faces = [], [], []
    direction = (ce*sa,ce*ca,se)
    items = sorted(pallet["packed_items"], key=lambda i: i["sequence"])
    for index, item in enumerate(items if step is None else items[:step]):
        point = [float(item["position"][k]) for k in ("x", "y", "z")]
        size = [float(item["placed_size"][k]) for k in ("length", "width", "height")]
        vertices = box_vertices(*point, *size)
        if color_mode == "type":
            key = str(item.get("box_type", item["id"]))
            ci = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % len(palette)
        elif color_mode == "height":
            ci = min(len(palette)-1, int(point[2]/tall*len(palette)))
        else:
            ci = index % len(palette)
        for face,factor,axis,normal in (((0,1,2,3),.7,2,-1),((4,5,6,7),1.12,2,1),
             ((0,1,5,4),.82,1,-1),((2,3,7,6),.82,1,1),
             ((1,2,6,5),.94,0,1),((0,3,7,4),.94,0,-1)):
            if normal*direction[axis]>1e-12:
                world = [vertices[j] for j in face]
                faces.append((axis,world[0][axis],world,shade(palette[ci],factor)))
        if labels:
            top = projected((point[0]+size[0]/2, point[1]+size[1]/2, point[2]+size[2]))
            texts.append((top[0], top[1], str(item["sequence"])))
    for _,_,world,color in _painter_order(faces,direction):
        projected_face = [projected(point) for point in world]
        polygons.append((sum(v[2] for v in projected_face)/len(projected_face),
                         [(v[0],v[1]) for v in projected_face],color))
    # 三个轴方向与输入坐标一致，明确标记容器尺寸。
    for vertex, text in ((1, f"X {length:g}"), (3, f"Y {breadth:g}"), (4, f"Z {tall:g}")):
        texts.append((frame[vertex][0], frame[vertex][1]-10, text))
    return polygons, lines, texts


class Raster:
    """小型 RGB 栅格，用于无需 Pillow/Matplotlib 的实验结果 PNG。"""
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.rows = [bytearray(bytes((248,250,252))*width) for _ in range(height)]

    @staticmethod
    def rgb(color):
        return bytes(int(color[i:i+2], 16) for i in (1,3,5))

    def line(self, start, end, color="#64748b"):
        x0,y0,x1,y1 = round(start[0]),round(start[1]),round(end[0]),round(end[1])
        dx,dy = abs(x1-x0), -abs(y1-y0)
        sx,sy = (1 if x0<x1 else -1),(1 if y0<y1 else -1)
        error, rgb = dx+dy, self.rgb(color)
        while True:
            if 0 <= x0 < self.width and 0 <= y0 < self.height:
                self.rows[y0][x0*3:x0*3+3] = rgb
            if x0 == x1 and y0 == y1:
                break
            twice = 2*error
            if twice >= dy:
                error += dy
                x0 += sx
            if twice <= dx:
                error += dx
                y0 += sy

    def polygon(self, points, color):
        rgb = self.rgb(color)
        edges = list(zip(points, points[1:]+points[:1]))
        bottom = max(0, math.floor(min(p[1] for p in points)))
        top = min(self.height-1, math.ceil(max(p[1] for p in points)))
        for y in range(bottom, top+1):
            sample = y+.5
            intersections = sorted(a[0]+(sample-a[1])*(b[0]-a[0])/(b[1]-a[1])
                for a,b in edges if (a[1] <= sample < b[1]) or (b[1] <= sample < a[1]))
            for left,right in zip(intersections[::2],intersections[1::2]):
                x0,x1 = max(0,math.ceil(left)),min(self.width,math.ceil(right))
                if x1 > x0:
                    self.rows[y][x0*3:x1*3] = rgb*(x1-x0)
        for a,b in edges:
            self.line(a,b,"#334155")

    def save(self, path, description):
        def chunk(kind, data):
            return struct.pack("!I",len(data))+kind+data+struct.pack("!I",zlib.crc32(kind+data)&0xffffffff)
        compressed = zlib.compressobj()
        encoded = b"".join(compressed.compress(b"\0"+row) for row in self.rows)+compressed.flush()
        data = (b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack("!2I5B",self.width,self.height,8,2,0,0,0))
                +chunk(b"tEXt",b"Description\0"+description.encode("ascii"))
                +chunk(b"IDAT",encoded)+chunk(b"IEND",b""))
        Path(path).write_bytes(data)


def save_overview(document, output_path, *, cancelled=None):
    pallets = document["pallets"] or [{"pallet":document["pallet"],"packed_items":[],"pallet_index":0}]
    columns, cell_width, cell_height = min(3,len(pallets)), 400, 340
    image = Raster(columns*cell_width, math.ceil(len(pallets)/columns)*cell_height)
    for index,pallet in enumerate(pallets):
        check_cancelled(cancelled)
        xoffset,yoffset = (index%columns)*cell_width,(index//columns)*cell_height
        polygons,lines,_ = project_scene(pallet,cell_width,cell_height)
        shift = lambda p: (p[0]+xoffset,p[1]+yoffset)
        for a,b in lines:
            image.line(shift(a),shift(b),"#cbd5e1")
        for _,points,color in polygons:
            check_cancelled(cancelled)
            image.polygon([shift(p) for p in points],color)
    check_cancelled(cancelled)
    image.save(output_path,"Ananno 2024 Phase 2 staged reproduction; pallets in row-major order")
