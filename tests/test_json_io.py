import json
import tempfile
import unittest
from pathlib import Path

from ananno_phase2.io import read_packing_json, write_packing_plan_json
from ananno_phase2.models import Pallet
from ananno_phase2.packer import FixedSequencePacker
from main import main


class JsonIOTests(unittest.TestCase):
    def _write_input(self, folder: str) -> Path:
        path = Path(folder) / "input.json"
        path.write_text(
            json.dumps(
                {
                    "pallet": {"length": 10, "width": 8, "height": 6},
                    "boxes": [
                        {
                            "box_type": "A",
                            "length": 4,
                            "width": 3,
                            "height": 2,
                            "target_num": 2,
                            "weight": 5.5,
                        },
                        {
                            "box_type": "B",
                            "length": 2,
                            "width": 2,
                            "height": 1,
                            "target_num": 1,
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_json_input_expands_quantities_and_reads_pallet(self):
        with tempfile.TemporaryDirectory() as td:
            pallet, boxes = read_packing_json(self._write_input(td))
        self.assertEqual(pallet, Pallet(10, 8, 6))
        self.assertEqual([b.id for b in boxes], ["A-001", "A-002", "B-001"])
        self.assertEqual([b.group for b in boxes], ["A", "A", "B"])
        self.assertEqual(boxes[0].weight, 5.5)

    def test_json_input_rejects_invalid_quantity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text(
                '{"pallet":{"length":10,"width":8,"height":6},'
                '"boxes":[{"box_type":"A","length":1,"width":1,"height":1,"target_num":0}]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "target_num"):
                read_packing_json(path)

    def test_json_output_contains_algorithm_summary_and_nested_positions(self):
        with tempfile.TemporaryDirectory() as td:
            pallet, boxes = read_packing_json(self._write_input(td))
            result = FixedSequencePacker(pallet).pack(boxes)
            output = Path(td) / "packing_plan.json"
            document = write_packing_plan_json(output, result)
            loaded = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(document, loaded)
        self.assertFalse(loaded["is_complete_reproduction"])
        self.assertEqual(loaded["summary"]["input_box_count"], 3)
        self.assertEqual(loaded["summary"]["packed_box_count"], 3)
        self.assertEqual(loaded["pallets"][0]["packed_items"][0]["box_type"], "A")
        self.assertEqual(loaded["pallets"][0]["packed_items"][0]["position"], {"x": 0.0, "y": 0.0, "z": 0.0})

    def test_cli_uses_json_pallet_and_writes_json_plan(self):
        with tempfile.TemporaryDirectory() as td:
            source = self._write_input(td)
            output = Path(td) / "result.json"
            code = main(["--input-json", str(source), "--output-json", str(output), "--no-show"])
            loaded = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(loaded["summary"]["input_box_count"], 3)
        self.assertEqual(loaded["pallets"][0]["pallet"], {"length": 10.0, "width": 8.0, "height": 6.0})


if __name__ == "__main__":
    unittest.main()
