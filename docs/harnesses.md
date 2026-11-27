# 설치 환경 안내

하나의 저장소가 MCP 엔진과 `skills/policy-preview/SKILL.md`를 함께 배포합니다. EGM의 전체 플러그인 설치 구조를 따르며, 호스트마다 스킬을 복제하지 않습니다.

| 환경 | 설치 |
| --- | --- |
| 어떤 AI든 | `Install https://github.com/hosungseo/policy-preview-engine`이라고 요청합니다. 호스트의 설치 기능이 있어야 합니다. |
| Claude Code | `claude plugin marketplace add hosungseo/policy-preview-engine && claude plugin install policy-preview@policy-preview` |
| Codex | `codex plugin marketplace add hosungseo/policy-preview-engine && codex plugin add policy-preview@policy-preview` |
| Antigravity | `agy plugin install https://github.com/hosungseo/policy-preview-engine` |

설치 후 새 대화를 열면 MCP와 안내 스킬을 함께 씁니다. 처음에는 무료 예시를 권하고, 내 문안은 비용을 확인한 뒤 실행합니다. 키를 요구하는 설치 절차는 없으며, 선택적 유료 실행 설정은 [README](../README.md#선택-설정-내-문안으로-실제-실행)를 참고하세요.

## 매니페스트와 실행기

| 환경 | 발견 파일 | MCP 연결 | 스킬 |
| --- | --- | --- | --- |
| Claude Code | `.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json` | `.mcp.json`의 `${CLAUDE_PLUGIN_ROOT}` | `skills/` |
| Codex | `.agents/plugins/marketplace.json`, `.codex-plugin/plugin.json` | `mcp.json`의 `${PLUGIN_ROOT}` | `skills/`, 설치 후 안내는 `onboardingSkill` |
| Antigravity | 루트 `plugin.json` | 표준 모드는 `mcp.json`, 기존 모드는 `mcp_config.json`의 `${PLUGIN_ROOT}` | 기본 `skills/` |

루트 `plugin.json`이 공통 이름·버전·설명·저작자 메타데이터의 기준입니다. 호환 매니페스트의 공통 값을 함께 갱신하세요. `.agents/plugins/`는 Codex용 카탈로그이며, 별도 서버나 스킬 사본이 아닙니다.

모든 호스트가 `sh scripts/plugin-mcp.sh`를 시작합니다. 실행기는 번들 위치·의존성 명세에 따라 사용자 캐시 아래 전용 가상환경을 만듭니다. uv가 있으면 uv, uvx만 있으면 uvx를 쓰고, 둘 다 없으면 Python 3.12 이상의 `venv`·`pip`를 사용합니다. 준비된 환경은 다음부터 재사용하며 패키지 저장소를 조회하지 않습니다. 첫 준비 실패에는 한국어 원인·조치 안내를 stderr에 냅니다. MCP stdout은 프로토콜에만 사용합니다.

플러그인은 키를 저장하지 않고 모델을 자동 실행하지 않습니다. 무료 흐름 `check_setup → try_example → slice_results`는 공개 보관 자료만 읽습니다. `ready=false`는 실제 유료 실행 준비 상태이며 무료 예시가 막혔다는 뜻이 아닙니다. 결과 `id`는 서버 재시작 시 사라집니다.

## 플러그인이 없는 AI

설치 기능이 없는 AI에게 GitHub 주소를 말하는 것만으로 호스트 기능이 생기지는 않습니다. MCP stdio 클라이언트가 있다면 저장소를 받아 `sh <저장소>/scripts/plugin-mcp.sh`를 서버 명령으로 지정하고, 같은 번들의 안내 스킬을 읽도록 연결할 수 있습니다. 실행기는 의존성을 자동 준비합니다. 기존 수동 Python 설치를 원하는 개발자는 README의 CLI·데스크톱 연결 예시를 사용할 수 있습니다.

## 격리 검증

실제 사용자 설정을 바꾸지 않도록 임시 `HOME`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`을 사용합니다. 로컬 마켓플레이스 추가·설치 후 설치된 번들의 연결 파일대로 서버를 띄우고 공식 Python MCP `ClientSession`으로 도구 목록과 무료 흐름을 확인합니다. AI 모델 호출은 검증에 필요하지 않습니다. 의존성 준비 뒤 네트워크를 차단해 무료 흐름을 검증합니다.

검증 결과와 재현 방법은 [설치 검증 기록](install-verification.md)에 남깁니다. 원격 GitHub 설치는 변경을 push하기 전에는 새 포장을 받을 수 없으므로 로컬 설치 검증과 구분합니다.
