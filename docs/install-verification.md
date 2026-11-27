# 플러그인 설치 검증 — 2026-11-28

macOS arm64에서 EGM과 같은 전체 저장소 플러그인 포장을 검증했습니다. 아래 첫 기록은 로컬 설치 시험이며, 공개 main `d3c1792`의 원격 주소 설치 시험은 뒤의 별도 절에 기록합니다. 이번 재시도 수정은 로컬 브랜치에서만 검증하며 push하지 않았습니다.

| 환경 | 결과 | 확인한 범위 | 남은 한계 |
| --- | --- | --- | --- |
| Claude Code 2.1.330 | 됨 | 임시 설정의 로컬 marketplace add·install, 스킬 1개·MCP 1개 발견, native mcp list Connected, 공식 MCP 클라이언트의 무료 전체 흐름 | 모델을 통한 자연어 안내는 외부 연결 제한 때문에 호출하지 않음 |
| Codex CLI 0.171.0 | 됨 | 임시 CODEX_HOME의 로컬 marketplace add·plugin add, onboarding 스킬 발견, native app-server의 도구 9개·Connected·무료 전체 흐름 | 모델을 통한 자연어 안내는 호출하지 않음 |
| Antigravity (`agy`) | 일부 | 임시 HOME의 plugin install·list, 스킬 1개·MCP 1개 발견, 표준 매니페스트 검증, 설치된 설정 그대로 공식 MCP 클라이언트의 무료 전체 흐름 | GUI/네이티브 대화 자동 연결 미검증. agy mcp list는 플러그인 서버를 표시하지 않음 |

실제 사용자 설정은 수정하지 않았습니다. 임시 폴더 아래 `HOME`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `PP_PLUGIN_CACHE_DIR`을 사용했으며 시험 프로세스에는 API 키를 전달하지 않았습니다.

## 설치와 무료 실행

로컬 저장소 전체를 다음 명령으로 설치했습니다.

```sh
claude plugin marketplace add /path/to/policy-preview-engine
claude plugin install policy-preview@policy-preview
codex plugin marketplace add /path/to/policy-preview-engine
codex plugin add policy-preview@policy-preview
agy plugin install /path/to/policy-preview-engine
```

의존성 준비 후 macOS `sandbox-exec`의 `(deny network*)`로 **모든 네트워크를 차단**했습니다. 공식 Python MCP SDK의 `ClientSession`·`stdio_client`로 각 설치 번들의 연결 설정 그대로 서버를 시작했습니다. 준비된 환경을 재사용하므로 재시작 때 패키지를 내려받지 않았습니다.

공통 흐름은 `check_setup → try_example(example="subway-free-ride") → slice_results(id=<같은 세션의 반환 id>, filters={"age_band":"60대"})`입니다. 세 번들 모두 도구 9개, 키 없음, 무료 예시 completed, 숫자 카드 있음, 60대 재집계 model_calls=0·cost_usd=0을 확인했습니다. 실제 유료 실행 준비는 `ready=false`여도 무료 흐름은 끝까지 통과합니다.

Codex는 추가로 네트워크를 막은 `codex app-server --stdio`에서 `initialize → skills/list → plugin/read → thread/start → mcpServerStatus/list → mcpServer/tool/call`을 사용했습니다. 같은 스레드에서 무료 예시와 60대 재집계를 호출했습니다. `codex mcp list`는 플러그인 서버를 표시하지 않으므로 그 출력만으로 설치 실패를 판정하지 않습니다.

`mcp.json`에는 표준 `$schema`, `type: "stdio"`, `env: {}`를 명시합니다. Codex는 루트 `plugin.json`이 Agent Plugins 표준을 선언하면 이 파일을 읽으며, 선언이 불완전하면 호환 매니페스트에 MCP 경로가 있어도 서버를 발견하지 못할 수 있습니다. Claude용 `.mcp.json`과 Antigravity 기존 모드용 `mcp_config.json`도 같은 실행기를 가리킵니다.

