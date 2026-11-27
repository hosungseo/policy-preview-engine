# `neon-upgrade` 변경 요약 (`upgrade-review.md` 바로 할 것 2·3)

- 기준 커밋: `main` (`9e6144d`)
- 작업 브랜치: `neon-upgrade` (로컬 worktree 전용, 원격 push 없음)
- 범위 원칙: 데이터·통계 계산 로직(`aggregate.summarize`, `visit.view`, 패널/시리즈 산출 로직 등)은 변경하지 않고, 첫 실행·보안 오안내 차단 결함과 UI·안내 문구·표시 정합성만 수정했습니다.

---

## 1. 첫 실행·보안 오안내 차단 결함 수정 (과제 2)

1. **Docker `/api/config` `numpy` 누락 크래시 제거**
   - `engine/pp/config.py`에 `FUTURE_YEAR = 2030` 상수를 분리하고 `engine/ppservice/app.py`의 `/api/config`가 `pp.life_history` 대신 `pp.config.FUTURE_YEAR`를 참조하도록 변경했습니다.
   - `engine/pp/life_history.py`의 `import numpy as np`를 `pp/semantic.py`와 동일하게 `try/except ImportError`로 감싸 `requirements-service.txt` 단독 환경에서도 안전하게 import됩니다.
   - `engine/ppservice/survey/panel.py`의 `load()` 기본 인자 평가를 호출 시점(`panel.BUNDLE`)으로 미뤄 테스트/환경 경로 교체 시 일관되게 동작합니다.

2. **패널·`web/out`·`.env` 누락 시 500/404 대신 한국어 조치 안내 (서버·`ServiceGate` 구분)**
   - `engine/ppservice/app.py`:
     - `panel-20k.jsonl.gz` 누락 시 `/api/config`가 원시 500 대신 HTTP 503 JSON(`code: "panel_missing"`)과 `build_panel_from_nemotron.py` 실행 명령을 한국어로 반환합니다.
     - 잘못된 `.env` 리전/URL(`JevError`) 시 HTTP 503 JSON(`code: "config_error"`)으로 안내합니다.
     - API 키/`.env` 누락 시 `/api/config` 응답에 `setup_warnings` 한국어 조치 안내를 포함하고, 서버 기동 로그(`lifespan`)에도 패널·`web/out`·`.env` 누락 경고를 출력합니다.
     - `web/out` 미빌드 시 비-API 경로(`GET /{rest:path}`)가 조용한 404 대신 HTTP 503 한국어 HTML(`cd web && npm ci && npm run build` 안내)을 반환합니다.
   - `web/src/lib/reviewApi.ts`, `web/src/lib/useService.ts`, `web/src/components/review/ServiceGate.tsx`:
     - 정적 호스팅/네트워크 단절(`NoService`)과 서버 오류·초기 준비 미완료(`ApiError` 503/500 등)를 구분 표시합니다.
     - `ServiceGate`가 `panel_missing`/`config_error`/503 및 `setup_warnings`를 한국어 안내 카드로 표시합니다.

3. **`korean` 프로필 국내 리전 확인 규칙 강화**
   - `engine/pp/jev.py`에 `is_korean_host()`, `upstage_is_korean_region()`을 추가해 기존 우선순위(`UPSTAGE_BASE_URL > PP_UPSTAGE_REGION=kr|global > 기본 글로벌`)를 그대로 유지하면서 실제 엔드포인트가 국내 리전(`kr.api.upstage.ai`, `kr.*`, `*.kr`)으로 확인될 때만 국내로 판정합니다.
   - `engine/ppservice/profile.py`에서 Upstage 글로벌 엔드포인트(기본값 포함)일 때는 `decision.where = "global"`로 판정하고, `PP_MODEL_PROFILE=korean`이 명시돼 있어도 국내 리전이 확인되지 않으면 절대 `korean`("국산 모델 · 국내 API")으로 표시하지 않고 `mixed`로 격하합니다. `openai` 공급자의 단순 `"upstage" in url` 판정도 `is_korean_host()`로 교체했습니다.

