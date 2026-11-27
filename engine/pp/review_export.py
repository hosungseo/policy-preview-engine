"""Explicit file export: retain the complete public result, never overwrite files."""
import json
from pathlib import Path

from . import service


def save(state: dict, path: str) -> dict:
    if state.get('status') != 'completed':
        raise service.RequestError('완료된 결과만 저장할 수 있습니다. get_run으로 진행 상태를 확인하세요.')
    try:
        target = Path(path).expanduser()
        # Exclusive creation rejects existing files and symlinks without touching their contents.
        with target.open('x', encoding='utf-8') as stream:
            json.dump(state['result'], stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    except (OSError, ValueError, TypeError):
        raise service.RequestError('저장하지 못했습니다. 서버 컴퓨터의 쓰기 가능한 폴더와 새 파일 이름을 지정하세요. 기존 파일은 덮어쓰지 않습니다.') from None
    return {'id': state['id'], 'saved': True, 'path': str(target.absolute()),
            'format': 'pp.run/2', 'notice': state['result'].get('notice'),
            'message': '고지·출처·영수증·실행 기록을 포함한 전체 결과를 저장했습니다.'}
