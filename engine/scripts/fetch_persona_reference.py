"""Import permitted local adult aggregates; never automate MDIS downloads."""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse

import httpx
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ppservice.persona_accuracy import canonical, read_json, validate, verified_sources, file_hash


def import_reference(document: dict, sources: dict, year: int) -> dict:
    payload = validate(document, 'reference')
    approved = verified_sources(sources)
    if payload['scope']['year'] != year or payload['scope']['unit'] != 'adult_person':
        raise ValueError('year_or_unit_mismatch')
    seen = set()
    for cell in payload['cells']:
        source = approved.get(cell['source_id'])
        if not source:
            raise ValueError('source_unverified')
        if source['period'] != str(year) or source['unit'] != 'adult_person' or source['population'] != payload['scope']['population']:
            raise ValueError('source_scope_mismatch')
        if cell['id'] in seen or cell['mapping_hash'] != payload['mapping_hash']:
            raise ValueError('reference_mismatch')
        seen.add(cell['id'])
        if sum(cell['probability_units']) != 10**12:
            raise ValueError('invalid_probability_sum')
    return document


def fetch_population(source: dict, year: int, fixture: list | None = None) -> list:
    """Require a reviewed table identifier before any network access."""
    if (source.get('status') != 'verified' or not source.get('evidence')
            or not re.fullmatch(r'DT_[A-Za-z0-9_]+', source.get('table_or_file', ''))):
        raise ValueError('population_table_unverified')
    if source['period'] != str(year) or source['unit'] != 'adult_person':
        raise ValueError('year_or_unit_mismatch')
    if fixture is None:
        from fetch_kosis_housing import _key
        source_url = urllib.parse.urlparse(source['url'])
        source_query = urllib.parse.parse_qs(source_url.query)
        org = source_query.get('orgId', [''])[0]
        if source_url.hostname != 'kosis.kr' or not org.isdigit() or source_query.get('tblId') != [source['table_or_file']]:
            raise ValueError('population_table_unverified')
        national_five_year = source['table_or_file'] == 'DT_1B04005N'
        query = urllib.parse.urlencode({'method': 'getList', 'apiKey': _key(), 'orgId': org,
            'tblId': source['table_or_file'], 'itmId': 'ALL', 'objL1': '00' if national_five_year else 'ALL', 'objL2': 'ALL',
            'objL3': '' if national_five_year else 'ALL', 'format': 'json', 'jsonVD': 'Y', 'prdSe': 'M',
            'startPrdDe': f'{year}12', 'endPrdDe': f'{year}12'})
        try:
            response = httpx.get('https://kosis.kr/openapi/Param/statisticsParameterData.do?' + query, timeout=60)
            response.raise_for_status()
            fixture = response.json()
        except Exception:
            raise ValueError('population_fetch_failed') from None
    if not isinstance(fixture, list) or not fixture or any(str(r.get('PRD_DE')) != f'{year}12' for r in fixture):
        raise ValueError('year_mismatch')
    return fixture


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--local-aggregate', type=Path)
    mode.add_argument('--population-source')
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--mapping', type=Path)
    parser.add_argument('--year', type=int, default=2024)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.population_source:
        sources = verified_sources(read_json(args.sources))
        source = sources.get(args.population_source)
        if source is None:
            raise ValueError('population_table_unverified')
        rows = fetch_population(source, args.year, read_json(args.fixture) if args.fixture else None)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(canonical(rows))
        return 0
    if not args.mapping:
        parser.error('--mapping is required for local aggregates')
    document = import_reference(read_json(args.local_aggregate), read_json(args.sources), args.year)
    mapping = validate(read_json(args.mapping), 'mapping')
    if not mapping['rows'] or not mapping['codebook_hashes'] or mapping['missing_codes']:
        raise ValueError('mapping_unverified')
    if document['payload']['mapping_hash'] != file_hash(args.mapping):
        raise ValueError('hash_mismatch')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(canonical(document))
    return 0


if __name__ == '__main__':
    sys.exit(main())
