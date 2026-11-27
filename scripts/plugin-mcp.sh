#!/bin/sh
# Keep stdout exclusively for the MCP stdio protocol, including the first boot.
set -eu
umask 077

fail() {
    printf '%s\n' "백번 미리 묻다: $*" >&2
    exit 1
}

PP_PLUGIN_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
# Include the location because editable installs refer to this particular bundle.
PP_CACHE_KEY=$({ printf '%s\n' "$PP_PLUGIN_ROOT"; cat "$PP_PLUGIN_ROOT/pyproject.toml" "$PP_PLUGIN_ROOT/engine/requirements-mcp.txt" "$0"; } | cksum | awk '{print $1}')
PP_RUNTIME="${PP_PLUGIN_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/policy-preview/plugins}/$PP_CACHE_KEY"
PP_VENV="$PP_RUNTIME/venv"
mkdir -p "$PP_RUNTIME" || fail '전용 실행 폴더를 만들 수 없습니다. 홈 폴더의 여유 공간과 쓰기 권한을 확인하고 다시 켜세요.'

if [ ! -f "$PP_RUNTIME/ready" ] || [ ! -x "$PP_VENV/bin/python" ]; then
    PP_WAIT=0
    until mkdir "$PP_RUNTIME/install.lock" 2>/dev/null; do
        PP_WAIT=$((PP_WAIT + 1))
        [ "$PP_WAIT" -lt 180 ] || fail '다른 창의 첫 설치가 끝나지 않았습니다. 설치 중인 창을 확인한 뒤 다시 켜세요. 중단된 설치라면 README의 설치 문제 해결을 참고하세요.'
        sleep 1
    done
    trap 'rmdir "$PP_RUNTIME/install.lock" 2>/dev/null || true' EXIT
    trap 'exit 1' HUP INT TERM
    if [ ! -f "$PP_RUNTIME/ready" ] || [ ! -x "$PP_VENV/bin/python" ]; then
        printf '%s\n' '백번 미리 묻다: 첫 실행에 필요한 도구를 전용 폴더에 준비합니다. 처음 한 번은 인터넷이 필요합니다.' >&2
        PP_INSTALL_HELP='자동 설치에 실패했습니다. 인터넷 연결·홈 폴더 여유 공간을 확인하고 다시 켜세요. 계속 실패하면 uv를 설치하거나 Python 3.12 이상(venv·pip 포함)을 준비하세요. 자세한 방법은 README의 설치 문제 해결을 참고하세요.'
        if command -v uv >/dev/null 2>&1; then
            uv venv --python '>=3.12' "$PP_VENV" >&2 || fail "$PP_INSTALL_HELP"
            uv pip install --python "$PP_VENV/bin/python" -r "$PP_PLUGIN_ROOT/engine/requirements-mcp.txt" -e "$PP_PLUGIN_ROOT" >&2 || fail "$PP_INSTALL_HELP"
        elif command -v uvx >/dev/null 2>&1; then
            uvx --from uv uv venv --python '>=3.12' "$PP_VENV" >&2 || fail "$PP_INSTALL_HELP"
            uvx --from uv uv pip install --python "$PP_VENV/bin/python" -r "$PP_PLUGIN_ROOT/engine/requirements-mcp.txt" -e "$PP_PLUGIN_ROOT" >&2 || fail "$PP_INSTALL_HELP"
        else
            PP_PYTHON=''
            for PP_CANDIDATE in python3 python3.15 python3.14 python3.13 python3.12 python; do
                if command -v "$PP_CANDIDATE" >/dev/null 2>&1 && "$PP_CANDIDATE" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
                    PP_PYTHON=$PP_CANDIDATE
                    break
                fi
            done
            [ -n "$PP_PYTHON" ] || fail 'uv 또는 Python 3.12 이상이 필요합니다. uv를 설치하고 AI 앱을 다시 켜세요(README의 설치 문제 해결). 패키지 설치나 경로 입력은 플러그인이 처리합니다.'
            "$PP_PYTHON" -m venv "$PP_VENV" >&2 || fail "$PP_INSTALL_HELP"
            "$PP_VENV/bin/python" -m pip install --disable-pip-version-check -r "$PP_PLUGIN_ROOT/engine/requirements-mcp.txt" -e "$PP_PLUGIN_ROOT" >&2 || fail "$PP_INSTALL_HELP"
        fi
        "$PP_VENV/bin/python" -c 'from pp.mcp import create_server; create_server()' >&2 || fail "$PP_INSTALL_HELP"
        touch "$PP_RUNTIME/ready"
    fi
    rmdir "$PP_RUNTIME/install.lock"
    trap - EXIT HUP INT TERM
fi

# For installers/tests that prefetch dependencies; normal hosts pass no arguments.
if [ "${1:-}" = '--prepare' ]; then
    exit 0
fi
exec "$PP_VENV/bin/python" -m pp.cli mcp
