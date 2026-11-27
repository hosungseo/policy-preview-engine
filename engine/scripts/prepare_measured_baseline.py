"""Freeze the reviewed December 2024 age standard; no opinion responses are used."""
import argparse
import copy
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ppservice.persona_accuracy import canonical, read_json, file_hash, verified_sources
from build_baseline import age_bounds
from fetch_baseline_kosis import AGE_ROWS


def prepare(directory):
    if (directory / 'answers.jsonl').exists() or (directory / 'run-manifest.json').exists():
        raise ValueError('responses_exist_inputs_are_frozen')
    official = read_json(directory / 'official-2024.json')
    raw = read_json(directory / 'social-raw.json')
    population = read_json(directory / 'population-202412-raw.json')
    assert all(r['PRD_DE'] == '202412' and r['UNIT_NM'] == '명' and r['C1_NM'] == '전국' for r in population)
    def weights(bands, sex='총인구수'):
        counts = {}
        for band in bands:
            lo, hi = age_bounds(band)
            counts[band] = sum(int(r['DT']) for r in population if r['ITM_NM'] == sex and r['C2_NM'] != '계'
                               and lo <= int(re.match(r'\d+', r['C2_NM'])[0]) <= (hi or 1000))
        assert all(counts.values())
        adults = sum(int(r['DT']) for r in population if r['ITM_NM'] == sex and r['C2_NM'] != '계'
                     and int(re.match(r'\d+', r['C2_NM'])[0]) >= 20)
        if sum(counts.values()) != adults:
            raise ValueError('age_bands_do_not_partition_all_adults')
        return {b: v / sum(counts.values()) for b, v in counts.items()}
    frozen = dict(year=2024, unit='adult_person', min_age=20, by_question={}, definitions={}, population_sha256=file_hash(directory/'population-202412-raw.json'), by_sex={})
    sources = []
    now = datetime.now(timezone.utc).isoformat()
    evidence_files = ['social-raw.json', 'population-202412-raw.json', 'source-review.md']
    evidence = [dict(path=str(directory/f), sha256=file_hash(directory/f)) for f in evidence_files]
    for item in official['items']:
        if '60대' in item['age_bands'] and '60세 이상' in item['age_bands']:
            item['age_bands'].remove('60세 이상')
        definition = item['definition']
        definition.update(survey_date='2024-05-15/2024-05-30', survey_mode='면접 및 인터넷 조사', fixed_weights='2024-12 주민등록인구 연령 표준; 조사 모집단 자체의 가중치가 아님')
        item['source_definition'] = copy.deepcopy(definition)
        context = dict(definition, options=item['options'])
        frozen['definitions'][item['id']] = context
        frozen['by_question'][item['id']] = weights(item['age_bands'])
        item['sex_tables'] = {}
        for sex in ['남자','여자']:
            groups = {}
            for r in raw[item['tbl']]:
                parts = r.get('C2_NM','').split('*')
                if r['C1_NM'] == '전국' and len(parts)==2 and parts[1]==sex and parts[0] in AGE_ROWS and r['ITM_NM'] in item['options']:
                    groups.setdefault(AGE_ROWS[parts[0]],{})[r['ITM_NM']] = float(r['DT'])
            if not groups: continue
            if '60대' in groups: groups.pop('60세 이상',None)
            bands = sorted(groups,key=lambda x:age_bounds(x)[0])
            w = weights(bands, sex+'인구수')
            table = {k:copy.deepcopy(item[k]) for k in ['id','period','options','definition']}
            table.update(groups=groups,age_bands=bands,weights=w,weight_definition=context,
                         group_definitions={b:dict(definition,min_age=age_bounds(b)[0],max_age=age_bounds(b)[1],options=item['options'],eligible=True) for b in bands})
            item['sex_tables'][sex]=table
            frozen['by_sex'].setdefault(item['id'],{})[sex]=w
        definition['sex_eligible'] = len(item['sex_tables'])==2
        item['excluded_reasons'] = [] if definition['sex_eligible'] else ['sex_adult_cross_table_missing']
        rows=raw[item['tbl']]
        sources.append(dict(id=item['id'],agency='통계청 (2024 조사 작성기관)',survey='2024 사회조사',table_or_file=item['tbl'],url='https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId='+item['tbl'],period='2024',downloaded_at=now,unit='adult_person',population=definition['population'],category_codes=item['options'],weights='공표 연령셀의 비율을 2024-12 주민등록인구로 연령 표준화; 공표 전국 추정치와 다름',revision=','.join(sorted({r.get('LST_CHN_DE','미제공') for r in rows})),terms='KOSIS 통계정보 활용약관: 출처표기 조건 재사용/재배포. source-review.md 참조',raw_sha256=file_hash(directory/'social-raw.json'),evidence=evidence,status='verified'))
    sources.append(dict(id='population-2024',agency='행정안전부; KOSIS 제공기관 코드 101',survey='주민등록인구현황',table_or_file='DT_1B04005N',url='https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1B04005N',period='2024',downloaded_at=now,unit='adult_person',population='2024-12-31 주민등록 대한민국 국민 20세 이상; 외국인 제외; 거주자·거주불명자·재외국민',category_codes=sorted({r['C2_NM'] for r in population}),weights='5세별 명 단위 원자료 중 20세 이상을 합산; 남녀 각각 및 전체 고정',revision=','.join(sorted({r['LST_CHN_DE'] for r in population})),terms='KOSIS 출처표기 조건 재사용/재배포',raw_sha256=file_hash(directory/'population-202412-raw.json'),evidence=evidence,status='verified'))
    envelope=dict(schema_version=2,kind='sources',payload=dict(items=sources));verified_sources(envelope)
    for name, value in [('official-2024.json',official),('frozen-weights.json',frozen),('sources-reviewed.json',envelope)]:
        (directory/name).write_bytes(canonical(value))
    print('Frozen weights and reviewed sources:',len(sources))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);prepare(ap.parse_args().directory)