Antigravity 검증기의 `AGENTS.md` 경고는 이 파일을 플러그인 런타임 규칙으로 읽지 않는다는 뜻입니다. 사용 안내는 발견된 `skills/policy-preview/SKILL.md`에 있으며 AGENTS.md는 저장소 설치·개발 안내입니다. 검증기에는 오류가 없고 스킬·서버가 각각 1개로 잡힙니다.

## 자동 준비와 사람이 할 일

- **uv**: 전용 가상환경 첫 준비와 설치 후 오프라인 무료 흐름 통과.
- **uvx만 PATH에 노출**: 정상 작동하는 uvx를 통해 uv·Python을 준비하고 전용 가상환경 설치 통과.
- **uv·uvx 없음**: Python 3.15만 추가한 PATH에서 `venv`·`pip` 자동 설치 후 오프라인 무료 흐름 통과.
- **누락·실패**: 한국어 조치 안내는 stderr에만 출력. 완료 표시가 없는 미완성 가상환경은 다음 실행에서 삭제하고 새로 준비합니다(uv·uvx·Python 공통). 삭제는 설치 잠금 안에서 확인한 전용 캐시의 `venv` 폴더로 한정하며, 빈 번호·잘못된 경로·심볼릭 링크는 삭제하지 않고 중단합니다. 공백 경로·가상환경 생성 후 의존성 실패·같은 경로 재시도·준비된 환경의 설치 생략은 회귀 시험에 포함합니다.

일반 사용자는 설치 후 새 대화를 열면 됩니다. uv/uvx 또는 Python 3.12 이상은 필요하지만, 무료 예시에는 별도 pip 명령·절대 경로 설정·API 키·패널 다운로드가 필요 없습니다. 내 문안을 실제 모델로 실행하려면 README의 선택적 키·패널 설정과 비용 동의가 필요합니다.

원래 포장 `d3c1792`는 오너 승인으로 공개되어 원격 주소 설치까지 확인했습니다. 이번 재시도 수정은 아직 공개하지 않았으므로 승인 후 별도로 배포해야 합니다. Antigravity GUI 연결, Linux·WSL·Windows 네이티브 실행은 미검증입니다. 실행기는 POSIX 셸을 사용하며 Windows 네이티브 지원을 주장하지 않습니다.

## 원격 주소 설치 확인(2026-11-28)

임시 HOME·CLAUDE_CONFIG_DIR·CODEX_HOME·XDG_CONFIG_HOME·XDG_CACHE_HOME을 새로 만들고 **실제 GitHub 주소**로 설치했습니다. Claude Code와 Codex가 clone한 저장소의 origin은 `https://github.com/hosungseo/policy-preview-engine.git`, HEAD는 공개 main `d3c17923fc12e4774e82b64be01ed72437dbe5af`로 확인했습니다. Antigravity도 같은 공개 주소를 clone해 설치했습니다. 오너의 실제 설정·키는 사용하거나 수정하지 않았습니다.

| 환경 | 결과 | 확인 범위 |
| --- | --- | --- |
| Claude Code 2.1.330 | 됨 | 원격 marketplace add·plugin install, 스킬 1개·MCP 1개 발견, native mcp list Connected, 공식 MCP 클라이언트의 무료 흐름 통과 |
| Codex CLI 0.171.0 | 됨 | 원격 marketplace add·plugin add, onboarding 스킬 발견, 정상 준비 후 native app-server에서 도구 9개·Connected·무료 흐름 통과 |
| Antigravity (`agy`) | 일부 | 원격 plugin install·list와 매니페스트 검증, 설치된 설정 그대로 공식 MCP 클라이언트의 무료 흐름 통과; GUI/네이티브 대화 연결은 미확인 |

```sh
claude plugin marketplace add hosungseo/policy-preview-engine
claude plugin install policy-preview@policy-preview
codex plugin marketplace add hosungseo/policy-preview-engine
codex plugin add policy-preview@policy-preview
agy plugin install https://github.com/hosungseo/policy-preview-engine
```

