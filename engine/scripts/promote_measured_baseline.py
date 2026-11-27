"""Promote a complete measured diagnostic, never an enrichment validation."""
import argparse
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ppservice.persona_accuracy import DATA,canonical,read_json,file_hash
from ppservice.historical_baseline import checked_bundle


def promote(source,target):
    files={'comparison-2024.json':'comparison-2024.json','comparison-2024-reversed.json':'comparison-2024-reversed.json',
           'sources-reviewed.json':'sources-reviewed.json','run-manifest.json':'measured-run.json'}
    # Validate in the research directory before touching the service bundle.
    (source/'measured-run.json').write_bytes(canonical(read_json(source/'run-manifest.json')))
    bundle=dict(kind='historical-diagnostic-v1',artifacts={dest:file_hash(source/original) for original,dest in files.items()})
    path=source/'historical-baseline-2024.json';path.write_bytes(canonical(bundle))
    checked_bundle(path)
    target.mkdir(parents=True,exist_ok=True)
    for original,dest in files.items():shutil.copyfile(source/original,target/dest)
    shutil.copyfile(path,target/path.name)
    print(checked_bundle(target/path.name))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);ap.add_argument('--target',type=Path,default=DATA)
    a=ap.parse_args();promote(a.directory,a.target)
