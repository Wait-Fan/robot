import tempfile
import subprocess
import sys
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from ananno_phase2.models import Box,Pallet
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2.paper_pipeline import PaperTwoPhasePacker,NoPaperSolution
from ananno_phase2.workbench_service import run_packing_job,load_result
from ananno_phase2.packer import PackingCancelled


class PaperPipelineTests(unittest.TestCase):
    def setUp(self):
        self.config=replace(PaperConfig(),population_size=12,mu=6,lambda_=6,generations=3,max_stagnation=2)

    def test_layer_plus_residual_conserves_every_box_and_validates(self):
        boxes=[Box(f"a{i}",2,2,2,1,"A") for i in range(8)]+[Box("residual",1,1,1,1,"B")]
        packer=PaperTwoPhasePacker(Pallet(4,4,6),self.config)
        result=packer.pack(boxes)
        self.assertEqual(len(result.placements),9)
        self.assertEqual({p.box.id for p in result.placements},{b.id for b in boxes})
        self.assertEqual(sorted(p.order for p in result.placements),list(range(1,10)))
        self.assertEqual(result.unplaced,[])
        self.assertTrue(packer.diagnostics["all_hard_constraints_pass"])
        self.assertGreater(packer.diagnostics["phase1"]["phase1_box_count"],0)
        self.assertGreater(packer.diagnostics["residual_box_count"],0)

    def test_residual_only_adds_pallets_and_is_reproducible(self):
        boxes=[Box("a",3,3,1,1,"A"),Box("b",3,3,2,1,"B"),Box("c",3,3,3,1,"C")]
        pallet=Pallet(3,3,3)
        first=PaperTwoPhasePacker(pallet,self.config)
        a=first.pack(boxes)
        b=PaperTwoPhasePacker(pallet,self.config).pack(boxes)
        self.assertEqual(len(a.placements),3)
        self.assertEqual(a.pallet_count,2)
        self.assertEqual([(p.box.id,p.point,p.orientation,p.pallet_index) for p in a.placements],
                         [(p.box.id,p.point,p.orientation,p.pallet_index) for p in b.placements])
        self.assertEqual(first.diagnostics["phase1"]["phase1_box_count"],0)

    def test_impossible_box_raises_instead_of_claiming_full_shipment(self):
        with self.assertRaises(NoPaperSolution):
            PaperTwoPhasePacker(Pallet(1,1,1),self.config).pack([Box("oversized",2,2,2)])

    def test_fixed_capacity_failure_restarts_ga_with_an_extra_pallet(self):
        boxes=[Box("a",2,2,2,1,"A"),Box("b",2,2,2,1,"B")]
        packer=PaperTwoPhasePacker(Pallet(3,3,3),self.config)
        result=packer.pack(boxes)
        self.assertEqual(result.pallet_count,2)
        self.assertEqual([row["feasible"] for row in packer.diagnostics["ga_attempts"]],[False,True])

    def test_unstable_single_box_fails_without_silently_relaxing_com(self):
        config=replace(self.config,pallet_weight=0,com_deviation_fraction=.1)
        with self.assertRaises(NoPaperSolution):
            PaperTwoPhasePacker(Pallet(10,10,10),config).pack([Box("heavy",1,1,1,100)])

    def test_service_exports_parameters_and_never_claims_complete_reproduction(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"boxes.csv"
            source.write_text("id,length,width,height,weight\na,2,2,1,1\nb,2,2,2,1\n")
            output=run_packing_job(source,"全部箱子",2,2,3,1,Path(td)/"out",algorithm="paper",paper_config=self.config)
            doc=load_result(output["paths"]["json"])
            self.assertFalse(doc["is_complete_reproduction"])
            self.assertEqual(doc["paper_diagnostics"]["config"]["seed"],42)
            self.assertTrue(doc["paper_diagnostics"]["all_hard_constraints_pass"])

    def test_ungrouped_equal_boxes_export_the_same_dimensional_type(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"same.csv"
            source.write_text("id,length,width,height\n"+"".join(f"b{i},2,2,1\n" for i in range(4)))
            output=run_packing_job(source,"全部箱子",4,4,4,1,Path(td)/"out",algorithm="paper",paper_config=self.config)
            doc=load_result(output["paths"]["json"])
            self.assertEqual(len({item["box_type"] for pallet in doc["pallets"] for item in pallet["packed_items"]}),1)
            self.assertEqual(doc["paper_diagnostics"]["mean_pallet_type_count"],1)

    def test_cancel_before_ga_does_not_publish_any_result(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"residuals.csv"
            source.write_text("id,length,width,height\na,2,2,1\nb,2,2,2\n")
            event=threading.Event()
            def log(text):
                if text.startswith("Phase 2"): event.set()
            target=Path(td)/"cancelled"
            with self.assertRaises(PackingCancelled):
                run_packing_job(source,"全部箱子",2,2,3,1,target,algorithm="paper",paper_config=self.config,
                                cancelled=event.is_set,log=log)
            self.assertFalse(list(target.rglob("*.json")))
            self.assertFalse(list(target.rglob("*.csv")))

    def test_cli_paper_mode_writes_audited_two_phase_result(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"plan.json"
            config=Path(td)/"config.json"
            import json
            config.write_text(json.dumps(self.config.to_dict()))
            process=subprocess.run([sys.executable,str(root/"main.py"),"--algorithm","paper","--input-json",
                str(root/"examples/paper_two_phase.json"),"--paper-config",str(config),"--output-json",str(path),
                "--output-csv",str(Path(td)/"positions.csv"),"--no-show"],capture_output=True,timeout=15)
            self.assertEqual(process.returncode,0,process.stderr)
            document=json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["paper_diagnostics"]["phase1"]["phase1_box_count"],8)
            self.assertEqual(document["paper_diagnostics"]["residual_box_count"],1)