4. **빈 환경변수(`""` / 공백) 미설정 동일 처리**
   - `engine/ppservice/settings.py`, `engine/ppservice/__main__.py`, `engine/ppservice/profile.py`, `engine/pp/jev.py`, `engine/pp/llm.py`, `engine/pp/config.py`, `engine/pp/bundle_db.py`에서 빈 문자열·공백 환경변수를 미설정과 동일하게 처리해 `int("")`/`float("")`/`Path("")`/빈 공급자 크래시를 제거했습니다.

5. **`.env` 파서 따옴표·CRLF·`export ` 처리**
   - `scripts/serve-profile.sh`의 `load_env_file()`과 `engine/pp/jev.py`의 `parse_dotenv_line()`에서 CRLF(`\r\n`), 앞뒤 공백, 선택적 `export ` 접두사, 쌍따옴표/홑따옴표 제거, 빈 값 무시, 호출자 환경변수 우선, 마지막 줄 개행 누락을 안전하게 처리합니다. `.env`·`.venv` 누락 시 한국어 안내를 출력합니다.

6. **Windows `fcntl` 크래시 및 보조 스크립트 import 오류 제거**
   - `engine/pp/filelock_util.py`를 추가해 POSIX `fcntl.flock`과 Windows `msvcrt.locking`을 분기하고, `engine/ppservice/jobs.py`와 `engine/pp/bundle_db.py`에서 최상단 `import fcntl`을 제거했습니다.
   - `engine/scripts/build_roster_1m.py`, `engine/scripts/export_visit.py`에 `sys.path.insert(0, ...)`를 추가해 `PYTHONPATH` 없이 직접 실행 시 `No module named 'pp'` 오류를 제거했습니다.

---

## 2. 불변 핵심 원칙 정합성 정리 (과제 3 — 표시·안내만 변경)

1. **찬반 `%` 막대·헤드라인·복사 문장 정리 및 ‘실제 사람 응답 0명’ 고지 통일**
   - `web/src/components/review/ResultView.tsx`: 상단 찬반 `%` 막대(`.rv-bars`)를 기본 화면에서 숨기고 접힌 `<details class="rv-more rv-internal-metrics">`("참고용 내부 지표 · 외부 보고·인용 금지")로 격하했습니다. `VisitView`(찾아갈 곳)를 상단 주 출력으로 올리고, 상단 라벨과 복사 문장에 `실제 사람 응답 0명`을 명시하며 복사 문장에서 찬반 `%`를 제거했습니다.
   - `web/src/components/review/VisitView.tsx`: 카드 본면에서 선택지 `%` 문구를 접힌 `참고용 내부 지표 · 왜 이 사람들인가`로 내리고, `찾아갈 곳 복사` 문장에 `실제 사람 응답 0명`과 대상·만날 곳·첫 질문만 포함하도록 정리했습니다.
   - `web/src/components/review/SurveyList.tsx`, `web/src/components/review/SurveyView.tsx`, `web/src/components/review/BatchNotices.tsx`: 목록 헤드라인 배지·이전 실행 행·사전 시험 기본 영역의 찬반 `%` 표시를 제거/접기 처리했습니다.
   - `web/src/app/runs/[id]/page.tsx`: 정적 사례 화면의 `ProbDistribution`·`SupportDistribution`도 접힌 `<details>`("참고용 내부 지표")로 격하했습니다.

2. **합성 인물 실명 표시 제거(익명 표기)**
   - `engine/pp/export.py`(`public_person`)와 `engine/ppservice/deep.py`(`_who`)에서 `name` 필드를 빈 문자열로 내보내도록 변경했습니다.
   - `web/src/lib/format.ts`(`personaShort`, `personaAnonBadge`, `stripPersonaName`), `web/src/components/PersonaCard.tsx`, `web/src/app/runs/[id]/hearing/page.tsx`, `web/src/components/HearingReads.tsx`, `web/src/components/map/MillionMap.tsx`에서 실명 표기를 제거하고 `합성 인물`·`합성 참석자 1~6`·연령대 배지·앞머리 실명 마스킹(`이 합성 인물은 ...`)으로 전환했습니다.

