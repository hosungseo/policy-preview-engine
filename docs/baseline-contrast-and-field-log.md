# 인물 순효과 대조 · 자동 진단 · 현장 확인 회수 기록 안내

합성 인물을 쓰는 것이 실제로 도움이 되는지 숫자로 확인하고, AI 응답의 대표적인 편향을 경고하며, 현장에서 직접 들은 결과로 돌아가는 절차를 정리한 문서입니다. 모든 기능은 **유료 모델 호출 없이 모의(mock) 시험과 오프라인 집계(0원)**로 먼저 점검할 수 있습니다.

---

## 1. 인물 순효과 대조 (선택 실행 모드)

합성 인물 수를 늘리기 전에, **같은 정책 문안과 같은 질문**을 아래 세 조건으로 나란히 비교합니다.

1. **(a) 인물 없음 (`no_persona`)**: 인물 설명을 전혀 넣지 않고 모델에 바로 묻습니다.
2. **(b) 수작업 소수 조건 (`manual`)**: 담당자가 손으로 적은 소수 조건(기본 5개 예시 또는 직접 만든 JSON)으로 묻습니다.
3. **(c) 합성 인물 (`synthetic`)**: 합성 인물 패널에서 뽑은 표본으로 묻습니다.

보고서에는 세 조건 대조 표와 함께 **「새로 고칠 문제가 늘었을 때만 확대」 판단 칸**이 자동으로 붙습니다.

- 인물 없는 대조군과의 차이(인물 순효과)가 흔들림 폭 이하이면 **확대 중단**을 권합니다.
- 수작업 소수 조건과 견줘 문안과 맞고 **새로 고칠 수 있는 문제**가 늘지 않으면 **수작업 유지**를 권합니다.
- 모의(`mock`) 시험 결과는 자리 채움 값이므로, 자동 판정이 항상 **`판단 보류(모의 시험 결과)`**로 고정됩니다.

### 모의 시험 실행 예시 (0원)

```bash
python engine/scripts/compare_persona_baseline.py \
  --policy engine/policies/subway-free-ride.json \
  --question "지하철 무임승차 기준 연령을 70세로 단계 상향하는 데 찬성하십니까?" \
  --options "찬성" "반대" "잘 모르겠다" \
  --n 40 \
  --out-md runs/contrast-subway.md \
  --out-json runs/contrast-subway.json
```

- 별도 옵션을 주지 않으면 항상 `PP_JEV_PROVIDER=mock`으로 실행됩니다. 실제 유료 모델을 쓸 때만 `--allow-paid`를 명시합니다.
- 직접 만든 수작업 조건 목록을 쓰려면 `--manual 조건파일.json`을, 세 조건에서 찾은 문제 목록을 함께 비교하려면 `--issues 문제목록.json`을 넘깁니다.
- 관련 코드: [`engine/pp/persona_contrast.py`](../engine/pp/persona_contrast.py), [`engine/scripts/compare_persona_baseline.py`](../engine/scripts/compare_persona_baseline.py)

---

## 2. 자동 진단과 문항별 신뢰도 사전 경보

최근 실증 연구(Morocho 외 2026, Jia 외 2026, Pourtaheri & Zareei 2026)에서 확인된 합성 인물의 대표적인 오류를 코드로 자동 점검해 보고서와 결과 화면에 경고로 표시합니다. 추가 모델 호출이 없어 비용은 **0원**입니다.

| 점검 항목 | 언제 경고가 뜨는가 | 보고서에 표시되는 뜻 |
|---|---|---|
| **문항 신뢰도 사전 경보(선택지 수)** | 선택지가 4~5개일 때 (`lint.py`) | 선택지가 많을수록 합성 인물 오차가 커지기 쉬우므로 실제 이용자 확인 비중을 높이도록 안내합니다. |
| **문항 신뢰도 사전 경보(주관적 체감)** | 문항에 "스트레스·만족·체감·불안·여가" 등 주관적 자기평가 표현이 있을 때 (`lint.py`) | 주관적 체감 문항은 합성 인물이 약하므로 실제 조사 비중을 높이도록 안내합니다. |
| **응답 쏠림(분산 압축) 진단** | 사람 간 표준편차 < 0.08 또는 사분위 폭 < 10%p 또는 평균 ±5%p 집중 비율 ≥ 80% | 합성 응답이 평균 주변으로 비슷하게 뭉쳐 실제 의견 폭을 좁게 볼 수 있다고 경고합니다. |
| **학력·소득 격차 과대추정 진단** | 전체 축 설명력(η²) 중 학력·소득 비중 ≥ 45% 또는 단일 축 η² ≥ 0.15 | AI가 실제 사람보다 학력·소득 격차를 크게 부풀리는 경향이 있으므로 가짜 격차를 현장 1순위로 오인하지 않도록 경고합니다. `찾아갈 곳` 카드의 학력·소득 카드에도 주의 문구가 붙습니다. |
| **고변동성 응답 경보** | 응답 분포의 정규화 엔트로피 ≥ 0.85 | 의견이 넓게 흩어지는 문항은 합성 오차가 커지기 쉬우므로 실제 조사를 우선하도록 안내합니다. |

