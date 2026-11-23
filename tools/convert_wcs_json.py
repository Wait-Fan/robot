"""显式指定托盘尺寸，将zhuang历史接口JSON转换为本工程可导入格式。"""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ananno_phase2.wcs_import import convert_wcs_document
from ananno_phase2.workbench_service import inspect_input


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input",type=Path)
    parser.add_argument("--pallet",required=True,nargs=3,type=float,metavar=("L","W","H"))
    parser.add_argument("--case-type",help="显式筛选指定型号；省略时保留全部data记录")
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    if args.input.resolve()==args.output.resolve(): raise ValueError("转换输出不能覆盖原始接口文件")
    raw=json.loads(args.input.read_text(encoding="utf-8-sig"))
    converted=convert_wcs_document(raw,args.pallet,case_type=args.case_type)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(converted,ensure_ascii=False,indent=2),encoding="utf-8")
    info=inspect_input(args.output)
    print(json.dumps({"output":str(args.output),"input_summary":info["summaries"],
                      "pallet":converted["pallet"],"conversion":converted["import_info"]},ensure_ascii=False,indent=2))


if __name__=="__main__": main()
