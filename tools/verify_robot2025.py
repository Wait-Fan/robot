"""真实工作线程、小样例约束对比、只读XLSX子样本验证。"""
import argparse
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ananno_phase2.models import Box,Pallet
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2.paper_pipeline import PaperTwoPhasePacker
from ananno_phase2.robot_pipeline import RobotTwoPhasePacker,annotate_robot_document
from ananno_phase2.robot_approach import ApproachConfig,OpenDirectionModel
from ananno_phase2.io import write_packing_plan_json,write_placements_csv
from ananno_phase2.qt_workbench_2025 import RobotWorkbench
from PyQt5 import QtCore as C,QtGui as G,QtWidgets as W


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--xlsx',type=Path,default=Path(r'E:\范卓燃\码垛算法\文件\数据集\668箱子数据集\668箱子数据集.xlsx'))
    args=parser.parse_args()
    folder=ROOT/'output/robot2025_validation';folder.mkdir(parents=True,exist_ok=True)
    app=W.QApplication.instance() or W.QApplication([]);app.setStyle('Fusion')
    if not G.QFontDatabase().families():
        for font in ('msyh.ttc','segoeui.ttf','seguisb.ttf'):
            path=Path('C:/Windows/Fonts')/font
            if path.exists():G.QFontDatabase.addApplicationFont(str(path))
    window=RobotWorkbench(ROOT);window.output_dir=folder/'gui_run';logs=[]
    report={'python':sys.executable,'pyqt':C.PYQT_VERSION_STR,'gui':'PyQt5',
            'is_complete_reproduction':False,'ik_verified':False,'joint_trajectory_verified':False}
    try:
        window.approach_direction='-X';window._mode_changed();window.load_input_file(ROOT/'examples/paper_two_phase.json')
        errors=[];window._error=errors.append
        window.show();window.start_packing();deadline=time.monotonic()+25
        while window.running and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
        assert not window.running,'GUI worker timed out'
        assert window.document is not None,errors or window.log_lines
        doc=window.document
        assert doc['summary']['packed_box_count']==9
        assert doc['robot_diagnostics']['passed'] and len(doc['robot_diagnostics']['checks'])==9
        assert doc['paper_diagnostics']['phase1']['phase1_box_count']==8
        report['gui_sample']={'summary':doc['summary'],'robot':doc['robot_diagnostics'],'result':str(window.result_path)}
        report['renders']=[]
        for width,height in ((1920,1080),(1280,800)):
            window.resize(width,height)
            for _ in range(3):app.processEvents()
            image=folder/f'robot2025_{width}x{height}.png';assert window.grab().save(str(image))
            report['renders'].append(str(image))
        window.mode_combo.setCurrentText('论文两阶段')
        assert '需重新计算' in window.mode_banner.text()
        logs.extend(window.log_lines)

        cfg=replace(PaperConfig(),population_size=12,mu=6,lambda_=6,generations=3,max_stagnation=2)
        boxes=[Box('A',1,1,1,1,'A'),Box('B',1,1,1,1,'B')];pallet=Pallet(3,1,1)
        old=PaperTwoPhasePacker(pallet,cfg).pack(boxes)
        model=OpenDirectionModel(ApproachConfig('-X'));previous=[];blocked=[]
        for item in sorted(old.placements,key=lambda p:p.order):
            if model.blockers(item,previous):blocked.append(item.box.id)
            previous.append(item)
        new=RobotTwoPhasePacker(pallet,cfg,ApproachConfig('-X'));result=new.pack(boxes,log=logs.append)
        assert old.pallet_count==1 and result.pallet_count==2 and new.rejected>0 and blocked==['B']
        proof=annotate_robot_document(write_packing_plan_json(None,result),new)
        (folder/'side_approach_counterexample.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
        report['mechanism_example']={'2024_pallets':old.pallet_count,'2024_blocked_ids':blocked,
            '2025_pallets':result.pallet_count,'rejected_inside_ga':new.rejected,
            'interpretation':'Side approach conflicts with inherited alignment; mechanism test, not industrial performance gain'}

        # 在独立进程读取原2024算法，不生成来源目录pyc，输出只写本验证目录。
        manifest=json.loads((ROOT/'provenance/baseline_2024_manifest.json').read_text(encoding='utf-8'))
        original=Path(manifest['source_project']);out=folder/'original2024_sample.json'
        completed=subprocess.run([sys.executable,'-B',str(original/'main.py'),'--algorithm','paper',
            '--input-json',str(ROOT/'examples/paper_two_phase.json'),'--output-json',str(out),
            '--output-csv',str(folder/'original2024_positions.csv'),'--no-show'],capture_output=True,timeout=30)
        assert completed.returncode==0,completed.stderr
        from ananno_phase2.io import read_packing_json
        sample_pallet,sample_boxes=read_packing_json(ROOT/'examples/paper_two_phase.json')
        inherited=PaperTwoPhasePacker(sample_pallet).pack(sample_boxes)
        inherited_doc=write_packing_plan_json(None,inherited)
        old_doc=json.loads(out.read_text(encoding='utf-8'))
        assert inherited_doc['pallets']==old_doc['pallets'] and inherited_doc['summary']==old_doc['summary']
        report['inherited_2024_matches_original_sample']=True

        xlsx=args.xlsx
        if xlsx.exists():
            from ananno_phase2.xlsx_input import read_boxes_xlsx
            pallet,all_boxes,metadata=read_boxes_xlsx(xlsx)
            assert all_boxes and pallet is not None
            counts={};subset=[]
            for box in all_boxes:
                if box.group not in counts and len(counts)>=4:continue
                if counts.get(box.group,0)>=6:continue
                subset.append(box);counts[box.group]=counts.get(box.group,0)+1
            assert len(subset)==24
            baseline=PaperTwoPhasePacker(pallet,cfg).pack(subset)
            robot=RobotTwoPhasePacker(pallet,cfg,ApproachConfig('+Z'))
            started=time.perf_counter();packed=robot.pack(subset,log=logs.append)
            assert len(packed.placements)==24 and robot.robot_diagnostics['passed']
            doc=annotate_robot_document(write_packing_plan_json(None,packed),robot)
            doc['input_import']={**metadata,'validation_subset':'up to six boxes per first four types, input order retained',
                                 'original_box_count':len(all_boxes),'subset_box_count':24}
            (folder/'xlsx_subset24_plan.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
            write_placements_csv(folder/'xlsx_subset24_positions.csv',packed)
            report['xlsx_subset']={'source':str(xlsx),'source_box_count':len(all_boxes),'tested_box_count':24,
                'baseline_pallets':baseline.pallet_count,'robot_pallets':packed.pallet_count,
                'robot_seconds':time.perf_counter()-started,'open_direction':'+Z','passed':True,
                'full_source_robot_run_performed':False}
        else:report['xlsx_subset']={'tested':False,'reason':'local source not found'}
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (folder/'run.log').write_text('\n'.join(logs),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        if window.running:
            window.stop_packing()
            while window.running:app.processEvents();time.sleep(.005)
        window.close();window.deleteLater();app.processEvents()


if __name__=='__main__':main()
