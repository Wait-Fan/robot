import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from ananno_phase2.models import Box, Pallet
from ananno_phase2.packer import FixedSequencePacker
from ananno_phase2 import workbench_service as service


class WorkbenchServiceTests(unittest.TestCase):
    def test_plain_csv_needs_no_order_and_produces_reloadable_result(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "自己的箱子.csv"
            source.write_text("id,length,width,height\nA,2,2,1\nB,2,2,1\n", encoding="utf-8")
            info = service.inspect_input(source)
            self.assertEqual(info["kind"], "csv")
            self.assertEqual(info["summaries"]["全部箱子"]["boxes"], 2)
            output = service.run_packing_job(source, "全部箱子", 2, 2, 1, 1, Path(td) / "out")
            doc = service.load_result(output["paths"]["json"])
            self.assertEqual(doc["summary"]["pallet_count"], 2)
            self.assertEqual([p["packed_items"][0]["id"] for p in doc["pallets"]], ["A", "B"])

    def test_json_loads_pallet_dimensions_and_quantities(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "boxes.json"
            source.write_text(json.dumps({"pallet": {"length": 4, "width": 3, "height": 2},
                "boxes": [{"box_type": "A", "length": 2, "width": 3, "height": 1, "target_num": 4}]}))
            info = service.inspect_input(source)
            self.assertEqual(info["pallet"], (4, 3, 2))
            self.assertEqual(info["summaries"]["全部箱子"], {"box_types": 1, "boxes": 4})

    def test_cancellation_does_not_publish_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "boxes.csv"
            source.write_text("id,length,width,height\nA,1,1,1\nB,1,1,1\n", encoding="utf-8")
            event = threading.Event()
            progress = []
            def report(done, total):
                progress.append((done, total))
                if done == 1:
                    event.set()
            with self.assertRaises(service.PackingCancelled):
                service.run_packing_job(source, "全部箱子", 2, 2, 2, 1, Path(td) / "out",
                                        progress=report, cancelled=event.is_set)
            self.assertIn((1, 2), progress)
            self.assertFalse(list((Path(td) / "out").glob("*_plan.json")))

    def test_progress_counts_oversized_boxes(self):
        progress = []
        result = FixedSequencePacker(Pallet(1, 1, 1)).pack(
            [Box("large", 2, 2, 2), Box("fits", 1, 1, 1)],
            progress=lambda done, total: progress.append((done, total)))
        self.assertEqual(progress, [(0, 2), (1, 2), (2, 2)])
        self.assertEqual(len(result.unplaced), 1)

    def test_all_unplaced_result_has_pallet_geometry(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "boxes.csv"
            source.write_text("id,length,width,height\nA,5,5,5\n")
            output = service.run_packing_job(source, "全部箱子", 1, 1, 1, 1, Path(td))
            doc = service.load_result(output["paths"]["json"])
            self.assertEqual(doc["summary"]["packed_box_count"], 0)
            self.assertEqual(doc["summary"]["unplaced_box_count"], 1)
            self.assertEqual(doc["pallet"], {"length": 1, "width": 1, "height": 1})

    def test_invalid_or_nonfinite_inputs_fail_before_writing(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "bad.csv"
            source.write_text("id,length,width,height\nA,nan,1,1\n")
            with self.assertRaises(ValueError):
                service.inspect_input(source)
            source.write_text("id,length,width,height\nA,1,1,1\n")
            with self.assertRaises(ValueError):
                service.run_packing_job(source, "全部箱子", float("inf"), 1, 1, 1, Path(td) / "out")
            self.assertFalse((Path(td) / "out").exists())

    def test_result_rejects_wrong_schema_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "wrong.json"
            path.write_text('{"boxes": []}')
            with self.assertRaises(ValueError):
                service.load_result(path)
            source = Path(td) / "boxes.csv"
            source.write_text("id,length,width,height\nA,1,1,1\n")
            output = service.run_packing_job(source, "全部箱子", 2, 2, 2, 1, Path(td))
            doc = json.loads(output["paths"]["json"].read_text(encoding="utf-8"))
            doc["pallets"][0]["packed_items"].append(doc["pallets"][0]["packed_items"][0])
            path.write_text(json.dumps(doc))
            with self.assertRaises(ValueError):
                service.load_result(path)

    def test_numeric_strings_in_imported_result_are_normalized_for_plotting(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "boxes.csv"
            source.write_text("id,length,width,height\nA,1,1,1\n")
            output = service.run_packing_job(source, "全部箱子", 2, 2, 2, 1, Path(td))
            doc = json.loads(output["paths"]["json"].read_text(encoding="utf-8"))
            doc["pallets"][0]["pallet"]["length"] = "2"
            doc["pallets"][0]["packed_items"][0]["position"]["x"] = "0"
            output["paths"]["json"].write_text(json.dumps(doc))
            loaded = service.load_result(output["paths"]["json"])
            self.assertIsInstance(loaded["pallets"][0]["pallet"]["length"], float)
            self.assertIsInstance(loaded["pallets"][0]["packed_items"][0]["position"]["x"], float)

    def test_overlapping_boxes_in_history_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "boxes.csv"
            source.write_text("id,length,width,height\nA,1,1,1\nB,1,1,1\n")
            output = service.run_packing_job(source, "全部箱子", 2, 2, 2, 1, Path(td))
            doc = output["document"]
            items = doc["pallets"][0]["packed_items"]
            items[1]["position"] = dict(items[0]["position"])
            output["paths"]["json"].write_text(json.dumps(doc))
            with self.assertRaises(ValueError):
                service.load_result(output["paths"]["json"])

    def test_cancel_during_publication_restores_existing_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "boxes.csv"
            source.write_text("id,length,width,height\nA,1,1,1\n")
            output = service.run_packing_job(source, "全部箱子", 2, 2, 2, 1, Path(td) / "out")
            previous = {key: path.read_bytes() for key, path in output["paths"].items()}
            source.write_text("id,length,width,height\nA,1,1,1\nB,1,1,1\n")
            event = threading.Event()
            replace = Path.replace
            def replace_then_cancel(path, target):
                result = replace(path, target)
                if path.parent.name.startswith(".packing_") and path.name.endswith("_plan.json"):
                    event.set()
                return result
            with patch.object(Path, "replace", replace_then_cancel):
                with self.assertRaises(service.PackingCancelled):
                    service.run_packing_job(source, "全部箱子", 2, 2, 2, 1, Path(td) / "out", cancelled=event.is_set)
            self.assertEqual({key: path.read_bytes() for key, path in output["paths"].items()}, previous)
