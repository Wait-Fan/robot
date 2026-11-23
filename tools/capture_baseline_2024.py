"""只读2024工程；在2025工程内保存基线快照和校验清单。"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def tracked(root):
    files = [p for p in root.iterdir() if p.is_file()]
    for name in ('src','tests','tools','docs','data','examples','.vscode'):
        if (root/name).exists(): files.extend((root/name).rglob('*'))
    return sorted(p for p in files if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('--verify',action='store_true')
    args=parser.parse_args();folder=ROOT/'provenance';manifest_path=folder/'baseline_2024_manifest.json'
    if args.verify:
        document=json.loads(manifest_path.read_text(encoding='utf-8'))
        current={p.relative_to(args.source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked(args.source)}
        assert current == document['files'], '2024来源文件集合或内容发生变化'
        print(f"2024_SOURCE_UNCHANGED: {len(current)} files")
        return
    if manifest_path.exists(): raise ValueError('基线已存在，不能覆盖溯源记录；使用--verify检查')
    folder.mkdir(parents=True,exist_ok=True)
    files=tracked(args.source)
    records={p.relative_to(args.source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    archive=folder/'baseline_2024_source.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,p.relative_to(args.source).as_posix())
    document={'source_project':str(args.source.resolve()),'inherited_target':r'E:\范卓燃\码垛算法\文件\装箱算法\robot\robot',
        'captured_at':datetime.now().astimezone().isoformat(),'baseline':'Ananno2024 staged research implementation v0.4.1',
        'numerical_equivalence_verified':False,'snapshot_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':records}
    manifest_path.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'CAPTURED: {len(records)} files')


if __name__=='__main__': main()
