# MCP 결과·진행·저장

처음에는 `check_setup → try_example → get_run(id) → get_run(id, view="full") → save_review(id)`로 키·패널 없이 무료 완주합니다. 무료 예시는 기존 공개 실행의 보관 결과(`mode: archived`)이며 새 분석이 아닙니다. 원본 질문·접점·문안·빠진 관점을 발췌한 네 예시와 출처·원본 파일 SHA-256·실행 시각이 설치 패키지에도 포함됩니다. 노인복지법 시행규칙은 문안만 제공하고 보관 결과를 꾸며 내지 않습니다.
내 문안의 0원 체험(`mode: mock`)은 카드 틀을 유지하되 “구조만 보여 주는 0원 체험입니다. 숫자·문장은 가짜이며, 실제 결과에는 API 키와 합성 인물 자료가 필요합니다.”를 맨 위에 표시합니다. 두 경로 모두 `mode`·`result_label`·`trial_notice`를 요약·전체·저장본에 남깁니다.
입법예고는 `find_notice → get_notice → estimate`로 무료로 찾고 읽습니다.

MCP의 권장 흐름은 `estimate → start_run(plan_id=…) → get_run(id) → save_review(id, path)`입니다.
실제 실행 의사는 견적을 본 사용자에게 확인하세요. `plan_id`만으로 사용자 승인을 증명하지는 않습니다.
모의 견적은 `requires_consent: false`, 수 초·0원으로 안내하며 사용자가 실행을 요청했다면 추가 동의 없이 실행합니다. 유료 견적은 `requires_consent: true`를 유지합니다. 설정·조회·견적·저장 확인에는 반응 고지문을 반복하지 않으며, 고지는 반응 결과와 저장 파일에 보존합니다.

```text
estimate(policy_text="공개 정책 문안", sample=12, seed=42, limits={"max_cost_usd": 2})
start_run(plan_id="견적에서 받은 plan_id")
get_run(id="실행에서 받은 id")
get_run(id="실행에서 받은 id", view="full")
save_review(id="실행에서 받은 id", path="/사용자가/정한/새파일.json")
```

첫 사용 권장은 합성 프로필 12개입니다. 기존 기본 sample=200은 유지합니다. 합성 프로필 수는 실제 응답자 수나 대표성의 근거가 아닙니다.

기본 조회는 ‘찾아갈 곳 · 먼저 물을 질문 · 명단 밖 사람’ 카드입니다. MCP text는 고지·출처·저장 안내를 포함해 최대 3,000자이며 별도 모델 호출 없이 기존 결과만 묶습니다. 문안 순서로 앞의 쟁점 세 개와 빠진 관점 네 개까지 보여 주며, 생략 여부는 `summary.truncated`에 표시합니다. 영수증·실행 입력·전체 반응은 `view="full"`로 확인합니다. full의 `result`와 저장 파일은 `pp.run/3`입니다. 문안 조건별 묶음과 찾아갈 곳·명단 밖 사람을 함께 보존합니다. HTTP와 CLI의 기존 전체 결과 계약도 유지합니다.

조회 응답은 `stage`·한국어 `stage_label`, `progress.completed_stages/total_stages`, `estimated_remaining_seconds`, `poll_after_ms`를 줍니다. 진행 수치는 실제로 끝난 단계 수이며 작업량 백분율이 아닙니다. 예상 시간은 기존 견적 범위에서 실행 경과 시간을 뺀 값이므로 보장 시간이 아니고 대기열 지연을 예측하지 않습니다.

견적 계획은 문안·sample·seed·확인한 문안 조건(conditions)·공개 확인·정규화한 예산 한도와 모델·provider 환경·패널 경로·선택 명료성 점검 여부를 기억합니다. 다른 조건으로 해당 계획을 실행하면 재견적을 요청합니다. 동일 계획 동시 재요청은 같은 작업 ID로 묶으며, 다시 분석하려면 새 견적을 받습니다. 기존 plan_id 없는 직접 실행은 호환성을 위해 유지하므로 그 경로에는 견적 일치 검사가 적용되지 않습니다. 이 단계의 계획 기능은 MCP와 공통 Jobs 메서드에서 제공하며 HTTP·CLI 견적에는 plan_id를 추가하지 않았습니다. 패널 파일 내용 자체를 견적 때 해싱하지는 않습니다.

작업과 계획은 메모리에만 있습니다. **서버를 재시작하면 ID와 결과를 잃습니다.** 프로그램 종료 전에 저장할지 한 번 안내합니다. `save_review`의 `path`는 선택 항목이며 기본은 홈의 `Documents/백번미리묻다/<작업 ID>.json`, 상대 경로는 홈 기준입니다. 폴더를 만들고 절대 경로를 돌려줍니다. 실패하면 경로 생략 또는 `~/Desktop/result-new.json` 같은 새 이름을 안내합니다. 고지·출처·영수증을 보존하고 기존 파일·심볼릭 링크는 덮어쓰지 않습니다. 원격 MCP에서는 클라이언트 컴퓨터의 파일 경로가 아닙니다.

## 통합 연결 지점

- `engine/pp/mcp.py`: `tool_result`의 카드 text, `estimate`의 Jobs 계획 생성, `start_run`의 선택 plan_id, `get_run`의 기본 summary/명시 full, 새 `save_review` 등록.
- `engine/pp/jobs.py`: `RunExperience` 믹스인, 계획·시간 상태 초기화, `_run`의 진행 context 및 시작 시각, `get`의 view 변환과 진행 snapshot. Jobs.get 기본은 기존 full.
- `engine/pp/service.py`: `run_progress` import와 preparing/reactions/questions/finalizing 단계 알림 네 곳. `policy_groups`·`visit_shared` 기반 `pp.run/3` 출력과 무료 체험을 연결.
- 새 모듈: `summary_card.py`, `run_progress.py`, `run_plans.py`, `run_experience.py`, `review_export.py`.
- 기존 시험의 MCP 도구 집합·estimate seed·full 조회 기대값을 갱신. `test_result_experience.py`에 무료 회귀 시험 추가.

통합본은 준비 점검·무료 예시·입법예고·견적 계획·요약·전체 조회·저장 문구와 README의 세 단계 안내를 실제 도구에 맞췄습니다. 조건 하위 항목은 MCP 입력 스키마에 표시하고, 잘못된 자격 목록 등은 입력값을 되풀이하지 않는 한국어 안내로 돌려줍니다.

## 검증 기록

키를 비우고 `PP_LLM_PROVIDER=mock PP_JEV_PROVIDER=mock`으로 엔진 전체 시험을 실행했습니다. 통합 후 결과는 **897 passed, 28 skipped**입니다. skip은 로컬 2만 명 패널 파일이 필요한 시험입니다. 조건 계획·체험 출처·설치 예시 회귀와 실제 stdio MCP 시험을 포함하며, 모델 응답은 mock 또는 네트워크를 차단한 가짜 전송기를 사용했습니다.
