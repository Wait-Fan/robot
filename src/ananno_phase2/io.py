from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import Box, PackingResult

REQUIRED_COLUMNS = {"id", "length", "width", "height"}
PAPER_DATASET_COLUMNS = {"Order", "Product", "Quantity", "Length", "Width", "Height", "Weight"}


def read_boxes_csv(path: str | Path) -> list[Box]:
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV 缺少列：{', '.join(sorted(missing))}")
        boxes = []
        for line, row in enumerate(reader, 2):
            def number(field: str, default: str | float | None = None) -> float:
                raw = row.get(field)
                if (raw is None or raw == "") and default is not None:
                    raw = default
                try:
                    return float(raw)  # type: ignore[arg-type]
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"CSV 第 {line} 行字段 {field} 不是有效数字：{raw!r}") from exc

            try:
                boxes.append(
                    Box(
                        row["id"].strip(),
                        number("length"),
                        number("width"),
                        number("height"),
                        number("weight", 0),
                        (row.get("group") or "").strip(),
                    )
                )
            except (TypeError, ValueError) as exc:
                if str(exc).startswith("CSV 第"):
                    raise
                raise ValueError(f"CSV 第 {line} 行数据无效：{exc}") from exc
    if len({b.id for b in boxes}) != len(boxes):
        raise ValueError("CSV 中存在重复箱体 id")
    return boxes


def write_placements_csv(path: str | Path, result: PackingResult) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["order", "pallet", "box_id", "x", "y", "z", "orientation", "length", "width", "height"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for p in result.placements:
            writer.writerow(
                {"order": p.order, "pallet": p.pallet_index + 1, "box_id": p.box.id,
                 "x": p.point.x, "y": p.point.y, "z": p.point.z, "orientation": p.orientation.code,
                 "length": p.orientation.length, "width": p.orientation.width, "height": p.orientation.height}
            )


def read_order_dataset(path: str | Path, order_id: str | int) -> list[Box]:
    """读取论文公开数据集中的一个订单，并按 Quantity 展开为逐箱列表。"""
    path = Path(path)
    requested = str(order_id).strip()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = PAPER_DATASET_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"论文数据集缺少列：{', '.join(sorted(missing))}")
        matched: list[tuple[int, dict[str, str]]] = []
        available_orders: list[str] = []
        seen_orders: set[str] = set()
        for line, row in enumerate(reader, 2):
            current = str(row.get("Order", "")).strip()
            if current and current not in seen_orders:
                seen_orders.add(current)
                if len(available_orders) < 10:
                    available_orders.append(current)
            if current == requested:
                matched.append((line, row))
    if not matched:
        examples = ", ".join(available_orders)
        raise ValueError(f"数据集中没有订单 {requested}；可用订单示例：{examples}")

    boxes: list[Box] = []
    product_counts: dict[str, int] = {}
    for line, row in matched:
        product = str(row["Product"]).strip()
        try:
            quantity_raw = row["Quantity"]
            quantity = int(quantity_raw)
            if quantity <= 0 or float(quantity_raw) != quantity:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f"论文数据集第 {line} 行 Quantity 必须是正整数") from None
        try:
            length = float(row["Length"])
            width = float(row["Width"])
            height = float(row["Height"])
            weight = float(row["Weight"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"论文数据集第 {line} 行尺寸或 Weight 无效：{exc}") from exc
        for _ in range(quantity):
            product_counts[product] = product_counts.get(product, 0) + 1
            boxes.append(
                Box(
                    f"{product}-{product_counts[product]:03d}",
                    length,
                    width,
                    height,
                    weight,
                    group=product,
                    metadata={"product": product, "order": requested},
                )
            )
    return boxes


def read_packing_json(path: str | Path) -> tuple["Pallet | None", list[Box]]:
    """读取标准输入或zhuang data[]；接口文件不带托盘时返回None由调用者提供。"""
    from .models import Pallet

    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 格式错误（第 {exc.lineno} 行第 {exc.colno} 列）：{exc.msg}") from exc
    if not isinstance(document, dict):
        raise ValueError("JSON 顶层必须是对象")

    pallet_data = document.get("pallet")
    is_wcs="data" in document and "boxes" not in document
    if not isinstance(pallet_data, dict) and (not is_wcs or "pallet" in document):
        raise ValueError("JSON 缺少 pallet 对象")
    pallet=None
    if isinstance(pallet_data,dict):
        try:
            pallet = Pallet(float(pallet_data["length"]),float(pallet_data["width"]),float(pallet_data["height"]))
        except KeyError as exc:
            raise ValueError(f"pallet 缺少字段：{exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"pallet 尺寸无效：{exc}") from exc

    entries_name="data" if is_wcs else "boxes"
    entries = document.get(entries_name)
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"JSON 的 {entries_name} 必须是非空数组")
    boxes: list[Box] = []
    type_counts: dict[str, int] = {}
    for row, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"{entries_name} 第 {row} 项必须是对象")
        box_type = str(entry.get("box_type") or f"BOX{row}").strip()
        try:
            quantity_raw = entry.get("target_num", 1)
            quantity = int(quantity_raw)
            if isinstance(quantity_raw,bool) or quantity <= 0 or float(quantity_raw) != quantity:
                raise ValueError
        except (TypeError, ValueError,OverflowError):
            raise ValueError(f"{entries_name} 第 {row} 项 target_num 必须是正整数") from None
        try:
            length = float(entry["length"])
            width = float(entry["width"])
            height = float(entry["height"])
            weight = float(entry.get("weight", 0) or 0)
        except KeyError as exc:
            raise ValueError(f"{entries_name} 第 {row} 项缺少字段：{exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{entries_name} 第 {row} 项尺寸或重量不是有效数字：{exc}") from exc
        for _ in range(quantity):
            type_counts[box_type] = type_counts.get(box_type, 0) + 1
            box_id = f"{box_type}-{type_counts[box_type]:03d}"
            boxes.append(
                Box(
                    box_id,
                    length,
                    width,
                    height,
                    weight,
                    group=box_type,
                    metadata={"box_type": box_type,**({"source_format":"zhuang_wcs_data",
                              "source_entry_index":row,"source_case_type":str(entry.get("case_type") or "")}
                              if is_wcs else {})},
                )
            )
    return pallet, boxes


