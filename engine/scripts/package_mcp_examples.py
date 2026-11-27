"""Package qualitative excerpts of existing public runs; never call a model.

Run from any directory: python engine/scripts/package_mcp_examples.py
The regression tests require every packaged source hash and question to match.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
from pp.numbers import from_archive


def main():
    destination = ROOT / 'engine/pp/data/examples'
    destination.mkdir(parents=True, exist_ok=True)
    for source in sorted((ROOT / 'web/public/runs').glob('*.json')):
        if source.stem == 'index':
            continue
        raw = source.read_bytes()
        data = json.loads(raw)
        plan = data['plan']
        source_path = source.relative_to(ROOT).as_posix()
        excerpt = {
            'numbers': from_archive(data),
            'title': data['title'], 'source': data['source'], 'policy_text': data['policy_text'],
            'segments': [{k: row[k] for k in ('id', 'text')} for row in data['segments']],
            'issues': [{**{k: row[k] for k in ('id', 'title', 'summary', 'segments')},
                        'groups': [group['group'] for group in row['groups']]}
                       for row in data['analysis']['issues']],
            'questions': [{k: row[k] for k in ('issue_id', 'question')} for row in plan['qa']],
            'outreach': [{'group': row['group'], 'where': row['suggestion'].get('where', ''),
                          'method': row['suggestion'].get('method', '')} for row in plan['outreach']],
            'missing': data.get('hearing', {}).get('summary', {}).get('missing', []),
            'models': data['meta'].get('models', {}),
            'archive': {'path': source_path, 'sha256': hashlib.sha256(raw).hexdigest(),
                        'created_at': data['meta']['created_at'],
                        'url': 'https://github.com/hosungseo/policy-preview-engine/blob/main/' + source_path,
                        'changes': '기존 실행의 쟁점·질문·접점과 실제 저장된 Jev 확률 평균 분포를 발췌했습니다. 개별 찬반이 없는 집단 분포와 측정하지 않은 흔들림은 복원하지 않습니다.'},
        }
        (destination / source.name).write_text(json.dumps(excerpt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
