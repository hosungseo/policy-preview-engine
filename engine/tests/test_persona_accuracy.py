"""Fixed offline examples for comparison contracts and honest result displays."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from ppservice.persona_accuracy import DATA, canonical, read_json, validate, verified_sources
from ppservice.survey import aggregate


def script(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = script('build_baseline')
fetch = script('fetch_baseline_kosis')
reference = script('fetch_persona_reference')


@pytest.fixture
def comparison():
    item = {'id': 'fixed', 'period': '2024', 'options': ['찬성', '반대'],
            'definition': {'year': 2024, 'unit': 'adult_person', 'min_age': 20, 'max_age': None, 'population': '20세 이상 개인'},
            'age_bands': ['20–29세', '60세 이상'],
            'groups': {'20–29세': {'찬성': 80, '반대': 20}, '60세 이상': {'찬성': 20, '반대': 80}}}
    item['group_definitions'] = {b: {**item['definition'], 'min_age': build.age_bounds(b)[0],
        'max_age': build.age_bounds(b)[1], 'eligible': True, 'options': item['options']} for b in item['age_bands']}
    people = [{'uuid': str(age), 'age': age} for age in (19, 20, 60, 70)]
    answers = {'19': [0, 1], '20': [1, 0], '60': [0, 1], '70': [0, 1]}
    return item, people, answers, {'20–29세': .5, '60세 이상': .5}


def test_fixed_weights_age_boundary_and_merging(comparison):
    item, people, answers, weights = comparison
    assert build.band_of(people[0], item['age_bands']) is None
    assert build.band_of(people[1], item['age_bands']) == '20–29세'
    result = build.compare(item, people, answers, weights)
    assert result['mae_overall_pp'] == pytest.approx(0)
    assert result['bands']['60세 이상']['n'] == 2
    assert result['bands']['20–29세']['mae_pp'] == pytest.approx(20)
    assert result['mae_sex_pp'] is None
    del answers['70']
    assert build.compare(item, people, answers, weights)['mae_overall_pp'] == pytest.approx(0)
    del answers['60']
    assert build.compare(item, people, answers, weights)['mae_overall_pp'] is None


def test_missing_weights_and_invalid_scope(comparison):
    item, people, answers, weights = comparison
    assert build.compare(item, people, answers)['mae_overall_pp'] is None
    for field, value in [('unit', 'household'), ('min_age', 13), ('year', 2025)]:
        bad = copy.deepcopy(item)
        bad['definition'][field] = value
        with pytest.raises(ValueError):
            build.compare(bad, people, answers, weights)
    with pytest.raises(ValueError):
        build.compare(item, people, answers, {'20–29세': 1})
    answers['20'] = [float('nan'), 1]
    with pytest.raises(ValueError):
        build.compare(item, people, answers, weights)


def test_collection_year_and_label():
    assert fetch.AGE_ROWS['20∼29세'] == '20–29세'
    fetch.validate_year([{'PRD_DE': '2024'}], 2024)
    for rows in ([], [{'PRD_DE': '2025'}], [{'PRD_DE': '2024'}, {'PRD_DE': '2022'}]):
        with pytest.raises(ValueError, match='year_mismatch'):
            fetch.validate_year(rows, 2024)


def test_collector_fixture_cli(tmp_path, monkeypatch):
    rows = {}
    for item in fetch.ITEMS:
        options = item['options'] or fetch.SAFETY_ORDER
        rows[item['tbl']] = [{'PRD_DE': '2024', 'C1_NM': '전국', 'C2_NM': '20∼29세',
                              'ITM_NM': o, 'DT': str(100 / len(options))} for o in options]
    fixture, output = tmp_path / 'fixture.json', tmp_path / 'official.json'
    fixture.write_text(json.dumps(rows))
    monkeypatch.setattr(fetch.httpx, 'get', lambda *a, **k: pytest.fail('network forbidden'))
    monkeypatch.setattr('sys.argv', ['fetch', '--fixture', str(fixture), '--out', str(output)])
    assert fetch.main() == 0
    data = json.loads(output.read_text())
    assert len(data['items']) == 5
    assert all(i['age_bands'] == ['20–29세'] and not i['definition']['sex_eligible'] for i in data['items'])


def test_contracts_unverified_and_benchmark():
    for filename, kind in [('sources.json', 'sources'), ('mapping-v1.json', 'mapping'),
                           ('reference-2024.json', 'reference'), ('benchmark-v2.json', 'benchmark')]:
        validate(read_json(DATA / filename), kind)
    assert verified_sources(read_json(DATA / 'sources.json')) == {}
    questions = read_json(DATA / 'benchmark-v2.json')['payload']['questions']
    assert len(questions) == 5
    assert all(q['split'] == 'development' and q['excluded_reason'] and not q['official'] for q in questions)


def test_reference_rejects_household_and_unverified():
    document = read_json(DATA / 'reference-2024.json')
    sources = read_json(DATA / 'sources.json')
    bad = copy.deepcopy(document)
    bad['payload']['scope']['unit'] = 'household'
    with pytest.raises(ValueError):
        reference.import_reference(bad, sources, 2024)
    with pytest.raises(ValueError):
        reference.import_reference(document, sources, 2025)
    document['payload']['cells'] = [dict(id='a', source_id='marriage', mapping_hash=document['payload']['mapping_hash'],
        province='서울', age='20–29세', sex='여자', family_type='1인', housing_type='아파트',
        fallback_level=0, n=100, ess=100, probability_units=[10**12, 0, 0, 0])]
    with pytest.raises(ValueError, match='source_unverified'):
        reference.import_reference(document, sources, 2024)


def test_canonical_and_schema_reject_invalid(tmp_path):
    assert canonical({'b': 1, 'a': '가'}) == '{"a":"가","b":1}\n'.encode()
    with pytest.raises(ValueError):
        canonical({'x': float('nan')})
    p = tmp_path / 'duplicate.json'
    p.write_text('{"x":1,"x":2}')
    with pytest.raises(ValueError, match='duplicate_key'):
        read_json(p)
    accuracy = aggregate.unavailable_accuracy()
    validate(accuracy, 'api_accuracy')
    accuracy['payload']['applied_rate'] = 1.1
    with pytest.raises(ValueError):
        validate(accuracy, 'api_accuracy')


def test_legacy_baseline_never_attached_to_new_result(tmp_path):
    old = {'summary': {'mae_pp': 6.5, 'worst_option_gap_pp': 33}}
    path = tmp_path / 'baseline.json'
    path.write_text(json.dumps(old))
    assert aggregate.load_baseline(path) is None
    assert json.loads(path.read_text()) == old
    people = [{'uuid': 'a', 'age_band': '30대', 'sex': '여자', 'capital': True}]
    result = aggregate.summarize({'options': ['찬성', '잘 모르겠다']}, people,
                                 {'main': {'a': [.8, .2]}}, [], old['summary'])
    assert result['baseline'] is None
    assert result['accuracy']['payload']['state'] == 'not_applied'
    assert '±' not in result['summary_text']
    assert '실측 비교 검증 전이며 실제 조사로 확인이 필요합니다.' in result['summary_text']
    assert '+6' not in str(result['cautions'])


def test_population_collector_blocks_unknown_table_without_network(monkeypatch):
    monkeypatch.setattr(reference.httpx, 'get', lambda *a, **k: pytest.fail('network forbidden'))
    with pytest.raises(ValueError, match='population_table_unverified'):
        reference.fetch_population({'status': 'unverified'}, 2024)
    source = {'status': 'verified', 'evidence': [{'path': 'fixture'}], 'table_or_file': 'DT_FIXTURE',
              'period': '2024', 'unit': 'adult_person'}
    assert reference.fetch_population(source, 2024, [{'PRD_DE': '202412', 'DT': '100'}])
    with pytest.raises(ValueError, match='year_mismatch'):
        reference.fetch_population(source, 2024, [{'PRD_DE': '202501'}])


def test_offline_builder_excludes_unverified_and_preserves_inputs(tmp_path, monkeypatch, comparison):
    item, people, answers, weights = comparison
    inputs = {'official': {'items': [item]},
              'responses': {'people': people, 'answers': {'fixed': answers}, 'model_version': 'fixture-only'},
              'weights': {'year': 2024, 'unit': 'adult_person', 'min_age': 20, 'by_question': {'fixed': weights}},
              'sources': read_json(DATA / 'sources.json')}
    argv = ['build']
    for name, value in inputs.items():
        path = tmp_path / (name + '.json')
        path.write_bytes(canonical(value))
        argv.extend(['--' + name, str(path)])
    output = tmp_path / 'diagnostic.json'
    monkeypatch.setattr('sys.argv', argv + ['--out', str(output)])
    assert build.main() == 0
    result = read_json(output)
    assert result['mae_pp'] is None
    assert result['items'][0]['excluded_reasons'] == ['source_unverified']
    assert result['input_hashes']['responses']
    for name, value in inputs.items():
        assert read_json(tmp_path / (name + '.json')) == value

@pytest.mark.parametrize('field,value', [('year', 2025), ('unit', 'household'), ('population', 'other'),
    ('min_age', 13), ('max_age', 28), ('eligible', False), ('options', ['반대', '찬성'])])
def test_cell_scope_excluded(comparison, field, value):
    item, people, answers, weights = comparison
    item['group_definitions']['20–29세'][field] = value
    result = build.compare(item, people, answers, weights)
    assert result['mae_overall_pp'] is None
    assert result['bands']['20–29세']['mae_pp'] is None
    assert result['bands']['20–29세']['reasons']


def test_context_scope_and_options(comparison):
    item, people, answers, weights = comparison
    valid = {**item['definition'], 'options': item['options']}
    for name in ('source', 'responses', 'weights'):
        for field, value in [('population', 'other'), ('unit', 'household'), ('min_age', 13),
                             ('max_age', 99), ('year', 2025), ('options', ['반대', '찬성'])]:
            result = build.compare(item, people, answers, weights, contexts={name: {**valid, field: value}})
            assert result['mae_overall_pp'] is None
            assert any(name in r for r in result['excluded_reasons'])


@pytest.mark.parametrize('bands', [['60세 이상', '70세 이상'], ['60세 이상', '60대'], ['20–39세', '30대']])
def test_all_overlaps_rejected(comparison, bands):
    item, people, answers, weights = comparison
    item['age_bands'] = bands
    with pytest.raises(ValueError, match='overlapping'):
        build.compare(item, people, answers, weights)


def test_asymmetric_frozen_weights(comparison):
    item, people, answers, _ = comparison
    weights = {'20–29세': .8, '60세 이상': .2}
    answers['70'] = [.5, .5]
    before = build.compare(item, people, answers, weights)
    del answers['70']
    after = build.compare(item, people, answers, weights)
    assert before['official_overall'] == pytest.approx([.68, .32])
    assert after['official_overall'] == pytest.approx([.68, .32])
    assert before['synthetic_overall'] == pytest.approx([.85, .15])
    assert after['synthetic_overall'] == pytest.approx([.8, .2])


@pytest.mark.parametrize('extra,valid', [(0, True), (.1, True), (.099, True), (.101, False), (.15, False)])
def test_official_normalization(comparison, extra, valid):
    item, people, answers, _ = comparison
    item['groups']['20–29세'] = {'찬성': 50, '반대': 50 + extra}
    result = build.compare(item, people, answers, {'20–29세': 1, '60세 이상': 0})
    if valid:
        assert result['official_overall'] == pytest.approx([50 / (100 + extra), (50 + extra) / (100 + extra)])
        assert result['mae_overall_pp'] == pytest.approx(100 * (1 - 50 / (100 + extra)))
        assert result['transformations'][0]['original_sum'] == pytest.approx(1 + extra / 100)
    else:
        assert result['mae_overall_pp'] is None


def test_zero_weight_missing_cell(comparison):
    item, people, answers, _ = comparison
    result = build.compare(item, people, {'20': answers['20']}, {'20–29세': 1, '60세 이상': 0})
    assert result['mae_overall_pp'] == pytest.approx(20)
    assert result['bands']['60세 이상']['mae_pp'] is None


def test_sex_adult_tables(comparison):
    item, people, answers, weights = comparison
    people = [{'uuid': f'{sex}{age}', 'age': age, 'sex': sex} for sex in ('남자', '여자') for age in (20, 60)]
    answers = {p['uuid']: [1, 0] if p['age'] == 20 else [0, 1] for p in people}
    item['sex_tables'] = {s: {**copy.deepcopy(item), 'weights': {'20–29세': .8, '60세 이상': .2},
        'weight_definition': {**item['definition'], 'options': item['options']}} for s in ('남자', '여자')}
    result = build.compare(item, people, answers, weights)
    assert result['mae_sex_pp'] == pytest.approx(12)
    item['sex_tables']['여자']['group_definitions']['20–29세']['min_age'] = 13
    result = build.compare(item, people, answers, weights)
    assert result['mae_sex_pp'] is None
    assert any('여자' in r for r in result['excluded_reasons'])


def test_legacy_historical_label(comparison):
    item, people, answers, _ = comparison
    item.update(title='fixture', question='fixture')
    item['age_bands'][0] = '19–29세'
    item['groups']['19–29세'] = item['groups'].pop('20–29세')
    item['groups'].update({'남자': {'찬성': 50, '반대': 50}, '여자': {'찬성': 50, '반대': 50}})
    for p in people:
        p['sex'] = '남자' if p['age'] < 60 else '여자'
    result = build.compare_legacy(item, people, answers)
    assert result['bands']['19–29세']['n'] == 1
    assert result['official_overall'] == [40, 60]
    assert result['synthetic_overall'] == [33.3, 66.7]
    assert result['mae_overall_pp'] == 6.7


def test_measured_diagnostic_metrics(comparison):
    item, people, answers, weights = comparison
    item['options'][1] = '잘 모르겠다'
    for values in item['groups'].values():
        values['잘 모르겠다'] = values.pop('반대')
    # The fixture shares the options list with each group definition.
    result = build.compare(item, people, answers, weights)
    assert result['mae_band_pp'] == pytest.approx(20)
    assert result['spread_ratio'] == pytest.approx(5/3)
    assert result['unsure_pp'] == pytest.approx(0)
    assert result['age_gaps'][0]['official_pp'] == pytest.approx(60)
    assert result['age_gaps'][0]['synthetic_pp'] == pytest.approx(100)
    assert result['age_gaps'][0]['error_pp'] == pytest.approx(40)
    assert result['age_gaps'][0]['ratio'] == pytest.approx(5/3)
