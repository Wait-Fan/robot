"""验证论文两阶段研究模式的实际输出，生成可复查日志与报告。"""
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ananno_phase2.workbench_service import load_result,run_packing_job


def main():
    folder=ROOT/"output/paper_validation"
    folder.mkdir(parents=True,exist_ok=True)
    rows=[]
    for label,source,order,dims in (
        ("layer_and_residual",ROOT/"examples/paper_two_phase.json","全部箱子",(4,4,6)),
        ("order35430",ROOT/"data/Dataset1000.csv","35430",(1200,800,1400)),
    ):
        logs=[]
        started=time.perf_counter()
        def log(text):
            logs.append(text)
            print(text,flush=True)
        output=run_packing_job(source,order,*dims,1,folder/label,algorithm="paper",log=log)
        document=load_result(output["paths"]["json"])
        audit=document["paper_diagnostics"]
        assert audit["all_hard_constraints_pass"]
        assert document["summary"]["unplaced_box_count"]==0
        assert not document["is_complete_reproduction"]
        rows.append({"case":label,"summary":document["summary"],
                     "phase1_boxes":audit["phase1"]["phase1_box_count"],
                     "residual_boxes":audit["residual_box_count"],
                     "ga_attempts":len(audit["ga_attempts"]),
                     "mean_residual_compactness":audit["mean_residual_compactness"],
                     "elapsed_seconds":time.perf_counter()-started,
                     "result":str(output["paths"]["json"]),"all_hard_constraints_pass":True})
        (folder/f"{label}.log").write_text("\n".join(logs),encoding="utf-8")
    (folder/"report.json").write_text(json.dumps({"python":sys.executable,"cases":rows},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(rows,ensure_ascii=False,indent=2))


if __name__=="__main__": main()
