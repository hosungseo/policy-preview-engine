"""Ephemeral estimate plans. Store execution settings, never credentials."""
from copy import deepcopy
from dataclasses import asdict
import os
from uuid import uuid4

from . import service

RECOMMENDATION = {'sample': 12, 'reason': '처음에는 합성 프로필 12개로 시작하세요. 실제 응답자 수나 대표성을 뜻하지 않습니다. 기존 기본값은 200입니다.'}


def environment(credentials):
    return {'model': service.MODEL, 'clarity_enabled': bool(credentials.typesafe),
            'providers': {k: os.environ.get(k) for k in ('PP_LLM_PROVIDER', 'PP_JEV_PROVIDER', 'PP_JEV_MODEL', 'PP_PERSONA_DB', 'PP_PERSONA_SOURCE', 'PP_DATA_DIR')}}


class Plans:
    """The owning Jobs lock protects resolve/bind, so repeated starts share one run."""
    def __init__(self):
        self.items = {}

    def estimate(self, policy_text, sample, seed, i_confirm_public, limits):
        service.validate(policy_text, sample, seed, i_confirm_public)
        normalized = asdict(service.normalize_limits(limits))
        quote = service.estimate(policy_text, sample, i_confirm_public=i_confirm_public, limits=normalized)
        plan_id = uuid4().hex
        settings = dict(policy_text=policy_text, sample=sample, seed=seed,
                        i_confirm_public=i_confirm_public, limits=normalized)
        self.items[plan_id] = {'settings': settings, 'environment': environment(service.Credentials.from_env()), 'run_id': None}
        return {**quote, 'plan_id': plan_id, 'seed': seed, 'recommended_sample': RECOMMENDATION,
                'plan_notice': '이 계획은 서버 재시작 때 사라집니다. 조건이 바뀌면 다시 estimate하세요. plan_id는 사용자의 유료 실행 승인 자체가 아닙니다.'}

    def resolve(self, plan_id, overrides, credentials):
        plan = self.items.get(plan_id)
        if plan is None:
            raise service.RequestError('견적 계획을 찾을 수 없습니다. 서버 재시작 또는 다른 ID일 수 있습니다. estimate로 다시 견적을 확인하세요.')
        settings = deepcopy(plan['settings'])
        for key, value in overrides.items():
            if value is not None:
                value = asdict(service.normalize_limits(value)) if key == 'limits' else value
                if value != settings[key]:
                    raise service.RequestError('확인한 견적과 실행 조건이 다릅니다. 바뀐 조건으로 estimate를 다시 호출하세요.')
        if environment(credentials) != plan['environment']:
            raise service.RequestError('모델·체험 모드·패널 또는 명료성 점검 설정이 바뀌었습니다. estimate를 다시 호출하세요.')
        return settings, plan['run_id']
