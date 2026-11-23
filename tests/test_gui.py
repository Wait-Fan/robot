import csv
import tempfile
import unittest
from pathlib import Path

from ananno_phase2.gui import (
    build_output_paths,
    dataset_order_summaries,
    run_packing_job,
    should_launch_gui,
)


DATASET = """Order,Product,Quantity,Length,Width,Height,Weight
100,501,2,4,3,2,5.5
100,502,1,2,2,1,1.0
200,601,3,1,1,1,0.5
"""


class GuiServiceTests(unittest.TestCase):
    def test_dataset_summary_counts_types_and_expanded_boxes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "dataset.csv"
            path.write_text(DATASET, encoding="utf-8")
            summaries = dataset_order_summaries(path)
        self.assertEqual(summaries["100"], {"box_types": 2, "boxes": 3})
        self.assertEqual(summaries["200"], {"box_types": 1, "boxes": 3})

    def test_output_paths_include_order(self):
        paths = build_output_paths(Path("out"), "35430")
        self.assertEqual(paths["json"], Path("out/order_35430_plan.json"))
        self.assertEqual(paths["csv"], Path("out/order_35430_positions.csv"))
        self.assertEqual(paths["png"], Path("out/order_35430.png"))

    def test_packing_job_generates_all_three_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            dataset = Path(td) / "dataset.csv"
            dataset.write_text(DATASET, encoding="utf-8")
            result = run_packing_job(dataset, "100", 10, 8, 6, 1.0, Path(td) / "output")
            self.assertEqual(result["input_box_count"], 3)
            self.assertEqual(result["packed_box_count"], 3)
            self.assertEqual(result["unplaced_box_count"], 0)
            self.assertTrue(result["paths"]["json"].exists())
            self.assertTrue(result["paths"]["csv"].exists())
            self.assertGreater(result["paths"]["png"].stat().st_size, 1000)

    def test_direct_start_launches_gui_but_cli_arguments_do_not(self):
        self.assertTrue(should_launch_gui([]))
        self.assertTrue(should_launch_gui(["--gui"]))
        self.assertFalse(should_launch_gui(["--dataset", "data.csv"]))


if __name__ == "__main__":
    unittest.main()
