"""本地文件服务；Excel 使用可选读取库，供工作台和 CLI 共用。"""
from __future__ import annotations

import csv
from collections import Counter
import json
import math
import tempfile
import time
from pathlib import Path

from .io import (PAPER_DATASET_COLUMNS, read_boxes_csv, read_order_dataset,
                 read_packing_json, write_packing_plan_json, write_placements_csv)
from .models import Pallet
from .run_control import monitored_job
from .packer import FixedSequencePacker, PackingCancelled, check_cancelled


def finite_number(value, label, *, positive=False):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} 必须是有效数字") from None
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f"{label} 必须是有限的{'正数' if positive else '非负数'}")
    return number


def _check_boxes(boxes):
    if not boxes:
        raise ValueError("输入文件没有箱子")
    for box in boxes:
        for field in ("length", "width", "height"):
            finite_number(getattr(box, field), f"{box.id} 的 {field}", positive=True)
        finite_number(box.weight, f"{box.id} 的 weight")


def dataset_order_summaries(path: str | Path) -> dict[str, dict[str, int]]:
    summaries = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = PAPER_DATASET_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"论文数据集缺少列：{', '.join(sorted(missing))}")
        for line, row in enumerate(reader, 2):
            order, product = str(row.get("Order") or "").strip(), str(row.get("Product") or "").strip()
            if not order or not product:
                raise ValueError(f"第 {line} 行 Order / Product 不能为空")
            try:
                quantity = int(row["Quantity"])
                if quantity <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError(f"第 {line} 行 Quantity 必须是正整数") from None
            for field in ("Length", "Width", "Height", "Weight"):
                finite_number(row.get(field), f"第 {line} 行 {field}", positive=field != "Weight")
            state = summaries.setdefault(order, {"products": set(), "boxes": 0})
            state["products"].add(product)
            state["boxes"] += quantity
    if not summaries:
        raise ValueError("数据集没有箱子")
    return {order: {"box_types": len(state["products"]), "boxes": state["boxes"]}
            for order, state in summaries.items()}


def inspect_input(path: str | Path) -> dict:
    path = Path(path)
    extra = {}
    if path.suffix.lower() == ".xlsx":
        from .xlsx_input import read_boxes_xlsx
        pallet, boxes, metadata = read_boxes_xlsx(path)
        dims = (pallet.length, pallet.width, pallet.max_height) if pallet else None
        kind = "xlsx"
        extra = {"worksheet": metadata["worksheet"], "warnings": metadata["warnings"]}
    elif path.suffix.lower() == ".json":
        pallet, boxes = read_packing_json(path)
        dims = (pallet.length, pallet.width, pallet.max_height) if pallet else None
        for value in dims or ():
            finite_number(value, "托盘尺寸", positive=True)
        kind = "wcs_json" if boxes and boxes[0].metadata.get("source_format")=="zhuang_wcs_data" else "json"
    else:
        if path.suffix.lower() != ".csv":
            raise ValueError("支持 .xlsx、.csv、.json；旧版 .xls 请先另存为 .xlsx")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            fields = set(next(csv.reader(handle), []))
        if "Order" in fields:
            return {"kind": "paper", "summaries": dataset_order_summaries(path), "pallet": None}
        boxes, dims, kind = read_boxes_csv(path), None, "csv"
    _check_boxes(boxes)
    source_dims=dims
    if dims:
        normalized=Pallet(*dims).with_long_side_x()
        dims=(normalized.length,normalized.width,normalized.max_height)
    types = {(b.group,b.length,b.width,b.height) for b in boxes}
    info={"kind": kind, "summaries": {"全部箱子": {"box_types": len(types), "boxes": len(boxes)}},"pallet": dims,
          "pallet_source_dimensions":source_dims,"pallet_axes_swapped":bool(source_dims and source_dims[0]<source_dims[1]), **extra}
    if kind=="wcs_json":
        records={b.metadata["source_entry_index"]:b.metadata["source_case_type"] for b in boxes}
        info["case_types"]=dict(Counter(records.values()))
    return info


def build_output_paths(output_dir: str | Path, order_id: str) -> dict[str, Path]:
    folder = Path(output_dir)
    safe = "".join(c for c in str(order_id) if c.isalnum() or c in ("-", "_")) or "unknown"
    return {"json": folder / f"order_{safe}_plan.json", "csv": folder / f"order_{safe}_positions.csv",
            "png": folder / f"order_{safe}.png"}


def _publish_outputs(staged, paths, cancelled):
    """三件输出要么全部完成，要么恢复原文件。GUI 每次使用独立目录。"""
    backups, published = {}, []
    try:
        for key, target in paths.items():
            check_cancelled(cancelled)
            if target.exists():
                backup = staged[key].with_name(staged[key].name + ".previous")
                target.replace(backup)
                backups[key] = backup
            staged[key].replace(target)
            published.append(key)
            check_cancelled(cancelled)
    except Exception:
        for key in published:
            paths[key].unlink(missing_ok=True)
        for key, backup in backups.items():
            backup.replace(paths[key])
        raise


