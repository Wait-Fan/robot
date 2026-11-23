import copy
import json
import tempfile
import unittest
from pathlib import Path

from ananno_phase2.wcs_import import convert_wcs_document
from ananno_phase2.workbench_service import inspect_input
from ananno_phase2.workbench_service import run_packing_job
from ananno_phase2.io import read_packing_json


class WcsImportTests(unittest.TestCase):
    def setUp(self):
        self.document={"code":200,"msg":"ok","data":[
            {"box_type":"A","length":4,"width":3,"height":2,"weight":1,"target_num":3,"case_type":"MH423C","order_id":"ignored"},
            {"box_type":"B","length":2,"width":2,"height":1,"weight":2,"target_num":2,"case_type":"WR246"}]}

    def test_all_records_are_kept_unless_filter_is_explicit(self):
        original=copy.deepcopy(self.document)
        converted=convert_wcs_document(self.document,(12,10,10))
        self.assertEqual(len(converted["boxes"]),2)
        self.assertEqual(converted["import_info"]["kept_box_count"],5)
        self.assertEqual(converted["import_info"]["excluded_record_count"],0)
        self.assertEqual(converted["pallet"],{"length":12,"width":10,"height":10})
        self.assertNotIn("order_id",converted["boxes"][0])
        self.assertEqual(self.document,original)

    def test_filter_is_reported_and_quantities_expand_in_real_reader(self):
        converted=convert_wcs_document(self.document,(12,10,10),case_type="MH423C")
        self.assertEqual(converted["import_info"]["excluded_record_count"],1)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"converted.json"
            path.write_text(json.dumps(converted))
            pallet,boxes=read_packing_json(path)
            self.assertEqual(len(boxes),3)
            self.assertEqual([b.id for b in boxes],["A-001","A-002","A-003"])
            self.assertEqual(inspect_input(path)["summaries"]["全部箱子"]["boxes"],3)

    def test_invalid_data_and_no_match_fail_explicitly(self):
        for bad in ({"data":[]},{"data":"bad"},{"pallet":{},"boxes":[]}):
            with self.assertRaises(ValueError): convert_wcs_document(bad,(12,10,10))

    def test_input_summary_preserves_distinct_explicit_types_with_same_size(self):
        raw=copy.deepcopy(self.document)
        raw["data"][1].update(length=4,width=3,height=2)
        converted=convert_wcs_document(raw,(12,10,10))
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"different_products.json"
            path.write_text(json.dumps(converted))
            self.assertEqual(inspect_input(path)["summaries"]["全部箱子"]["box_types"],2)

    def test_original_data_wrapper_reads_all_and_uses_explicit_service_dimensions(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"original_wcs.json"
            path.write_text(json.dumps(self.document))
            pallet,boxes=read_packing_json(path)
            self.assertIsNone(pallet)
            self.assertEqual(len(boxes),5)
            info=inspect_input(path)
            self.assertEqual(info["kind"],"wcs_json")
            self.assertEqual(info["case_types"],{"MH423C":1,"WR246":1})
            output=run_packing_job(path,"全部箱子",12,10,10,1,Path(td)/"out",algorithm="basic")
            self.assertEqual(output["packed_box_count"],5)
            self.assertEqual(output["document"]["pallet"],{"length":12,"width":10,"height":10})
        with self.assertRaises(ValueError): convert_wcs_document(self.document,(12,10,10),case_type="missing")
        for field,value in (("length",0),("weight",-1),("target_num",1.5),("height",float("nan"))):
            bad=copy.deepcopy(self.document)
            bad["data"][0][field]=value
            with self.assertRaises(ValueError): convert_wcs_document(bad,(12,10,10))
