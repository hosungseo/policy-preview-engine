# 숫자 결과 계약: pp.run/4

빠른 CLI·HTTP·MCP 경로는 같은 `service.run_policy`를 사용합니다. 기존 `pp.run/3` 정성 필드는 유지하며 계산된 숫자를 별도 영역에 추가합니다. 문장 모델이 임의로 만든 찬반 숫자는 여전히 정성 출력 검사에서 제외합니다.

- `decision_sample`: 판단 모델 추출 수. 기본 3,000, 최대 5,000. `PP_DECISION_SAMPLE`로 기본값 변경 가능. `sample`은 기존대로 이유 수집 인원이며 기본 200입니다.
- `estimate.stages.distribution`: 판단 모델, 요청 인원, 입력량 가정, 비용 범위, 대조 문장·선택지 뒤집기 점검, 키가 없을 때 소표본 대체 안내.
- `estimate.stages.reasons`: 문장 모델, 이유 수집 인원, 비용 범위. 최상단 비용은 두 단계 합계입니다. 비용과 시간은 계획용 추정치입니다.
- `overall`: 대표 패널의 `n`, `counts`, `rates`(`support`, `oppose`, `unknown`), 원본 풀 `population`, `representative`, 별도 `affected`, `reason_sample_n`, 판단 모델 설정 `decision`, `variability`입니다. 실제로 사용한 풀 크기를 표시하며 축소 패널을 100만 명으로 표시하지 않습니다.
- `counts`는 판단 모델에서 확률 합계(`count_kind=expected`), 문장 모델 소표본 대체에서 단일 선택 수(`count_kind=selected`)입니다. 추정 인원과 실제 선택 건수를 혼용하면 안 됩니다. `rates`는 0~1 값입니다.
- `overall.distribution_selection`: 판단 패널의 층화 추출 영수증. MCP 기본 요약에는 포함하지 않습니다.
- `by_group`: `age_band`, `region`, `province`, `sex`별 목록입니다. 각 행에 `panel`, `n`, `counts`, `rates`, 전체 대비 차이 `delta_pp`, `variability`, 비교 기준 `comparison_threshold_pp`, `highlight`, 소집단 경고가 있습니다. 영향권은 대표 패널 전체 비율과 합산하지 않습니다.
- `variability`: 기본 질문과 대조 문장/뒤집은 선택지의 확률 평균 분포를 비교합니다. 각 점검에서 찬성·반대·모름 변화 중 최대 절댓값을 %p로 계산합니다. `width_pp=max(3, control_pp, order_pp)`이며 7%p 초과는 `UNSTABLE_PP`입니다. 통계적 표본오차나 신뢰구간이 아닙니다. 측정하지 않았으면 `available=false`, 수치는 null입니다.
- 소집단: 5명 미만은 `rates=null`, 인원만 표시합니다. 5~29명은 소집단 주의, 30~99명은 표본 여유 부족 주석입니다. 강조는 대표 패널 100명 이상, 전체와 집단 모두 측정·안정 상태이며 최대 차이가 `전체 흔들림 + 집단 흔들림 + 100/sqrt(집단 인원)`을 넘을 때만 생성합니다. 마지막 항은 보수적인 비교 여유 기준이며 통계 오차 추정이 아닙니다.
- `highlights`: 기준을 넘는 집단의 숫자와 `visit_shared`의 현장 접점 `outreach`를 연결합니다. 실제 협조나 실제 주민 의견이 확인됐다는 뜻이 아닙니다.
- `slice_data`: 반환한 결과만 다시 집계하는 `pp.slice/1` 행입니다. 이름·개인 서사는 넣지 않고 합성 UUID와 연령·지역·성별·패널·확률 및 별도 이유 소표본을 유지합니다.
- `baseline`: 정확히 확인한 `pp trend` 결과가 있을 때만 표시합니다. 없으면 `available=false`입니다.

## 무료 재집계

MCP: `slice_results(id=실행번호, filters={"age_min":60,"age_max":69,"region":"동남권"})`. 저장한 전체 결과는 `id` 대신 `result`로 넣습니다. 두 입력은 동시에 넣지 않습니다.

HTTP: `POST /slice-results`, 본문은 `{"result": 전체결과, "filters": {...}, "reason_limit": 3}` 또는 `{"id": 실행번호, ...}`입니다.