@monitored_job
def run_packing_job(dataset, order_id, pallet_length, pallet_width, pallet_height,
                    support_ratio, output_dir, *, progress=None, cancelled=None, log=None,
                    algorithm="basic",paper_config=None,approach_config=None,robot_scene_path=None,
                    robot_scene_sha256=None,max_seconds=3600.,robot_seal_verified_pallets=False) -> dict:
    started = time.perf_counter()
    check_cancelled(cancelled)
    dims = [finite_number(v, "托盘尺寸", positive=True) for v in
            (pallet_length, pallet_width, pallet_height)]
    support = 1.0 if algorithm in ("paper","robot2025") else finite_number(support_ratio, "支撑率")
    if support > 1:
        raise ValueError("支撑率必须在 0 到 1 之间")
    path = Path(dataset)
    info = inspect_input(path)
    import_metadata = None
    if info["kind"] == "paper":
        boxes = read_order_dataset(path, order_id)
    elif info["kind"] == "xlsx":
        from .xlsx_input import read_boxes_xlsx
        _, boxes, import_metadata = read_boxes_xlsx(path)
        if log:
            log(f"Excel 工作表：{import_metadata['worksheet']}；读取 {len(boxes)} 箱，不按订单分组。")
            for warning in import_metadata["warnings"]: log(warning)
    elif info["kind"] in ("json","wcs_json"):
        _, boxes = read_packing_json(path)
    else:
        boxes = read_boxes_csv(path)
    _check_boxes(boxes)
    if algorithm not in ("basic","paper","robot2025"): raise ValueError("未知装箱算法模式")
    if robot_scene_path is not None and algorithm!='robot2025':raise ValueError('机器人工位只用于2025模式')
    if log and algorithm=="basic":
        log(f"已读取 {len(boxes)} 箱，开始固定序列 + 简化 EP 装箱。")
    pallet = Pallet(*dims).with_long_side_x()
    if log:log(f'本次托盘：X长边={pallet.length:g}，Y短边={pallet.width:g}，Z限高={pallet.max_height:g}。')
    algorithm_started = time.perf_counter()
    if algorithm=="robot2025":
        from .robot_pipeline import RobotTwoPhasePacker
        verifier=None;scene_snapshot=scene_digest=None
        if robot_scene_path is not None:
            from .workcell_runtime import create_scene_verifier
            verifier,scene_snapshot,scene_digest=create_scene_verifier(Path(__file__).resolve().parents[2],
                robot_scene_path,Pallet(*dims),output_dir,robot_scene_sha256)
            if log:log('已启用当前工位的'+verifier.config.get('robot_name','EC66')+'完整离线检查：IK、机器人/夹具/携箱碰撞、抓取放置与撤离路径。')
        packer=RobotTwoPhasePacker(pallet,paper_config,approach_config,robot_verifier=verifier,seal_verified_pallets=robot_seal_verified_pallets)
        try:result=packer.pack(boxes,progress=progress,cancelled=cancelled,log=log)
        except InterruptedError:
            check_cancelled(cancelled);raise
        if verifier is not None:
            packer.robot_diagnostics.update(scene_source_sha256=scene_digest,scene_snapshot=scene_snapshot.name)
    elif algorithm=="paper":
        from .paper_pipeline import PaperTwoPhasePacker
        packer=PaperTwoPhasePacker(pallet,paper_config)
        result=packer.pack(boxes,progress=progress,cancelled=cancelled,log=log)
    else:
        result = FixedSequencePacker(pallet, support).pack(boxes, progress=progress, cancelled=cancelled)
    algorithm_seconds = time.perf_counter() - algorithm_started
    check_cancelled(cancelled)
    if log:
        log(f"算法计算时间：{algorithm_seconds:.3f} 秒，正在保存 JSON、CSV 和三维图。")
    paths = build_output_paths(output_dir, order_id)
    paths["json"].parent.mkdir(parents=True, exist_ok=True)
    # 完整导出后发布；取消或异常会清理临时文件。
    with tempfile.TemporaryDirectory(prefix=".packing_", dir=paths["json"].parent) as td:
        staged = build_output_paths(td, order_id)
        doc = write_packing_plan_json(staged["json"], result)
        if algorithm=="robot2025":
            from .robot_pipeline import annotate_robot_document
            annotate_robot_document(doc,packer)
        elif algorithm=="paper":
            from .paper_pipeline import annotate_document
            annotate_document(doc,packer.diagnostics)
        from .pallet_coordinates import public_document
        doc=public_document(doc)
        if info["kind"]=="wcs_json":
            doc["input_import"]={"format":"zhuang data[]","source_file":path.name,"included_boxes":len(boxes),
                 "case_type_record_counts":info["case_types"],
                 "handling":"ALL entries, one explicitly configured pallet size; no case_type/order filtering"}
        if import_metadata is not None: doc["input_import"] = import_metadata
        doc["timing"] = {"algorithm_seconds": algorithm_seconds, "clock": "perf_counter",
                         "scope": "solver_setup_and_packing_including_enabled_robot_verification; excludes_input_and_export"}
        staged["json"].write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8")
        write_placements_csv(staged["csv"], result,public_coordinates=True)
        from .native_scene import save_overview
        save_overview(doc, staged["png"], cancelled=cancelled)
        check_cancelled(cancelled)
        _publish_outputs(staged, paths, cancelled)
    return {**doc["summary"], "paths": paths, "document": doc,
            "algorithm_seconds": algorithm_seconds,
            "elapsed_seconds": time.perf_counter() - started}


