"""Historical comparison visibility must not imply a model-matched validation."""
import copy
from pathlib import Path

import pytest

from ppservice import historical_baseline as history
from ppservice.persona_accuracy import DATA,canonical,file_hash,read_json,validate
from ppservice.survey import aggregate


@pytest.fixture
def bundle(tmp_path):
    sources=read_json(DATA/'sources.json')
    for s in sources['payload']['items']:
        s.update(status='verified', unit='adult_person', evidence=[dict(path='fixture',sha256='a'*64)])
    population=copy.deepcopy(sources['payload']['items'][0]);population['id']='population-2024'
    sources['payload']['items'].append(population)
    (tmp_path/'sources-reviewed.json').write_bytes(canonical(sources))
    scope=dict(year=2024,unit='adult_person',population='20세 이상 개인',min_age=20,max_age=None)
    items=[dict(id=q,options=['찬성','반대'],**scope,mae_overall_pp=10.,worst_pp=10.,mae_sex_pp=10.,
                eligible=True,sex_eligible=True,n_planned=3000,n_adult_planned=2975,n_adult_answered=2975,
                official_overall=[.6,.4],synthetic_overall=[.5,.5],unsure_signed_pp=None) for q in sorted(history.QUESTIONS)]
    hashes=dict(official='a'*64,weights='b'*64,sources=file_hash(tmp_path/'sources-reviewed.json'))
    for reverse in (False,True):
        comparison=dict(status='diagnostic_complete',model_version='test-model',items=items,mae_pp=10.,worst_pp=10.,
                        input_hashes=dict(hashes,responses=('d' if reverse else 'c')*64,paired_responses=('c' if reverse else 'd')*64))
        (tmp_path/('comparison-2024-reversed.json' if reverse else 'comparison-2024.json')).write_bytes(canonical(comparison))
    run=dict(status='complete',attempts=30000,n=3000,adult_n=2975,seed=2024,failures=0,cost_usd=1.,returned_models=['test-model'],panel_version='test-panel',
             input_hashes={'official-2024.json':hashes['official'],'frozen-weights.json':hashes['weights'],'sources-reviewed.json':hashes['sources']})
    (tmp_path/'measured-run.json').write_bytes(canonical(run))
    path=tmp_path/'historical-baseline-2024.json'
    path.write_bytes(canonical(dict(kind='historical-diagnostic-v1',artifacts={p.name:file_hash(p) for p in tmp_path.glob('*.json')})))
    return path


def test_historical_snapshot_has_distinct_contract(bundle,monkeypatch):
    diagnostic=history.checked_bundle(bundle)
    assert diagnostic['mae_pp']==10
    assert diagnostic['model_identity_verified'] is False
    monkeypatch.setattr(history,'load',lambda:diagnostic)
    people=[dict(uuid='a',sex='남자',age_band='30대',capital=True)]
    result=aggregate.summarize({'options':['찬성','잘 모르겠다']},people,{'main':{'a':[.8,.2]}},[],
                               panel_version='test-panel',model_version='another-model')
    payload=validate(result['accuracy'],'api_accuracy')
    assert payload['baseline'] is None
    assert payload['model_revision'] is None
    assert payload['historical_baseline']['mae_pp']==10
    assert 'historical_model_mismatch' in payload['reasons']
    assert '이 문항의 오차 범위가 아닙니다' in result['summary_text']
    assert '동일성은 미확인' in result['summary_text']
    old=aggregate.summarize({'options':['찬성','반대']},people,{'main':{'a':[.8,.2]}},[])
    assert 'historical_baseline' not in old['accuracy']['payload']
    wrong_panel=aggregate.summarize({'options':['찬성','반대']},people,{'main':{'a':[.8,.2]}},[],panel_version='wrong')
    assert 'historical_baseline' not in wrong_panel['accuracy']['payload']


@pytest.mark.parametrize('change',['hash','metric','budget','incomplete','source','pair'])
def test_reject_invalid_promotions(bundle,change):
    parent=bundle.parent
    if change in ['hash','metric','pair']:
        path=parent/'comparison-2024.json';data=read_json(path)
        if change=='pair':data['input_hashes']['paired_responses']='e'*64
        else:data['items'][0]['mae_overall_pp']=99
    elif change=='source':
        path=parent/'sources-reviewed.json';data=read_json(path);data['payload']['items'][0]['status']='unverified'
    else:
        path=parent/'measured-run.json';data=read_json(path)
        if change=='budget':data['cost_usd']=1.51
        else:data['status']='stopped'
    path.write_bytes(canonical(data))
    if change!='hash':
        manifest=read_json(bundle);manifest['artifacts'][path.name]=file_hash(path);bundle.write_bytes(canonical(manifest))
    assert history.load(bundle) is None