3. **‘발표 전/비공개 문안 입력 가능’ 안내 철회 및 잔존 ‘여론 미리 듣기’ 문구 정리**
   - `engine/ppservice/profile.py`, `web/src/lib/modelGuide.ts`, `web/src/components/review/ModelBadge.tsx`, `web/src/components/review/SurveyList.tsx`, `web/src/components/AiNotice.tsx`, `web/src/app/page.tsx`, `web/src/app/layout.tsx`, `web/src/app/review/review.css`, `engine/ppservice/deep.py`, `Dockerfile`, `README.md`에서 민감(S)/기밀(C)·발표 전 정책안·비공개 검토안 입력 허용 안내 및 `여론 미리 듣기`/`합성 여론 미리보기` 잔존 표현을 철회·정리하고, **공개·가상 문안 전용 + 실제 사람 응답 0명** 원칙으로 통일했습니다.

---

## 3. 검증 결과

- **Python 전체 테스트**: `PP_JEV_PROVIDER=mock PP_LLM_PROVIDER=mock ../.venv/bin/python -m pytest` → **266 passed, 26 skipped, 0 failed**
  - 신규/확장 테스트: `engine/tests/test_first_run_and_security.py`(9건), `engine/tests/test_profile.py`(12건)
- **Web 타입체크·렌더 테스트·정적 빌드**:
  - `npm run typecheck` (`tsc --noEmit`) 통과
  - `node scripts/test-accuracy-render.mjs` (9/9 PASS)
  - `node scripts/test-panel-render.mjs` (PASS)
  - `node scripts/test-principles-render.mjs` (4/4 PASS)
  - `npm run build` (Next.js 16 정적 페이지 51/51 생성) 통과
- **로컬 기동 검증 (`mock` 프로필)**:
  - `scripts/serve-profile.sh mock` 실제 기동 후 `GET /review/` HTTP 200, 패널 미생성 상태에서 `GET /api/config` HTTP 503 JSON(`code: "panel_missing"`, 한국어 조치 명령 포함) 확인.
- **Docker Python 서비스 환경 대체 검증 (`requirements-service.txt` 단독, `numpy` 미설치)**:
  - 임시 Python 3.12 가상환경에 `engine/requirements-service.txt`만 설치(24개 패키지, `numpy` 부재 확인)한 뒤 `GET /api/config`(HTTP 200, `future_year: 2030`) 및 `web/out` 미존재 시 `GET /`(HTTP 503 한국어 HTML) 통과 확인.

---

## 4. 이 환경에서 확인하지 못한 것

- **실제 `docker build` / 컨테이너 기동**: 로컬 macOS 환경에 `docker`(및 `podman`/`colima`/`orbstack`) CLI/데몬이 설치되어 있지 않아 실제 이미지 빌드는 실행하지 못했습니다. 대신 동일한 Python 3.12 + `requirements-service.txt` 단독 가상환경에서 `numpy` 없는 `/api/config` 기동을 검증했습니다.
- **2만 명 패널 및 life-history/forecast 종속 테스트 26건 (`skipped`)**: Hugging Face 원본 다운로드 없이 진행했으므로 `needs_panel` 및 `life-history`/`life-forecast` 미빌드 조건 테스트 26건은 건너뛰어졌습니다.
- **실제 Windows OS에서의 네이티브 `msvcrt.locking` 실행**: macOS에서 `fcntl=None` + `FakeMsvcrt` 모킹으로 단위 검증했으며, 실제 Windows 호스트 실행은 미확인입니다.
- **Playwright 브라우저 E2E 및 유료 외부 API 호출**: 본 과제 제약(유료 API 호출·맥미니 접속 금지) 및 오프라인 검증 범위에 따라 `web/scripts/e2e-*.mjs` 브라우저 실행과 실제 Upstage/EXAONE/TypeSafe/Claude API 호출은 수행하지 않았습니다.