- 정확도 비교 검증을 위한 다차원 지표 함수(`jsd`, `nmd_soft_similarity`, `informedness_j`, `equity_dpi`)도 [`engine/pp/diagnostics.py`](../engine/pp/diagnostics.py)에 함께 제공합니다.

---

## 3. 현장 확인 회수 기록과 적중·놓침 대조표

합성 미리보기는 누구를 먼저 찾아갈지 고르는 출발점입니다. 실제로 국민·담당자를 만나 들은 결과를 정해진 형식(CSV 또는 JSON)으로 적고, 미리 예측한 집단·막힘과 대조해 **적중 · 오탐 · 놓침 · 미방문** 표를 만듭니다.

### 기록 형식과 템플릿

- JSON 스키마: [`engine/schemas/field-verification-v1.schema.json`](../engine/schemas/field-verification-v1.schema.json)
- 바로 복사해 쓸 수 있는 예시 파일:
  - [`docs/templates/field-verification-template.csv`](templates/field-verification-template.csv)
  - [`docs/templates/field-verification-template.json`](templates/field-verification-template.json)
- **개인정보 차단**: 주민등록번호나 휴대전화 번호로 보이는 값이 들어 있으면 검증 단계에서 자동으로 거부합니다. 실명이나 연락처는 적지 마시기 바랍니다.

| 열 이름 | 설명 | 허용 값 예시 |
|---|---|---|
| `entry_id` | 기록 고유 번호 | `fv-001` |
| `visit_date` | 현장 방문·면담 날짜 | `2026-11-27` |
| `group_label` | 실제로 만난 집단 이름 | `70세 이상`, `대리 신청 보호자` |
| `venue` | 만난 장소·창구 유형 | `경로당·노인복지관`, `행정복지센터` |
| `participant_count` | 실제 면담 인원 수 | `5` (1 이상 정수) |
| `predicted_ref` | 비교한 예측 항목 ID·이름(놓친 항목이면 비움) | `card-1:70세 이상` |
| `item_kind` | 항목 구분 | `group`, `blocker`, `missing_party`, `unpredicted` |
| `outcome` | 현장 대조 판정 | `hit`(적중), `false_positive`(오탐), `miss`(놓침), `unverified`(미확인) |
| `field_finding` | 현장에서 실제로 들은 핵심 내용 요약 | 쉬운 문장으로 요약(개인정보 금지) |
| `action_taken` | 문안·정책 수정 반영 여부 | `revised`, `planned`, `no_change`, `pending` |
| `review_minutes` | 담당자 현장 확인·검토 소요 시간(분, 선택) | `60` |
| `notes` | 비고(선택) | 추가 메모 |

### 대조표 만들기 예시

```bash
# 1) 미리보기 결과(visit.json 또는 plan.json)에서 현장 기록용 CSV 템플릿 자동 생성
python engine/scripts/reconcile_field_log.py \
  --predictions runs/my-policy/plan.json \
  --init-csv runs/my-policy/field-log.csv

# 2) 현장 방문 뒤 채운 CSV(또는 JSON)를 예측 결과와 대조해 적중·놓침 표 출력
python engine/scripts/reconcile_field_log.py \
  --predictions runs/my-policy/plan.json \
  --field-log runs/my-policy/field-log.csv \
  --out-md runs/my-policy/field-reconciliation.md \
  --out-json runs/my-policy/field-reconciliation.json
```

- 관련 코드: [`engine/pp/field_log.py`](../engine/pp/field_log.py), [`engine/scripts/reconcile_field_log.py`](../engine/scripts/reconcile_field_log.py)
