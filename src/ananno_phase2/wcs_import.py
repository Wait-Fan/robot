"""将 zhuang 的本地接口 JSON 转换为纯装箱输入，不连接数据库/接口。"""
from collections import Counter
from .workbench_service import finite_number


def convert_wcs_document(document,pallet_dimensions,*,case_type=None):
    if not isinstance(document,dict) or not isinstance(document.get("data"),list) or not document["data"]:
        raise ValueError("需要非空data数组的zhuang接口JSON")
    if len(pallet_dimensions)!=3: raise ValueError("必须明确提供托盘长、宽和限高")
    dimensions=[finite_number(v,"托盘尺寸",positive=True) for v in pallet_dimensions]
    entries=[]
    all_types=Counter()
    selected_types=Counter()
    selected_count=0
    for index,row in enumerate(document["data"],1):
        if not isinstance(row,dict): raise ValueError(f"data第{index}项必须是对象")
        model=str(row.get("case_type") or "")
        all_types[model]+=1
        if case_type is not None and model!=case_type: continue
        raw_quantity=row.get("target_num",1)
        try:
            quantity=int(raw_quantity)
            if isinstance(raw_quantity,bool) or quantity<=0 or float(raw_quantity)!=quantity: raise ValueError
        except (TypeError,ValueError,OverflowError):
            raise ValueError(f"data第{index}项target_num必须是正整数") from None
        entry={"box_type":str(row.get("box_type") or f"BOX{index}"),
               **{key:finite_number(row.get(key),f"data第{index}项{key}",positive=True)
                  for key in ("length","width","height")},
               "target_num":quantity,
               "weight":finite_number(row.get("weight") or 0,f"data第{index}项weight"),
               "source_record_index":index}
        entries.append(entry)
        selected_types[model]+=1
        selected_count+=quantity
    if not entries: raise ValueError("筛选后没有箱体记录")
    return {"pallet":dict(zip(("length","width","height"),dimensions)),"boxes":entries,
            "import_info":{"source_format":"zhuang WCS response data[]","source_record_count":len(document["data"]),
               "kept_record_count":len(entries),"kept_box_count":selected_count,
               "excluded_record_count":len(document["data"])-len(entries),"case_type_filter":case_type,
               "source_case_types":dict(all_types),"kept_case_types":dict(selected_types),
               "pallet_assumption":"All selected boxes use the single explicitly supplied pallet size; source case_type is not an algorithm constraint.",
               "ignored_business_fields":["order_id","case_group","priority","loading_rate","product_code"]}}
