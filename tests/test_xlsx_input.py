import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook
from ananno_phase2.workbench_service import inspect_input, run_packing_job
from main import main


class XlsxInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.path = self.folder / "boxes.xlsx"

    def tearDown(self):
        self.temp.cleanup()

    def workbook(self, headers, rows, title="最终挑选结果", notes=False):
        book = Workbook()
        sheet = book.active
        sheet.title = title
        sheet.append(headers)
        for row in rows: sheet.append(row)
        if notes:
            book.create_sheet("说明").append(["这是说明，不是箱子"])
        book.save(self.path)
        book.close()

    def test_expanded_chinese_rows_ignore_parts_and_orders(self):
        self.workbook(["箱子序号", "销售订单号", "Box类型", "实际包装数量", "箱子长", "箱子宽", "箱子高", "总重量", "托盘长", "托盘宽", "托盘高"],
                      [[1, "A", "T", 92, 2, 2, 1, .5, 4, 4, 4],
                       [2, "B", "T", 92, 2, 2, 1, .5, 4, 4, 4]], notes=True)
        info = inspect_input(self.path)
        self.assertEqual(info["kind"], "xlsx")
        self.assertEqual(info["summaries"], {"全部箱子": {"boxes": 2, "box_types": 1}})
        self.assertEqual(info["pallet"], (4, 4, 4))
        result = run_packing_job(self.path, "全部箱子", 4, 4, 4, 1, self.folder / "out")
        self.assertEqual(result["packed_box_count"], 2)
        items = result["document"]["pallets"][0]["packed_items"]
        self.assertEqual([i["id"] for i in items], ["1", "2"])
        self.assertEqual(sum(i["weight"] for i in items), 1)
        self.assertEqual(result["document"]["input_import"]["worksheet"], "最终挑选结果")

    def test_english_quantity_expands_and_cli_uses_pallet(self):
        self.workbook(["box_type", "length", "width", "height", "quantity", "pallet_length", "pallet_width", "pallet_height"],
                      [["T", 2, 2, 1, 3, 4, 4, 4]])
        out = self.folder / "cli.json"
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(["--input", str(self.path), "--output-json", str(out),
                         "--output-csv", str(self.folder / "cli.csv"), "--no-show"])
        import json
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(doc["summary"]["packed_box_count"], 3)
        self.assertEqual(doc["pallet"], {"length": 4, "width": 4, "height": 4})

    def test_missing_optional_columns_and_mixed_pallets(self):
        self.workbook(["长", "宽", "高"], [[2, 2, 1]], title="货物")
        info = inspect_input(self.path)
        self.assertEqual(info["summaries"]["全部箱子"]["boxes"], 1)
        self.assertIsNone(info["pallet"])
        self.assertTrue(info["warnings"])
        self.workbook(["length", "width", "height", "pallet_length", "pallet_width", "pallet_height"],
                      [[1, 1, 1, 4, 4, 4], [1, 1, 1, 5, 5, 5]])
        info = inspect_input(self.path)
        self.assertIsNone(info["pallet"])
        self.assertTrue(any("多种托盘" in s for s in info["warnings"]))

    def test_bad_numbers_report_sheet_and_row(self):
        for headers, rows in [
            (["length", "width", "height"], [[0, 1, 1]]),
            (["length", "width", "height"], [["NaN", 1, 1]]),
            (["length", "width", "height"], [[None, 1, 1]]),
            (["length", "width", "height", "quantity"], [[1, 1, 1, 1.5]]),
            (["length", "width", "height", "weight"], [[1, 1, 1, -1]]),
            (["length", "width", "height"], [["=1+1", 1, 1]]),
        ]:
            with self.subTest(rows=rows):
                self.workbook(headers, rows)
                with self.assertRaisesRegex(ValueError, "最终挑选结果.*第 2 行"):
                    inspect_input(self.path)

    def test_reject_duplicate_ids_and_ambiguous_sheets(self):
        self.workbook(["id", "length", "width", "height"], [["a", 1, 1, 1], ["a", 1, 1, 1]])
        with self.assertRaisesRegex(ValueError, "重复"):
            inspect_input(self.path)
        book = Workbook()
        for sheet in (book.active, book.create_sheet("第二份")):
            sheet.append(["length", "width", "height"])
            sheet.append([1, 1, 1])
        book.save(self.path); book.close()
        with self.assertRaisesRegex(ValueError, "多个.*工作表"):
            inspect_input(self.path)

    def test_header_after_title_blank_rows_and_unsupported_format(self):
        self.workbook(["箱体数据"], [[None], [" Length ", "WIDTH", "Height"], [1, 2, 3], [None, None, None]], title="货物")
        self.assertEqual(inspect_input(self.path)["summaries"]["全部箱子"]["boxes"], 1)
        self.workbook(["foo"], [[1]])
        with self.assertRaisesRegex(ValueError, "长.*宽.*高"):
            inspect_input(self.path)
        old = self.folder / "old.xls"; old.write_text("test")
        with self.assertRaisesRegex(ValueError, "xlsx"):
            inspect_input(old)


if __name__ == "__main__":
    unittest.main()
