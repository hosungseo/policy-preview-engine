#!/bin/bash
# Start the review server with one of three model setups. The screen shows which one is running.
#   scripts/serve-profile.sh global   # Claude (sentences) + TypeSafe Jev (decisions)
#   scripts/serve-profile.sh korean   # LG EXAONE + Upstage Solar Decide
#   scripts/serve-profile.sh local    # local OpenAI-compatible LLM (e.g. Gemma 4) + local decision model (e.g. tev1:4b)
#   scripts/serve-profile.sh mock     # no keys, no model calls
# Keys come from the git-ignored .env (copy .env.example; never commit it). A legacy .env.service is read when .env is absent. Local endpoints default to Ollama on this machine and
# can be pointed elsewhere with PP_LOCAL_LLM_URL, PP_LOCAL_LLM_MODEL, PP_LOCAL_DECISION_URL, PP_LOCAL_DECISION_MODEL.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KIND="${1:-mock}"
load_env_file() {
  local file="$1" line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ "$line" == export[[:space:]]* ]]; then
      line="${line#export}"
      line="${line#"${line%%[![:space:]]*}"}"
    fi
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ ${#value} -ge 2 ]]; then
      if [[ "$value" == \"*\" && "$value" == *\" ]]; then
        value="${value:1:${#value}-2}"
      elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
        value="${value:1:${#value}-2}"
      fi
    fi
    [[ -z "$value" ]] && continue
    [[ -n "${!key:-}" ]] || export "$key=$value"
  done < "$file"
}

ENV_FILE="$ROOT/.env"
[[ -f "$ENV_FILE" ]] || ENV_FILE="$ROOT/.env.service"
if [[ -f "$ENV_FILE" ]]; then
  # Variables already set by the caller win over the file (e.g. PP_SERVICE_DATA for a second instance).
  load_env_file "$ENV_FILE"
elif [[ "$KIND" == "global" || "$KIND" == "korean" ]]; then
  echo "안내: .env 파일이 없습니다. 필요 시 'cp .env.example .env && chmod 600 .env'로 만들고 API 키를 설정하세요." >&2
fi
case "$KIND" in
  global)
    export PP_LLM_PROVIDER=cli PP_JEV_PROVIDER=api
    unset PP_JEV_URL PP_JEV_MODEL ;;
  korean)
    export PP_LLM_PROVIDER=exaone PP_JEV_PROVIDER=upstage PP_JEV_MODEL=solar-decide PP_EXAONE_LOCAL_ONLY=1 ;;
  local)
    export PP_LLM_PROVIDER=openai
    export PP_LLM_BASE_URL="${PP_LOCAL_LLM_URL:-http://127.0.0.1:11434/v1}"
    export PP_LLM_MODEL="${PP_LOCAL_LLM_MODEL:-gemma4}"
    export PP_JEV_PROVIDER=api
    export PP_JEV_URL="${PP_LOCAL_DECISION_URL:-http://127.0.0.1:11434/v1/systemone}"
    export PP_JEV_MODEL="${PP_LOCAL_DECISION_MODEL:-tev1:4b}"
    # Nothing leaves the machine: drop every cloud credential for this process.
    unset TYPESAFE_API_KEY UPSTAGE_API_KEY EXAONE_API_KEY PP_LLM_API_KEY PP_JEV_API_KEY ;;
  mock)
    export PP_LLM_PROVIDER=mock PP_JEV_PROVIDER=mock ;;
  *)
    echo "usage: $0 global|korean|local|mock" >&2; exit 2 ;;
esac
export PP_MODEL_PROFILE="$KIND"
PY_BIN="${PP_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PY_BIN" ]]; then
  echo "오류: Python 가상환경($PY_BIN)이 없습니다. 먼저 'python3.12 -m venv .venv && .venv/bin/pip install -r engine/requirements.txt -r engine/requirements-service.txt'를 실행하세요." >&2
  exit 1
fi
cd "$ROOT/engine"
exec "$PY_BIN" -m ppservice serve --host 127.0.0.1 --port "${PP_LOCAL_PORT:-8800}"