CLI: `pp slice-results result.json --filters '{"province":"서울","stance":"support"}'`.

조건은 `age_min`, `age_max`, `age_band`, `region`, `province`, `sex`, `stance`, `panel`입니다. `stance`는 `support`/`oppose`/`unknown`, `panel`은 기본 `representative` 또는 `affected`입니다. 여러 조건은 AND입니다. 판단 모델의 찬반 필터는 확률이 가장 높은 선택을 기준으로 사람을 고릅니다. 필터로 정해진 비율은 표시하지 않으며 rates와 counts는 null입니다. 문장 모델의 이유는 같은 조건의 별도 소표본이며 판단 모델 개인별 이유로 단정하지 않습니다. `reason_limit`은 0~10입니다. 모든 재집계는 비용·모델 호출 0이며 축소 인원에 소집단 규칙과 흔들림을 다시 계산합니다.

## 과거 공개 기준선

`estimate`·`start_run` 및 HTTP 요청의 선택 인자 `baseline` 또는 CLI `--baseline file.json`에 `pp trend` 출력과 `definition`을 넣습니다. 임의로 비슷한 주제를 매칭하지 않습니다. 현재는 전체 대한민국 19세 이상 기준선만 지원합니다.

```json
{
  "kind": "historical_trend_baseline",
  "question_id": "교통지원-q1",
  "definition_id": "검토한-정의-v1",
  "group": "all",
  "options": ["찬성", "반대", "모름"],
  "probabilities": [0.5, 0.3, 0.2],
  "source_name": "통계청 사회조사",
  "method": "last",
  "target_year": 2026,
  "as_of": "2025-12-31",
  "history_sources": [{"year": 2024, "released_at": "2024-12-20", "source_url": "https://example.org/public"}],
  "cost_usd": 0,
  "model_calls": 0,
  "definition": {
    "confirmed": true,
    "policy_text": "실행할 policy_text와 정확히 동일한 문안",
    "question_id": "교통지원-q1",
    "definition_id": "검토한-정의-v1",
    "group": "all",
    "options": ["찬성", "반대", "모름"],
    "stance_keys": ["support", "oppose", "unknown"],
    "population": "대한민국 19세 이상",
    "group_boundaries": "전체"
  }
}
```

`confirmed`는 호출자가 원자료 정의를 검토했다는 명시적 확인입니다. 문항 문구·선택지·모집단·집단 경계의 실제 의미 일치 여부를 엔진이 자동 판정하지 않습니다. 기준일 이전 공표, 목표 연도 이전 관측, 확률·식별자 일치도 검사합니다. 기준선은 과거 추세 참고값이며 현재 여론이나 합성 응답의 정답이 아닙니다.

## 무료 보관 예시

포장 스크립트는 `web/public/runs`의 원본과 SHA-256 출처를 유지합니다. 도시철도는 Jev 5,000명 원본 확률 평균의 찬성 쪽 46.93%, 반대 쪽 17.18%, 모름·유보 35.88%를 그대로 사용합니다(원본 반올림 합계 99.99%). 숫자를 정수 선택 건수로 바꾸지 않습니다.

원본의 집단별 `reserve`는 반대·유보 합계이므로 `favor=1-reserve`와 함께 표시합니다(도시철도 60대 893명, 찬성 쪽 39.08%, 반대·유보 60.92%). 반대와 모름을 따로 복원할 수 없으므로 세 선택지의 `rates`는 null로 유지합니다. 원래 쟁점 순서·반복·배치 점검은 전체 찬반의 문장/선택지 흔들림과 다른 검사라서 `width_pp`로 재사용하지 않습니다. 보관 예시 재집계는 조건이 저장 집단표와 같으면 그 Jev 행을 반환합니다(`source_scope=archived_group_table`). 70세 이상은 age_min:70도 같은 집단으로 처리합니다. 표에 없는 조건은 숫자 없이 이유 목소리만 반환합니다(`source_scope=archived_voices_only`, n/rates/counts=null). 이유 소표본은 비율로 표시하지 않으며 문장 모델 쏠림을 알립니다. 새 모델 호출로 숫자를 보충하지 않습니다.