def write_packing_plan_json(path: str | Path | None, result: PackingResult) -> dict:
    """构造纯装箱方案；path 为 None 时只返回文档，不写文件。"""
    path = Path(path) if path is not None else None
    pallets = []
    for pallet_index in range(result.pallet_count):
        items = [p for p in result.placements if p.pallet_index == pallet_index]
        used_volume = sum(p.box.volume for p in items)
        pallets.append(
            {
                "pallet_index": pallet_index + 1,
                "pallet": {
                    "length": result.pallet.length,
                    "width": result.pallet.width,
                    "height": result.pallet.max_height,
                },
                "box_count": len(items),
                "volume_utilization": used_volume / result.pallet.volume,
                "packed_items": [
                    {
                        "id": p.box.id,
                        "box_type": p.box.group or p.box.id,
                        "sequence": p.order,
                        "position": {"x": p.point.x, "y": p.point.y, "z": p.point.z},
                        "orientation": p.orientation.code,
                        "placed_size": {
                            "length": p.orientation.length,
                            "width": p.orientation.width,
                            "height": p.orientation.height,
                        },
                        "weight": p.box.weight,
                    }
                    for p in items
                ],
            }
        )
    document = {
        "algorithm": "Ananno 2024 Phase 2 staged reproduction",
        "is_complete_reproduction": False,
        "pallet": {"length": result.pallet.length, "width": result.pallet.width,
                   "height": result.pallet.max_height},
        "summary": {
            "input_box_count": len(result.placements) + len(result.unplaced),
            "packed_box_count": len(result.placements),
            "unplaced_box_count": len(result.unplaced),
            "pallet_count": result.pallet_count,
            "volume_utilization": result.utilization,
        },
        "pallets": pallets,
        "unplaced_items": [
            {
                "id": item.box.id,
                "box_type": item.box.group or item.box.id,
                "size": {
                    "length": item.box.length,
                    "width": item.box.width,
                    "height": item.box.height,
                },
                "reason": item.reason,
            }
            for item in result.unplaced
        ],
    }
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return document
