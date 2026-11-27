# 플러그인 설치 검증 — 2026-11-28

macOS arm64에서 EGM과 같은 전체 저장소 플러그인 포장을 검증했습니다. 원격 push는 하지 않았습니다.

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
- **누락·실패**: 한국어 조치 안내는 stderr에만 출력. 실패 시 완료 표시를 남기지 않아 재시도 가능. 공백 경로·실패 재시도·준비된 환경의 설치 생략은 회귀 시험 포함.

일반 사용자는 설치 후 새 대화를 열면 됩니다. uv/uvx 또는 Python 3.12 이상은 필요하지만, 무료 예시에는 별도 pip 명령·절대 경로 설정·API 키·패널 다운로드가 필요 없습니다. 내 문안을 실제 모델로 실행하려면 README의 선택적 키·패널 설정과 비용 동의가 필요합니다.

남은 외부 작업은 오너 승인 후 push와 원격 GitHub 주소로 새 포장을 받는 시험입니다. Antigravity GUI 연결, Linux·WSL·Windows 네이티브 실행은 미검증입니다. 실행기는 POSIX 셸을 사용하며 Windows 네이티브 지원을 주장하지 않습니다.

## 회귀 시험과 재현

엔진 전체 시험은 **1,171개 통과, 28개 건너뜀**입니다. 공개 저장소에 없는 패널 자료를 요구하는 시험 등의 기존 skip 조건을 유지했습니다. 웹의 accuracy 9개 렌더 사례, panel 렌더 시험, principles 렌더 시험도 모두 통과했습니다. 셸 문법·Python 문법·`git diff --check`·Claude strict 매니페스트 검증을 통과했습니다.

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
