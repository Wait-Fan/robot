import tempfile
import unittest
from pathlib import Path

from ananno_phase2.io import read_order_dataset
from ananno_phase2.models import Pallet
from main import main


DATASET = """Order,Product,Quantity,Length,Width,Height,Weight
100,501,2,4,3,2,5.5
100,502,1,2,2,1,1.0
200,601,3,1,1,1,0.5
"""


class PaperDatasetTests(unittest.TestCase):
    def test_selects_one_order_and_expands_quantity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "dataset.csv"
            path.write_text(DATASET, encoding="utf-8")
            boxes = read_order_dataset(path, "100")
        self.assertEqual([b.id for b in boxes], ["501-001", "501-002", "502-001"])
        self.assertEqual([b.group for b in boxes], ["501", "501", "502"])
        self.assertEqual(boxes[0].weight, 5.5)

    def test_unknown_order_lists_example_order_ids(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "dataset.csv"
            path.write_text(DATASET, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "100.*200"):
                read_order_dataset(path, "999")

    def test_rejects_non_positive_quantity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "dataset.csv"
            path.write_text(DATASET.replace("100,501,2", "100,501,0"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Quantity"):
                read_order_dataset(path, "100")

    def test_cli_runs_selected_order_with_required_pallet(self):
        with tempfile.TemporaryDirectory() as td:
            dataset = Path(td) / "dataset.csv"
            dataset.write_text(DATASET, encoding="utf-8")
            output = Path(td) / "plan.json"
            code = main([
                "--dataset", str(dataset), "--order", "100",
                "--pallet", "10", "8", "6",
                "--output-json", str(output), "--no-show",
            ])
            self.assertEqual(code, 0)
            self.assertTrue(output.exists())

    def test_cli_dataset_requires_order_and_pallet(self):
        with tempfile.TemporaryDirectory() as td:
            dataset = Path(td) / "dataset.csv"
            dataset.write_text(DATASET, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "--order"):
                main(["--dataset", str(dataset), "--pallet", "10", "8", "6", "--no-show"])
            with self.assertRaisesRegex(ValueError, "--pallet"):
                main(["--dataset", str(dataset), "--order", "100", "--no-show"])


if __name__ == "__main__":
    unittest.main()