첫 의존성 준비 후 네트워크 전체를 OS sandbox로 차단했습니다. 세 원격 설치 번들 모두 키 없이 `check_setup → try_example → slice_results(filters={"age_band":"60대"})`가 통과했고, 무료 예시 completed·숫자 카드 있음·재집계 model_calls=0·cost_usd=0을 확인했습니다. Codex는 같은 native app-server 스레드의 도구 호출도 통과했습니다. Antigravity `agy mcp list`는 플러그인 서버를 표시하지 않아 GUI 연결 확인의 증거로 사용하지 않았습니다.

처음 Codex native 추가 시험에서는 준비한 PP_PLUGIN_CACHE_DIR 대신 임시 HOME의 기본 `.cache/policy-preview/plugins/`에 새 venv가 생겼고, 차단된 네트워크 때문에 MCP initialize 전에 종료했습니다. 생성 경로를 보면 Codex의 기본 하위 프로세스 환경 필터가 시험용 캐시 변수를 전달하지 않은 것으로 판단됩니다. 새 임시 HOME의 기본 캐시를 정상 준비한 뒤에는 같은 오프라인 native 시험이 통과했습니다. 이 시험 환경 차이를 원격 설치 자체의 실패와 구분합니다.

다만 초기 실패 뒤 같은 캐시에서 준비를 다시 시도하면 `uv venv`가 남은 venv를 거절하는 실제 결함도 발견했습니다(`A virtual environment already exists ... Use --clear to replace it`). 이번 로컬 수정은 ready가 없는 venv만 안전하게 정리해 세 설치 경로의 다음 시도가 새 환경에서 진행되도록 합니다. 가짜 설치기로 venv 생성 후 의존성 실패를 흉내 낸 오프라인 회귀 시험에서, 다음 시도의 성공·ready 생성·이웃 파일 보존을 확인했습니다. 실제 uv로도 빈 패키지 캐시와 네트워크 차단으로 의존성 준비를 실패시킨 뒤, 같은 실행 폴더에서 이미 받아 둔 패키지 캐시만 사용해 재시도하고 무료 예시·60대 재집계까지 통과했습니다(새 다운로드·모델 호출·비용 없음). 심볼릭 링크·잘못된 삭제 경로는 중단합니다. 공개 `d3c1792`의 원격 설치 결과와 아직 배포하지 않은 이 수정을 혼동하지 마세요.

## 회귀 시험과 재현

이번 재시도 수정 후 엔진 전체 시험은 **1,182개 통과, 28개 건너뜀**입니다(플러그인 포장·준비 시험 15개 포함). 공개 저장소에 없는 패널 자료를 요구하는 시험 등의 기존 skip 조건을 유지했습니다. 웹의 accuracy 9개 렌더 사례, panel 렌더 시험, principles 렌더 시험도 모두 통과했습니다. 셸 문법·Python 문법·`git diff --check`를 통과했으며, 원래 포장의 Claude strict 매니페스트 검증 결과도 유지합니다.

무료 연결 재현 도구는 `scripts/verify-plugin.py`입니다. 설치된 번들을 지정하고 MCP SDK가 설치된 시험용 Python으로 실행합니다. 일반 사용자가 이 검증 도구를 실행할 필요는 없습니다. 환경변수는 위와 같이 임시 폴더로 지정하고 키를 전달하지 마세요.

```sh
sh "$BUNDLE/scripts/plugin-mcp.sh" --prepare
# 의존성 준비 후 네트워크 전체 차단
sandbox-exec -p '(version 1)(allow default)(deny network*)' \
  "$TEST_PYTHON" scripts/verify-plugin.py "$BUNDLE" --harness claude
# --harness codex / --harness antigravity도 같은 방식
```

전체 엔진 시험에는 로컬 HTTP fixture가 있어 루프백만 허용하는 `scripts/offline-tests.sb`를 사용합니다. 처음 네트워크 전체를 차단한 전체 시험에서는 fixture 두 건의 bind만 거절됐으며, 외부 연결을 차단하고 루프백을 허용한 최종 시험은 통과했습니다. 최종 정책에서 외부 주소의 TCP 연결이 OS에 의해 거절되는 것도 확인했습니다.

```sh
cd engine
sandbox-exec -f ../scripts/offline-tests.sb "$TEST_PYTHON" -m pytest -q -o addopts=
```
