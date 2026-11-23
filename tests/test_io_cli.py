import csv
import tempfile
import unittest
from pathlib import Path

from ananno_phase2.io import read_boxes_csv, write_placements_csv
from ananno_phase2.models import Pallet
from ananno_phase2.packer import FixedSequencePacker
from main import main


class IOAndCliTests(unittest.TestCase):
    def test_csv_read_and_write(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "boxes.csv"
            source.write_text("id,length,width,height\nA,2,3,1\n", encoding="utf-8")
            boxes = read_boxes_csv(source)
            result = FixedSequencePacker(Pallet(3, 3, 3)).pack(boxes)
            target = Path(td) / "placed.csv"
            write_placements_csv(target, result)
            with target.open(encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["box_id"], "A")
            self.assertIn(rows[0]["orientation"], {"Z0", "Z90"})

    def test_csv_errors_include_row_or_missing_columns(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "bad.csv"
            source.write_text("id,length\nA,nope\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "缺少列"):
                read_boxes_csv(source)

            source.write_text("id,length,width,height\nA,nope,2,3\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "第 2 行.*length"):
                read_boxes_csv(source)

    def test_cli_generates_result_csv(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "result.csv"
            code = main(["--output-csv", str(out), "--no-show"])
            self.assertEqual(code, 0)
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
