# 선택 기능과 검증 범위

두 글자 검색 수정은 기본 동작에 반영했습니다. 아래 기능은 명시적으로 선택할 때만 동작하며, 기본 설치에 모델·실험 도구 의존성을 추가하지 않습니다.

## 로컬 검색 재순위

`PP_RERANK=nvidia`로 영향권 후보를 다시 정렬합니다. 이름을 제거한 서술 최대 300명을 채점한 뒤 기존 지역·연령 다양성 규칙을 적용합니다. 기본값은 `off`입니다. 실패·잠금 충돌·180초 시간 초과에는 원래 선택을 유지하고 선택 기록에 이유를 남깁니다.

별도 환경에 `torch`, `transformers`, `huggingface_hub`를 설치하고, 모델 이용 조건(OpenMDW 1.1 및 Llama 3.2 조건)을 확인한 뒤 고정 스냅샷을 미리 받으세요.

```sh
hf download nvidia/llama-nemotron-rerank-1b-v2 --revision 828765652b05bd439c9789d2a6d093db1caa1443
```

실행 시 다운로드하지 않습니다. 해당 revision의 모델 코드만 `trust_remote_code=True`로 읽습니다. 로컬 모델 잠금 기본 경로는 `~/.cache/policy-preview/local-model.lock`이며 `PP_LOCAL_MODEL_LOCK`으로 바꿀 수 있습니다. 여러 모델 실험은 같은 잠금 파일을 지정해야 합니다. 작은 검색 실험 결과가 전체 정책 판단 정확도 개선을 입증하지는 않습니다.

## 출력 안전 관문과 판단 모델

`PP_SAFETY_GATE=report`는 출력에 규칙 검사 결과를 덧붙이고, `block`은 걸린 줄을 가립니다. 기본값은 `off`입니다. 실제 여론으로 오해할 표현, 자격 단정, 근거 없는 개인사, 프롬프트 주입을 고정 규칙으로 검사합니다. 규칙은 의미 이해나 완전한 안전성을 보장하지 않습니다.

외부 Guardrails 검사 주소 `PP_SAFETY_GATE_URL`은 기본적으로 비어 있습니다. Content Safety·JailbreakDetect는 이번 검증 결과로 권장하지 않으며 모델·서버·설정·의존성을 배포에 넣지 않았습니다. 남겨 둔 외부 검사 접점은 loopback만 허용하며, 연결 오류는 `block`에서 내용을 가리고 `report`에서 오류를 기록합니다.

`PP_JEV_PROVIDER=upstage PP_JEV_MODEL=solar-decide-flash`는 Solar Decide Flash를 명시적으로 선택합니다. 기존 기본 모델은 유지하며 Upstage 키만 해당 공급자에게 보냅니다. 실서비스 품질·속도 우위는 이번 통합 시험 범위가 아닙니다.

## 과거 집계 기준선

```sh
pp trend --history history.json --question-id q --group '20대' \
  --definition-id q-v1-age20-29 --target-year 2027 --as-of 2026-11-27 --method last
```

입력은 JSON 배열입니다. 각 행에 `question_id`, `group`, `definition_id`, `year`, `fieldwork_end`, `released_at`, `source_url`, `options`, `probabilities`를 넣습니다. 예:

```json
[{"question_id":"q","group":"20대","definition_id":"q-v1-age20-29","year":2024,"fieldwork_end":"2024-05-30","released_at":"2024-11-20","source_url":"https://kosis.kr/example","options":["찬성","기타"],"probabilities":[0.4,0.6]}]
```

`last`는 마지막 관측값, `linear`는 과거값의 선형 추세입니다. 기준일 이후 공개된 자료와 목표 연도 자료는 쓰지 않습니다. 문항·선택지·모집단·집단 경계의 동일성은 사용자가 검토해 definition ID로 구분해야 합니다. 합성 인물 응답이 아닌 집계 참고값이며 Kumo 라이브러리나 모델을 사용하지 않습니다.

## 실행 기록 감사

```sh
python -m pp.trace_audit run.json --export-compass traces.jsonl --min-cases 3
```

명시적으로 전달한 JSON/JSONL 기록만 로컬에서 읽고 계약 위반 후보·반복 사례를 요약하며 NeMo Compass v3 형식으로 내보냅니다. NeMo Compass(Apache-2.0) 호환 형식이며 기본 엔진은 Compass 패키지나 모델을 불러오지 않습니다. 모델 호출과 외부 전송은 없습니다. 사례 ID가 다르다는 것이 통계적 독립성을 입증하지 않으며 감사 신호만으로 제품 결함을 확정하지 않습니다. AutoFA 코드·의존성·실험 결과는 공개 엔진에 포함하지 않습니다.

## 생활 여건 배정 수정

직업란의 `전직 …, 현재 구직중`을 현재 미취업 상태로 판정해 근로 형태·출퇴근·맞벌이·근무 관련 속성과 통계 조건에 일관되게 적용합니다. `구직 상담원` 같은 직업명은 계속 취업 상태로 취급합니다.

기초생활·기초연금 배정자가 순자산 상위 20%를 동시에 추첨하지 않도록 순자산 확률에 구조적 0을 넣은 뒤 보정합니다. 실제 제도의 소득인정액 산식이나 수급 자격을 구현한 것이 아닌 합성자료 정합 규칙입니다. 보정 오차와 한계를 진단에 남기며, 지원 가능한 확률이 없으면 미상으로 둡니다. 값 스키마는 `life-context-values-v4`입니다. 기존 패널·생활 여건 파일은 재생성하지 않았으므로 저장된 배정값은 바뀌지 않습니다. 새 로직 적용 여부는 다음 별도 데이터 빌드에서 확인해야 합니다.

실험용 다운로드·로그·모델 출력은 공개 이력에서 제외했습니다. Docling은 모델 계보에 대한 오너 판단 대기, 인물 서술 확장은 품질 미달, 다른 판단 모델 변환기는 실모델 실행 검증 미완료로 포함하지 않았습니다.