def load_result(path: str | Path) -> dict:
    """校验本工程 JSON，按实际箱体重算统计，兼容旧版无顶层 pallet。"""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(doc, dict) or not isinstance(doc.get("pallets"), list) or not isinstance(doc.get("unplaced_items"), list):
            raise ValueError("请选择本工程输出的装箱方案 JSON")
        seen, sequences, pallet_ids = set(), set(), set()
        packed_count, used_volume, capacity = 0, 0.0, 0.0
        def dimensions(data):
            keys = ("length", "width", "height")
            values = [finite_number(data[k], k, positive=True) for k in keys]
            data.update(zip(keys, values))
            return values
        def unique_id(item):
            box_id = str(item["id"])
            if not box_id.strip() or box_id in seen:
                raise ValueError("结果含有空箱号或重复箱号")
            seen.add(box_id)
        def metric_fields(item):
            item["weight"]=finite_number(item.get("weight") if item.get("weight") is not None else 0,"结果箱体weight")
            box_type=item.get("box_type")
            if box_type is None:item["box_type"]=""
            elif isinstance(box_type,str):pass
            elif isinstance(box_type,(int,float)) and not isinstance(box_type,bool) and math.isfinite(box_type):
                item["box_type"]=str(box_type)
            else:raise ValueError("结果箱型box_type必须是文字或有限数字")
        for pallet in doc["pallets"]:
            index = pallet["pallet_index"]
            if isinstance(index, bool) or not isinstance(index, int) or index < 1 or index in pallet_ids:
                raise ValueError("托盘编号无效或重复")
            pallet_ids.add(index)
            dims = dimensions(pallet["pallet"])
            items = pallet["packed_items"]
            if not isinstance(items, list) or not items:
                raise ValueError("结果包含空托盘")
            volume = 0.0
            occupied = []
            for item in items:
                unique_id(item)
                metric_fields(item)
                size = dimensions(item["placed_size"])
                pos = [finite_number(item["position"][axis], axis) for axis in ("x", "y", "z")]
                item["position"].update(zip(("x", "y", "z"), pos))
                if any(a + b > c + 1e-7 for a, b, c in zip(pos, size, dims)):
                    raise ValueError("结果含有超出托盘的箱子")
                extent = [(start, start + width) for start, width in zip(pos, size)]
                if any(all(min(a[1], b[1]) - max(a[0], b[0]) > 1e-9
                           for a, b in zip(extent, other)) for other in occupied):
                    raise ValueError("结果含有相互重叠的箱子")
                occupied.append(extent)
                seq = item["sequence"]
                if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1 or seq in sequences:
                    raise ValueError("放置顺序无效或重复")
                sequences.add(seq)
                if item["orientation"] not in ("Z0", "Z90"):
                    raise ValueError("未知的箱体姿态")
                volume += math.prod(size)
            items.sort(key=lambda i: i["sequence"])
            pallet["box_count"] = len(items)
            pallet["volume_utilization"] = volume / math.prod(dims)
            capacity += math.prod(dims)
            used_volume += volume
            packed_count += len(items)
        for item in doc["unplaced_items"]:
            unique_id(item)
            metric_fields(item)
            dimensions(item["size"])
            if not isinstance(item["reason"], str):
                raise ValueError("未装箱原因无效")
        if not doc["pallets"] and "pallet" not in doc:
            raise ValueError("空方案缺少托盘尺寸，需使用新版程序重新导出")
        dimensions(doc.get("pallet") or doc["pallets"][0]["pallet"])
        doc["summary"] = {"input_box_count": packed_count + len(doc["unplaced_items"]),
            "packed_box_count": packed_count, "unplaced_box_count": len(doc["unplaced_items"]),
            "pallet_count": len(doc["pallets"]), "volume_utilization": used_volume / capacity if capacity else 0.0}
        if "timing" in doc:
            doc["timing"]["algorithm_seconds"] = finite_number(doc["timing"]["algorithm_seconds"], "算法计算时间")
        return doc
    except (KeyError, TypeError, AttributeError, OverflowError, json.JSONDecodeError) as exc:
        raise ValueError(f"装箱方案格式不正确：{exc}") from exc
