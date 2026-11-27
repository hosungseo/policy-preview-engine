"""Offline stage-0 contracts. No assignment or activation is performed here."""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

DATA = Path(__file__).parent / 'data' / 'persona-accuracy'


def canonical(value) -> bytes:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return (unicodedata.normalize('NFC', text) + '\n').encode('utf-8')


def read_json(path: Path):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('duplicate_key')
            out[key] = value
        return out
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite')))


def _validate(value, rule):
    for union in ('oneOf', 'anyOf'):
        if union in rule:
            count = 0
            for child in rule[union]:
                try:
                    _validate(value, child)
                    count += 1
                except ValueError:
                    pass
            if not count or (union == 'oneOf' and count != 1):
                raise ValueError('schema_invalid')
            return
    if 'const' in rule and value != rule['const'] or 'enum' in rule and value not in rule['enum']:
        raise ValueError('schema_invalid')
    typ = rule.get('type')
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'number': (int, float), 'boolean': bool, 'null': type(None)}
    if typ and (not isinstance(value, types[typ]) or typ in ('integer', 'number') and isinstance(value, bool)):
        raise ValueError('schema_invalid')
    if typ == 'object':
        if set(rule['required']) - value.keys() or rule.get('additionalProperties') is False and value.keys() - rule['properties'].keys():
            raise ValueError('schema_invalid')
        for key, val in value.items():
            _validate(val, rule['properties'][key])
    if typ == 'array':
        if len(value) < rule.get('minItems', 0) or len(value) > rule.get('maxItems', math.inf):
            raise ValueError('schema_invalid')
        for val in value:
            _validate(val, rule['items'])
    if typ == 'string' and (len(value) < rule.get('minLength', 0) or 'pattern' in rule and not re.search(rule['pattern'], value)):
        raise ValueError('schema_invalid')
    if typ in ('integer', 'number') and (not math.isfinite(value) or value < rule.get('minimum', -math.inf) or value > rule.get('maximum', math.inf)):
        raise ValueError('schema_invalid')


def validate(document: dict, kind: str) -> dict:
    _validate(document, read_json(DATA / 'schema-v2.json'))
    if document['kind'] != kind:
        raise ValueError('schema_invalid')
    return document['payload']


def verified_sources(document: dict) -> dict:
    items = validate(document, 'sources')['items']
    if len({s['id'] for s in items}) != len(items):
        raise ValueError('duplicate_source')
    return {s['id']: s for s in items if s['status'] == 'verified'}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unavailable_accuracy() -> dict:
    return {'schema_version': 2, 'kind': 'api_accuracy', 'payload': {
        'state': 'not_applied', 'manifest_hash': None, 'model_revision': None,
        'applied_rate': None, 'scope': None, 'baseline': None,
        'reasons': ['baseline_unavailable', 'model_unverified', 'enrichment_not_applied']}}
