"""Regressions from the first-use report: genuine examples, honest trials and safe saves."""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from pp import archived_examples, mcp_copy, mcp_setup, public_rules, review_export, service, summary_card
from pp.jobs import Jobs
from pp.mcp import create_server
from test_mcp_onboarding import offline

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('key', archived_examples.EXAMPLES)
def test_archived_examples_retain_real_source_fields_offline(offline, monkeypatch, key):
    monkeypatch.setattr(service, 'run_policy', lambda *a, **k: pytest.fail('archive must not execute models'))
    source = ROOT / 'web/public/runs' / f'{key}.json'
    original = json.loads(source.read_text())
    state = mcp_setup.try_example(key)
    result = state['result']
    assert result['mode'] == 'archived' and state['cost_usd'] == 0
    assert result['archive']['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result['archive']['created_at'] == original['meta']['created_at']
    assert result['policy_source'] == original['source']
    assert result['questions'] == [{k: q[k] for k in ('issue_id', 'question')} for q in original['plan']['qa']]
    card = summary_card.build(result, 'archive')
    assert card['cards'] and all(c['questions'] for c in card['cards'])
    assert any(c['contact_hints'] for c in card['cards'])
    assert all(c['source_quote'] in original['policy_text'] for c in card['cards'])
    assert {'만 19세 미만', '외국인 주민(귀화하지 않은 결혼이민자 포함)'} <= {m['group'] for m in card['missing_perspectives']}
    assert '보관 결과' in card['text'] and 'NVIDIA' in card['text'] and 'MOCK' not in card['text']
    assert '보관 출처:' in card['text']
    assert {row['title'] for row in state['available_examples']} == {mcp_copy.EXAMPLES[k].title for k in archived_examples.EXAMPLES}


def test_unarchived_example_does_not_invent_a_result(offline):
    with pytest.raises(mcp_setup.SetupError, match='보관 결과는 없습니다'):
        mcp_setup.try_example('elderly-welfare-rule')


def test_own_policy_trial_is_clear_on_first_line(offline):
    jobs = Jobs()
    try:
        quote = jobs.estimate('노인복지주택의 계속 거주를 지원한다.', sample=12)
        assert quote['mode'] == 'mock' and quote['requires_consent'] is False
        assert quote['estimated_seconds'] == {'low': 1, 'high': 3}
        assert 'NVIDIA' not in json.dumps(quote, ensure_ascii=False)
        state = jobs.start_planned(plan_id=quote['plan_id'])
        assert state['trial_notice'] == mcp_setup.TRIAL_NOTICE and state['mode'] == 'mock'
        jobs.close()
        summary = jobs.get(state['id'], view='summary')['summary']
        assert summary['text'].splitlines()[0] == summary_card.numbers_copy.BANNER
        assert summary['cards'] and summary['missing_perspectives']
        assert summary_card.numbers_copy.TAILS['mock'] in summary['text']
    finally:
        jobs.close()


def test_schema_and_conditions_errors_are_actionable_korean(offline):
    jobs = Jobs()
    try:
        server = create_server(jobs)
        tools = asyncio.run(server.list_tools())
        for tool in tools:
            if tool.name in {'estimate', 'start_run'}:
                condition = tool.inputSchema['$defs']['Condition']['properties']
                assert {'name', 'age_min', 'age_max', 'provinces', 'eligibility'} <= condition.keys()
                assert condition['eligibility']['type'] == 'array'
                assert condition['eligibility']['items']['type'] == 'string'
        saved = next(t for t in tools if t.name == 'save_review')
        assert saved.inputSchema['required'] == ['id']
        invalid = asyncio.run(server.call_tool('estimate', {'policy_text': '교통비를 지원한다.', 'conditions': {'eligibility': '비밀값-출력금지'}}))
        assert invalid.isError
        assert '문자열 목록' in invalid.content[0].text and 'eligibility' in invalid.content[0].text
        assert '비밀값-출력금지' not in invalid.model_dump_json()
    finally:
        jobs.close()


def test_save_uses_home_from_root_and_gives_easy_failure(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.chdir('/')
    state = {'id': 'test-run', 'status': 'completed', 'result': archived_examples.load('subway-free-ride')}
    default = review_export.save(state)
    assert Path(default['path']) == tmp_path / 'Documents/백번미리묻다/test-run.json'
    relative = review_export.save(state, 'relative/result.json')
    assert Path(relative['path']) == tmp_path / 'relative/result.json'
    assert json.loads(Path(relative['path']).read_text()) == state['result']
    assert json.loads(Path(default['path']).read_text()) == state['result']
    with pytest.raises(service.RequestError) as error:
        review_export.save(state)
    payload = mcp_setup.error_payload(error.value)
    assert payload['code'] == 'save_failed'
    assert '~/Desktop/result-new.json' in payload['next_action']
    assert public_rules.NOTICE == json.loads(Path(default['path']).read_text())['notice']


def test_non_result_tools_do_not_repeat_reaction_notice(offline, tmp_path):
    jobs = Jobs()
    try:
        server = create_server(jobs)
        for name, args, first_line in [
            ('check_setup', {}, '설정 확인이며 분석 결과가 아닙니다.'),
            ('estimate', {'policy_text': '교통비를 지원한다.'}, '비용·시간 견적이며 분석 결과가 아닙니다.'),
        ]:
            result = asyncio.run(server.call_tool(name, args))
            assert not result.isError and result.content[0].text.splitlines()[0] == first_line
            assert public_rules.NOTICE not in result.content[0].text
        trial = jobs.try_example()
        saved = asyncio.run(server.call_tool('save_review', {'id': trial['id'], 'path': str(tmp_path / 'saved.json')}))
        assert not saved.isError
        assert public_rules.NOTICE not in saved.content[0].text
    finally:
        jobs.close()
