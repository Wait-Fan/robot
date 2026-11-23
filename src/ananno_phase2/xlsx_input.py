"""只读 Excel 货物导入；业务数量不等同于箱数，不读取参考表作为货物。"""
from __future__ import annotations

import math
from pathlib import Path
from zipfile import BadZipFile

from .models import Box, Pallet


ALIASES = {
    "id": {"id", "box_id", "箱子序号", "箱号", "箱体编号"},
    "box_type": {"box_type", "product", "box类型", "箱型", "箱子类型"},
    "length": {"length", "长", "长度", "箱子长", "箱长", "长度(mm)", "箱子长(mm)"},
    "width": {"width", "宽", "宽度", "箱子宽", "箱宽", "宽度(mm)", "箱子宽(mm)"},
    "height": {"height", "高", "高度", "箱子高", "箱高", "高度(mm)", "箱子高(mm)"},
    "weight": {"weight", "重量", "总重量", "单箱重量", "箱重", "重量(kg)"},
    "quantity": {"quantity", "数量", "箱数", "target_num"},
    "pallet_length": {"pallet_length", "托盘长", "托盘长度"},
    "pallet_width": {"pallet_width", "托盘宽", "托盘宽度"},
    "pallet_height": {"pallet_height", "托盘高", "托盘高度", "限高"},
}
DIMENSIONS = ("length", "width", "height")
PALLET_FIELDS = ("pallet_length", "pallet_width", "pallet_height")


def _header(value):
    return str(value or "").strip().lower().replace(" ", "").replace("（", "(").replace("）", ")")


def _find_header(sheet):
    lookup = {alias: field for field, aliases in ALIASES.items() for alias in aliases}
    rows = sheet.iter_rows(min_row=1, max_row=20, max_col=128, values_only=True)
    try:
        for line, row in enumerate(rows, 1):
            fields, duplicate = {}, None
            for index, value in enumerate(row):
                field = lookup.get(_header(value))
                if field:
                    if field in fields: duplicate = field
                    fields[field] = index
            if all(field in fields for field in DIMENSIONS):
                if duplicate:
                    raise ValueError(f"工作表 {sheet.title} 第 {line} 行存在重复字段：{duplicate}")
                return line, fields
    finally:
        rows.close()
    return None


def read_boxes_xlsx(path: str | Path) -> tuple[Pallet | None, list[Box], dict]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("读取 XLSX 需要 openpyxl，请使用当前 Python 运行：python -m pip install -r requirements.txt") from exc
    try:
        book = load_workbook(path, read_only=True, data_only=True)
    except (BadZipFile, OSError, ValueError) as exc:
        raise ValueError(f"无法读取 XLSX 文件：{exc}") from exc
    try:
        candidates = []
        sheets = [book["最终挑选结果"]] if "最终挑选结果" in book.sheetnames else book.worksheets
        for sheet in sheets:
            found = _find_header(sheet)
            if found: candidates.append((sheet, *found))
        if not candidates:
            raise ValueError("XLSX 未找到箱子长、宽、高表头；支持 length/width/height 或 箱子长/箱子宽/箱子高")
        if len(candidates) > 1:
            names = "、".join(item[0].title for item in candidates)
            raise ValueError(f"XLSX 有多个货物工作表：{names}；请将要计算的表命名为“最终挑选结果”，或另存为单表文件")
        sheet, header_row, fields = candidates[0]
        if any(f in fields for f in PALLET_FIELDS) and not all(f in fields for f in PALLET_FIELDS):
            raise ValueError(f"工作表 {sheet.title} 的托盘长、宽、高列必须同时提供，或全部省略")
        boxes, ids, pallet_sizes, warnings = [], set(), set(), []
        missing_weights = missing_pallets = 0
        rows_count = 0
        for line, row in enumerate(sheet.iter_rows(min_row=header_row + 1,
                                  max_col=max(fields.values()) + 1, values_only=True), header_row + 1):
            if all(value is None or value == "" for value in row): continue
            label = f"工作表 {sheet.title} 第 {line} 行"
            def value(field):
                return row[fields[field]] if field in fields else None
            def number(field, *, positive=False, default=None):
                raw = value(field)
                if raw is None or raw == "": raw = default
                try:
                    if isinstance(raw, bool): raise ValueError
                    result = float(raw)
                    if not math.isfinite(result) or result < 0 or (positive and result == 0): raise ValueError
                    return result
                except (TypeError, ValueError, OverflowError):
                    raise ValueError(f"{label} {field} 必须是有限{'正数' if positive else '非负数'}；空白公式请先用 Excel/WPS 重算并保存") from None
            size = tuple(number(f, positive=True) for f in DIMENSIONS)
            weight = number("weight", default=0)
            if value("weight") in (None, ""): missing_weights += 1
            quantity = number("quantity", positive=True, default=1)
            if not quantity.is_integer(): raise ValueError(f"{label} quantity 箱数必须是正整数")
            quantity = int(quantity)
            box_type = str(value("box_type") or "").strip() or "×".join(f"{v:g}" for v in size)
            raw_id = value("id")
            if isinstance(raw_id, (int, float)) and not isinstance(raw_id, bool):
                raw_id = f"{raw_id:g}"
            base_id = str(raw_id).strip() if raw_id is not None else ""
            base_id = base_id or f"XLSX-{line:06d}"
            for serial in range(quantity):
                box_id = base_id if quantity == 1 else f"{base_id}-{serial + 1:03d}"
                if box_id in ids: raise ValueError(f"{label} 箱号重复：{box_id}")
                ids.add(box_id)
                boxes.append(Box(box_id, *size, weight, group=box_type,
                                 metadata={"source_format": "xlsx", "worksheet": sheet.title, "source_row": line}))
            if all(f in fields for f in PALLET_FIELDS):
                if all(value(f) in (None, "") for f in PALLET_FIELDS): missing_pallets += 1
                else: pallet_sizes.add(tuple(number(f, positive=True) for f in PALLET_FIELDS))
            rows_count += 1
        if not boxes: raise ValueError(f"工作表 {sheet.title} 没有箱子数据")
        pallet = Pallet(*next(iter(pallet_sizes))) if len(pallet_sizes) == 1 and not missing_pallets else None
        if missing_weights: warnings.append(f"{missing_weights} 行未提供重量，按0读取；重量/重心相关结果受此假设影响。")
        if len(pallet_sizes) > 1: warnings.append("文件包含多种托盘尺寸；不自动分组，请在装箱设置中确认本次统一托盘规格。")
        elif pallet is None: warnings.append("未提供完整统一托盘尺寸；请在装箱设置中确认长、宽和限高。")
        return pallet, boxes, {"format": "xlsx", "source_file": Path(path).name, "worksheet": sheet.title,
            "source_rows": rows_count, "included_boxes": len(boxes), "warnings": warnings,
            "handling": "quantity/数量/箱数/target_num are box counts; 实际包装数量 and business order fields ignored; no order grouping"}
    finally:
        book.close()
