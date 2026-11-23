"""独立2025发布清单；复制前备份，只允许写入指定的2025目录。"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TARGET=Path(r'E:\范卓燃\码垛算法\文件\装箱算法\复现ananno2025算法\robot')
ROOT_FILES=('.gitignore','main.py','README.md','requirements.txt','requirements-ga.txt','start_workbench.bat','progress.md')


def release_files():
    files=[ROOT/name for name in ROOT_FILES if (ROOT/name).is_file()]
    for name in ('src','tests','tools','docs','data','examples','.vscode','provenance','output/robot2025_validation'):
        files.extend(p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    return sorted(set(files))


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def changes():
    baseline=json.loads((ROOT/'provenance/baseline_2024_manifest.json').read_text(encoding='utf-8'))['files']
    records=[]
    for path in release_files():
        rel=path.relative_to(ROOT).as_posix()
        if rel.startswith(('provenance/','output/')):continue
        current=digest(path)
        if current!=baseline.get(rel):records.append({'file':rel,'change':'modified' if rel in baseline else 'added',
                                                     'baseline_sha256':baseline.get(rel),'sha256':current})
    (ROOT/'provenance/changes_2025.json').write_text(json.dumps({'version':'0.1.0','changes':records},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'CHANGED_OR_ADDED={len(records)}')


def sync(destination):
    target=destination.resolve(strict=True)
    if target!=TARGET.resolve(strict=True):raise ValueError('只允许指定2025目录，拒绝更新2024目录或其他路径')
    if ROOT.resolve()==target:raise ValueError('不允许原地同步')
    backup=target/('backup_before_2025_robot_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    changed=[]
    for source in release_files():
        rel=source.relative_to(ROOT);out=target/rel
        out.resolve().relative_to(target)
        if out.exists() and digest(source)==digest(out):continue
        if out.exists():
            saved=backup/rel;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(out,saved)
        out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,out)
        assert digest(out)==digest(source),str(out)
        changed.append(rel.as_posix())
    print(json.dumps({'copied':len(changed),'destination':str(target),'backup':str(backup),'files':changed},ensure_ascii=False,indent=2))


def package():
    destination=ROOT.parent/'ananno2025_reachability_workbench.zip'
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=8) as archive:
        for path in release_files():archive.write(path,Path('robot')/path.relative_to(ROOT))
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert 'robot/provenance/baseline_2024_source.zip' in archive.namelist()
    print(f'{destination}\n{destination.stat().st_size} bytes')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['changes','sync','package'])
    parser.add_argument('--destination',type=Path,default=TARGET);args=parser.parse_args()
    if args.action=='changes':changes()
    elif args.action=='sync':sync(args.destination)
    else:package()
