# 설치 환경 안내

하나의 저장소가 MCP 엔진과 `skills/policy-preview/SKILL.md`를 함께 배포합니다. 호스트마다 스킬을 복제하지 않습니다.

| 환경 | 설치 |
| --- | --- |
| Claude Code | `claude plugin marketplace add hosungseo/policy-preview-engine && claude plugin install policy-preview@policy-preview` |
| Codex | `codex plugin marketplace add hosungseo/policy-preview-engine && codex plugin add policy-preview@policy-preview` |
| Claude Desktop | [README의 uvx stdio 설정](../README.md#claude-desktop-설치)을 복사합니다. GitHub URL에서 격리 설치하며 uv와 Git이 필요합니다. |

다른 MCP 클라이언트도 stdio 설정으로 연결할 수 있지만 시험하지 않았습니다.

Claude Code·Codex는 설치 후 새 대화를 열면 MCP와 안내 스킬을 함께 씁니다. Desktop은 MCP 도구·안내 메뉴·읽을거리를 씁니다. 처음에는 무료 예시를 권하고, 내 문안은 비용을 확인한 뒤 실행합니다. 키를 요구하는 설치 절차는 없으며, 선택적 유료 실행 설정은 [README](../README.md#선택-설정-내-문안으로-실제-실행)를 참고하세요.

## 매니페스트와 실행기

| 환경 | 발견 파일 | MCP 연결 | 스킬 |
| --- | --- | --- | --- |
| Claude Code | `.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json` | `.mcp.json`의 `${CLAUDE_PLUGIN_ROOT}` | `skills/` |
| Codex | `.agents/plugins/marketplace.json`, `.codex-plugin/plugin.json` | `mcp.json`의 `${PLUGIN_ROOT}` | `skills/`, 설치 후 안내는 `onboardingSkill` |
| Claude Desktop | 사용자가 편집하는 `claude_desktop_config.json` | `uvx --python 3.12 --from git+https://github.com/hosungseo/policy-preview-engine@ae3bcc38a2898089cb4cfc078a1453ffa9101449 pp mcp` | 플러그인 스킬 없음, MCP 안내 제공 |

루트 `plugin.json`이 공통 이름·버전·설명·저작자 메타데이터의 기준입니다. 호환 매니페스트의 공통 값을 함께 갱신하세요. `.agents/plugins/`는 Codex용 카탈로그이며, 별도 서버나 스킬 사본이 아닙니다.

Claude Code·Codex 플러그인은 `sh scripts/plugin-mcp.sh`를 시작합니다. 실행기는 번들 위치·의존성 명세에 따라 사용자 캐시 아래 전용 가상환경을 만듭니다. uv가 있으면 uv, uvx만 있으면 uvx를 쓰고, 둘 다 없으면 Python 3.12 이상의 `venv`·`pip`를 사용합니다. 준비된 환경은 다음부터 재사용하며 패키지 저장소를 조회하지 않습니다. 첫 준비 실패에는 한국어 원인·조치 안내를 stderr에 냅니다. MCP stdout은 프로토콜에만 사용합니다.

플러그인은 키를 저장하지 않고 모델을 자동 실행하지 않습니다. 무료 흐름 `check_setup → try_example → slice_results`는 공개 보관 자료만 읽습니다. `ready=false`는 실제 유료 실행 준비 상태이며 무료 예시가 막혔다는 뜻이 아닙니다. 결과 `id`는 서버 재시작 시 사라집니다.

## 플러그인이 없는 AI

Claude Desktop은 [README의 설정](../README.md#claude-desktop-설치)으로 GitHub URL에서 바로 설치합니다. uvx는 루트 `pyproject.toml`의 `pp = "pp.cli:main"` 진입점과 `engine/` 패키지를 설치하며 무료 예시 자료도 패키지에 포함합니다. 저장소 수동 복제·venv·pip·절대 경로 입력은 필요 없습니다. macOS에서 정확한 command/args의 stdio 무료 흐름을 검증했지만 Desktop GUI·로그인한 자연어 대화·Windows 네이티브 실행은 미검증입니다. 개발자용 수동 설치는 README의 [고급 연결](../README.md#mcp로-쓰기-고급-수동-설치와-연결)을 참고하세요.

## 격리 검증

실제 사용자 설정을 바꾸지 않도록 임시 `HOME`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`을 사용합니다. 로컬 마켓플레이스 추가·설치 후 설치된 번들의 연결 파일대로 서버를 띄우고 공식 Python MCP `ClientSession`으로 도구 목록과 무료 흐름을 확인합니다. AI 모델 호출은 검증에 필요하지 않습니다. 의존성 준비 뒤 네트워크를 차단해 무료 흐름을 검증합니다.

검증 결과와 재현 방법은 [설치 검증 기록](install-verification.md)에 남깁니다. 원격 GitHub 설치는 변경을 push하기 전에는 새 포장을 받을 수 없으므로 로컬 설치 검증과 구분합니다.
