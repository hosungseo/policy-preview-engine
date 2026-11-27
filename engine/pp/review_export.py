"""Explicit file export: retain the complete public result, never overwrite files."""
import json
from pathlib import Path

from . import service


def save(state: dict, path: str | None = None) -> dict:
    if state.get('status') != 'completed':
        raise service.RequestError('완료된 결과만 저장할 수 있습니다. get_run으로 진행 상태를 확인하세요.')
    try:
        home = Path.home()
        if path is None:
            target = home / 'Documents' / '백번미리묻다' / f"{state['id']}.json"
        else:
            if not isinstance(path, str) or not path.strip():
                raise ValueError('empty path')
            target = Path(path).expanduser()
            if not target.is_absolute():
                target = home / target
        target = target.absolute()
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation rejects existing files and symlinks without touching their contents.
        with target.open('x', encoding='utf-8') as stream:
            json.dump(state['result'], stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    except (OSError, ValueError, TypeError):
        raise service.RequestError('결과 파일을 저장하지 못했습니다.', 'save_failed') from None
    return {'id': state['id'], 'saved': True, 'path': str(target.absolute()),
            'format': state['result']['schema'], 'notice': state['result'].get('notice'),
            'message': '고지·출처·영수증·실행 기록을 포함한 전체 결과를 저장했습니다.'}
