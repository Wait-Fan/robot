"""验证转换后的真实WCS输入：完整基础模式与明确标注的两阶段子样本。"""
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ananno_phase2.workbench_service import inspect_input,run_packing_job


def main():
    source=ROOT/"examples/imported/20260720_171800_MH423C.json"
    all_source=ROOT/"examples/imported/20260720_171800_all_uniform_pallet.json"
    folder=ROOT/"output/wcs_import_validation"
    folder.mkdir(parents=True,exist_ok=True)
    report={"inputs":{"MH423C":inspect_input(source),"all_uniform_pallet":inspect_input(all_source)},"computations":[]}
    # 先验证整份2080箱在现有基础装箱器中实际读取、计算和导出。
    started=time.monotonic()
    last_bucket=-1
    def progress(done,total):
        nonlocal last_bucket
        bucket=int(done/max(total,1)*10)
        if bucket!=last_bucket:
            print(f"基础模式 {done}/{total}",flush=True)
            last_bucket=bucket
    output=run_packing_job(source,"全部箱子",1440,2240,720,1,folder/"MH423C_basic_full",
        algorithm="basic",progress=progress,cancelled=lambda:time.monotonic()-started>90)
    report["computations"].append({"scope":"full_MH423C_basic","summary":output["document"]["summary"],
        "elapsed_seconds":output["elapsed_seconds"],"result":str(output["paths"]["json"])})
    # 真实输入首尾各12条，只验证小样本两阶段流程，不冒称整单论文模式验证。
    original=json.loads(source.read_text(encoding="utf-8"))
    sample={"pallet":original["pallet"],"boxes":original["boxes"][:12]+original["boxes"][-12:],
            "sample_info":"ONLY first12 + last12 MH423C records; not full-order validation"}
    sample_path=folder/"MH423C_24_record_sample.json"
    sample_path.write_text(json.dumps(sample,ensure_ascii=False,indent=2),encoding="utf-8")
    started=time.monotonic()
    print("论文两阶段：真实输入的24条子样本",flush=True)
    output=run_packing_job(sample_path,"全部箱子",1440,2240,720,1,folder/"MH423C_paper_sample",
        algorithm="paper",log=lambda text:print(text,flush=True),cancelled=lambda:time.monotonic()-started>90)
    audit=output["document"]["paper_diagnostics"]
    report["computations"].append({"scope":"ONLY_24_record_paper_sample","summary":output["document"]["summary"],
        "phase1_boxes":audit["phase1"]["phase1_box_count"],"residual_boxes":audit["residual_box_count"],
        "all_hard_constraints_pass":audit["all_hard_constraints_pass"],
        "elapsed_seconds":output["elapsed_seconds"],"result":str(output["paths"]["json"])})
    report["not_verified"]=["complete 2080-box order in paper mode","2147-box all-case-types computation","WR246 actual pallet dimensions"]
    (folder/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__": main()
