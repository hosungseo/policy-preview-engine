"""Offline first-screen, plan consistency, observed progress and loss-free export checks."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from threading import Event

import pytest

from pp import mcp, run_progress, service, summary_card
from pp.jobs import Jobs
from test_public_interfaces import POLICY, SECRET, assert_result, fake_models, wait_job


def test_mcp_summary_full_and_saved_result(fake_models, tmp_path):
    jobs = Jobs()
    server = mcp.create_server(jobs)
    def call(name, **args):
        result = asyncio.run(server.call_tool(name, args))
        assert not result.isError, result
        return result
    try:
        quote = call('estimate', policy_text=POLICY, sample=12, seed=7).structuredContent
        assert quote['recommended_sample']['sample'] == 200
        started = call('start_run', plan_id=quote['plan_id']).structuredContent
        full = wait_job(jobs.get, started['id'])
        assert full['status'] == 'completed'
        assert full['result']['conditions']['seed'] == 7
        summary = call('get_run', id=started['id'])
        text = summary.content[0].text
        assert len(text) <= 3000
        for label in ('찾아갈 곳', '먼저 물을 질문', '명단 밖 사람', '재시작', '이 결과를 저장해 줘', '전체 결과를 보여 줘', 'NVIDIA'):
            assert label in text
        assert 'result' not in summary.structuredContent
        assert 'selection' not in json.dumps(summary.structuredContent)
        assert_result(call('get_run', id=started['id'], view='full').structuredContent['result'])
        path = tmp_path / 'saved.json'
        saved = call('save_review', id=started['id'], path=str(path)).structuredContent
        assert saved['saved']
        assert json.loads(path.read_text()) == full['result']
        again = asyncio.run(server.call_tool('save_review', {'id': started['id'], 'path': str(path)}))
        assert again.isError and json.loads(path.read_text()) == full['result']
        assert SECRET not in path.read_text() + json.dumps(jobs._plans.items)
    finally:
        jobs.close()


@pytest.mark.parametrize('override', [dict(policy_text=POLICY + '\n접수 안내를 제공한다.'),
    dict(sample=2), dict(seed=5), dict(i_confirm_public=True), dict(limits={'max_calls': 1})])
def test_plan_rejects_changed_conditions_before_execution(fake_models, monkeypatch, override):
    jobs = Jobs()
    try:
        quote = jobs.estimate(POLICY, sample=12)
        monkeypatch.setattr(jobs._pool, 'submit', lambda *a, **k: pytest.fail('must not execute'))
        with pytest.raises(service.RequestError, match='estimate'):
            jobs.start_planned(plan_id=quote['plan_id'], **override)
        assert not jobs._runs
    finally:
        jobs.close()


@pytest.mark.parametrize('name,value', [('PP_LLM_PROVIDER', 'changed'), ('PP_JEV_MODEL', 'changed'),
    ('PP_PERSONA_DB', 'changed'), ('TYPESAFE_API_KEY', 'fake-new-key')])
def test_plan_rejects_environment_drift(fake_models, monkeypatch, name, value):
    jobs = Jobs()
    try:
        quote = jobs.estimate(POLICY, sample=12)
        monkeypatch.setenv(name, value)
        with pytest.raises(service.RequestError, match='estimate'):
            jobs.start_planned(plan_id=quote['plan_id'])
        assert not jobs._runs
    finally:
        jobs.close()


def test_plan_concurrent_retry_starts_once(fake_models):
    jobs = Jobs()
    try:
        quote = jobs.estimate(POLICY, sample=12)
        with ThreadPoolExecutor(max_workers=4) as pool:
            runs = list(pool.map(lambda _: jobs.start_planned(plan_id=quote['plan_id']), range(4)))
        assert len({r['id'] for r in runs}) == 1
        assert len(jobs._runs) == 1
        assert wait_job(jobs.get, runs[0]['id'])['status'] == 'completed'
    finally:
        jobs.close()


def test_progress_measures_stage_and_handles_queued_jobs(fake_models, monkeypatch, tmp_path):
    entered, release = Event(), Event()
    def slow(*args, **kwargs):
        run_progress.report('questions')
        entered.set()
        assert release.wait(10)
        return {'schema': 'pp.run/2'}
    monkeypatch.setattr(service, 'run_policy', slow)
    jobs = Jobs()
    try:
        first = jobs.start(POLICY, sample=12)
        assert entered.wait(5)
        second = jobs.start(POLICY, sample=12)
        running = jobs.get(first['id'], view='summary')
        assert running['stage'] == 'questions'
        assert running['progress']['completed_stages'] == 2
        assert running['progress']['total_stages'] == 4
        assert running['estimated_remaining_seconds']['high'] > 0
        assert running['poll_after_ms'] > 0
        assert jobs.get(second['id'])['stage'] == 'queued'
        with pytest.raises(service.RequestError, match='완료'):
            jobs.save_review(first['id'], str(tmp_path / 'early.json'))
        release.set()
        complete = wait_job(jobs.get, first['id'])
        assert complete['progress']['completed_stages'] == 4
        assert complete['estimated_remaining_seconds'] == {'low': 0, 'high': 0}
    finally:
        release.set()
        jobs.close()


def test_summary_large_prose_is_bounded_without_mutating_full_result(fake_models):
    result = service.run_policy(POLICY, sample=12)
    result['who_to_ask'] *= 20
    for row in result['who_to_ask']:
        row['questions'] = ['질문 문장입니다. ' * 2000] * 10
    original = deepcopy(result)
    card = summary_card.build(result, 'run-test')
    assert len(card['text']) <= 3000
    assert card['truncated']
    assert '명단 밖 사람' in card['text']
    assert '이 결과를 저장해 줘' in card['text']
    assert result == original


def test_restart_and_invalid_view_are_actionable(fake_models):
    jobs = Jobs()
    try:
        with pytest.raises(KeyError, match='재시작'):
            jobs.get('missing')
        with pytest.raises(service.RequestError, match='estimate'):
            jobs.start_planned(plan_id='lost')
        with pytest.raises(service.RequestError, match='view'):
            jobs.get('missing', view='invalid')
    finally:
        jobs.close()


def test_summary_keeps_verbatim_policy_numbers_in_long_clause():
    clause = '교통비의 30%를 지원한다.\n' + '신청 절차를 안내한다. ' * 30
    result = {'clauses': [{'id': 's1', 'text': clause, 'issues': ['i1']}],
              'issues': [{'id': 'i1', 'summary': '절차를 확인하세요.'}],
              'who_to_ask': [{'issue_id': 'i1', 'groups': ['이용자'], 'questions': ['신청할 때 어디에서 막히나요?']}]}
    card = summary_card.build(result, 'run-test')
    assert card['cards'][0]['source_quote'] == clause[:160]
    assert '30%' in card['text']


def test_export_rejects_symlink_without_modifying_target(tmp_path):
    from pp.review_export import save
    target = tmp_path / 'existing.json'
    target.write_text('keep me')
    link = tmp_path / 'link.json'
    link.symlink_to(target)
    with pytest.raises(service.RequestError, match='덮어쓰지'):
        save({'id': 'test', 'status': 'completed', 'result': {'schema': 'pp.run/2'}}, str(link))
    assert target.read_text() == 'keep me'
