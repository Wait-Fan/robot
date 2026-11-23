from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ananno_phase2.io import (
    read_boxes_csv,
    read_order_dataset,
    read_packing_json,
    write_packing_plan_json,
    write_placements_csv,
)
from ananno_phase2.models import Box, Pallet
from ananno_phase2.packer import FixedSequencePacker


def demo_boxes() -> list[Box]:
    return [Box("A", 6, 4, 2), Box("B", 4, 4, 2), Box("C", 5, 3, 2),
            Box("D", 3, 5, 2), Box("E", 6, 4, 2), Box("F", 4, 4, 2)]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ananno 2025 独立研究工程：继承2024两阶段算法，加入固定开放方向模型")
    inputs = p.add_mutually_exclusive_group()
    inputs.add_argument("--input", type=Path, help="箱体 CSV 或 XLSX；省略时使用内置示例")
    inputs.add_argument("--input-json", type=Path, help="精简装箱 JSON（含 pallet 和 boxes）")
    inputs.add_argument("--dataset", type=Path, help="论文 Dataset1000/10000 CSV")
    p.add_argument("--order", help="从论文数据集中选择一个 Order")
    p.add_argument("--pallet", nargs=3, type=float, metavar=("L", "W", "H"), help="覆盖输入中的托盘尺寸")
    p.add_argument("--support", type=float, default=1.0, help="最小底面支撑率，0 到 1")
    p.add_argument("--algorithm",choices=["basic","paper","robot2025"],default="basic",help="基础、2024两阶段、2025开放方向研究实现")
    p.add_argument("--open-direction",choices=["+X","-X","+Y","-Y","+Z"],default="+Z",help="2025固定来向，负方向使用--open-direction=-X")
    p.add_argument("--paper-config",type=Path,help="论文模式参数JSON；未提供的参数使用显式研究默认值")
    p.add_argument("--robot-scene",type=Path,help="为robot2025启用EC66离线IK/碰撞/路径检查；需要工位配置JSON")
    p.add_argument("--output-csv", type=Path, default=ROOT / "output" / "demo_placements.csv")
    p.add_argument("--output-json", type=Path, help="结构化装箱方案 JSON")
    p.add_argument("--save-plot", type=Path)
    p.add_argument("--no-show", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from ananno_phase2.gui import launch_gui, should_launch_gui
    if should_launch_gui(argv):
        return launch_gui()
    args = parser().parse_args(argv)
    if args.robot_scene and args.algorithm!='robot2025':raise ValueError('--robot-scene仅用于robot2025模式')
    json_pallet = None
    import_metadata = None
    if args.dataset:
        if args.order is None:
            raise ValueError("使用 --dataset 时必须同时提供 --order")
        if args.pallet is None:
            raise ValueError("使用 --dataset 时必须通过 --pallet 指定托盘长、宽和最大高度")
        boxes = read_order_dataset(args.dataset, args.order)
    elif args.input_json:
        json_pallet, boxes = read_packing_json(args.input_json)
        if json_pallet is None and args.pallet is None:
            raise ValueError("接口JSON未提供托盘尺寸；请通过 --pallet 指定长、宽和限高")
    elif args.input and args.input.suffix.lower() == ".xlsx":
        from ananno_phase2.xlsx_input import read_boxes_xlsx
        json_pallet, boxes, import_metadata = read_boxes_xlsx(args.input)
        for warning in import_metadata["warnings"]: print(warning)
        if json_pallet is None and args.pallet is None:
            raise ValueError("Excel 未提供统一托盘尺寸；请通过 --pallet 指定长、宽和限高")
    else:
        boxes = read_boxes_csv(args.input) if args.input else demo_boxes()
    pallet = Pallet(*args.pallet) if args.pallet else (json_pallet or Pallet(12, 10, 10))
    if args.paper_config and args.algorithm not in ("paper","robot2025"): raise ValueError("--paper-config 仅用于 paper/robot2025")
    if args.algorithm in ("paper","robot2025"):
        from ananno_phase2.paper_config import PaperConfig
        from ananno_phase2.paper_pipeline import PaperTwoPhasePacker,annotate_document
        parameters=json.loads(args.paper_config.read_text(encoding="utf-8-sig")) if args.paper_config else {}
        if args.algorithm=="robot2025":
            from ananno_phase2.robot_pipeline import RobotTwoPhasePacker,annotate_robot_document
            from ananno_phase2.robot_approach import ApproachConfig
            verifier=None
            if args.robot_scene:
                import os
                dependency_dir=Path(os.environ.get('ANANNO_ROBOT_DEPS') or ROOT/'robot_runtime/site-packages')
                if dependency_dir.is_dir():sys.path.insert(0,str(dependency_dir))
                from ananno_phase2.robot_offline import OfflineRobotVerifier
                verifier=OfflineRobotVerifier(args.robot_scene)
            packer=RobotTwoPhasePacker(pallet,PaperConfig(**parameters),ApproachConfig(args.open_direction),robot_verifier=verifier)
        else:packer=PaperTwoPhasePacker(pallet,PaperConfig(**parameters))
        result=packer.pack(boxes,log=print)
        print(("EC66离线IK、网格碰撞、完整抓放路径已通过当前配置模型检查；未验证真实硬件。" if args.robot_scene else "两阶段研究实现；2025模式仅验证固定开放侧，机械臂IK/关节轨迹未验证。") if args.algorithm=="robot2025" else
              "论文两阶段研究实现：层/块 + GA + EP；参数假设已记录，论文数值等价尚未验证。")
    else:
        result = FixedSequencePacker(pallet, args.support).pack(boxes)
        print("阶段性复现：固定序列 + 简化 Extreme Points（不是完整论文复现）")
    print("order pallet box   x     y     z   pose    L     W     H")
    for p in result.placements:
        print(f"{p.order:>5} {p.pallet_index+1:>6} {p.box.id:<4} {p.point.x:>5g} {p.point.y:>5g} {p.point.z:>5g} "
              f"{p.orientation.code:<5} {p.orientation.length:>5g} {p.orientation.width:>5g} {p.orientation.height:>5g}")
    write_placements_csv(args.output_csv, result)
    output_json = args.output_json
    document=write_packing_plan_json(None,result)
    if import_metadata is not None: document["input_import"] = import_metadata
    if args.algorithm in ("paper","robot2025"):
        if args.algorithm=="robot2025":annotate_robot_document(document,packer)
        else:annotate_document(document,packer.diagnostics)
        if output_json is None: output_json=ROOT/"output"/("robot2025_plan.json" if args.algorithm=="robot2025" else "paper_plan.json")
    if args.input_json and output_json is None:
        output_json = ROOT / "output" / "packing_plan.json"
    if output_json:
        output_json.parent.mkdir(parents=True,exist_ok=True)
        output_json.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"总箱数={len(boxes)}，已放置={len(result.placements)}，未放置={len(result.unplaced)}，"
          f"托盘数={result.pallet_count}，体积利用率={result.utilization:.2%}")
    for item in result.unplaced:
        print(f"未放置 {item.box.id}: {item.reason}")
    print(f"结果 CSV: {args.output_csv}")
    if output_json:
        print(f"结果 JSON: {output_json}")
    if args.save_plot or not args.no_show:
        from ananno_phase2.visualize import plot_result
        plot_result(result, pallet, args.save_plot, show=not args.no_show,document=document)
        if args.save_plot:
            print(f"三维图: {args.save_plot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
