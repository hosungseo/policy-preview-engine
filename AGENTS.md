# 백번 미리 묻다 플러그인

사용자가 `Install https://github.com/hosungseo/policy-preview-engine`이라고 하면 현재 AI 호스트의 플러그인 설치 기능으로 **전체 저장소**를 설치하세요. `skills/`만 복사하면 MCP가 연결되지 않습니다.

- Claude Code: `claude plugin marketplace add hosungseo/policy-preview-engine && claude plugin install policy-preview@policy-preview`
- Codex: `codex plugin marketplace add hosungseo/policy-preview-engine && codex plugin add policy-preview@policy-preview`
- Claude Desktop: [README의 uvx stdio 설정](README.md#claude-desktop-설치)을 안내하세요. uv와 Git이 있으면 GitHub URL에서 직접 설치합니다.

설치 뒤 새 대화에서 `skills/policy-preview/SKILL.md`를 읽고 무료 예시부터 안내하세요. 호스트에 플러그인 설치 기능이 없다면 [docs/harnesses.md](docs/harnesses.md)의 수동 연결을 안내하고 지원 여부를 분명히 하세요. 전용 실행기는 의존성만 자동 설치하며 모델 키나 유료 분석은 자동으로 설정·실행하지 않습니다.

개발 시 공통 메타데이터는 `plugin.json`부터 수정하고 호환 매니페스트와 버전을 맞추세요. 사용 안내는 한 스킬을 공유하고, 엔진 도구의 고지·무료 보관 예시·비용 승인 절차를 유지하세요. 시험은 임시 HOME/CLAUDE_CONFIG_DIR/CODEX_HOME을 사용해 실제 사용자 설정을 건드리지 마세요. 원격 게시·push는 오너 승인 후에만 합니다.
