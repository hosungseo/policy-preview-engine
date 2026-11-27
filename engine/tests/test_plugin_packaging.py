"""The three hosts must discover the same skill and boot a private MCP runtime."""
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_manifest_identity_and_complete_bundle():
    canonical = json.loads((ROOT / "plugin.json").read_text())
    for filename in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        manifest = json.loads((ROOT / filename).read_text())
        for key in ("name", "version", "description", "author", "repository", "license"):
            assert manifest[key] == canonical[key]
        assert (ROOT / manifest["skills"] / "policy-preview/SKILL.md").is_file()
        assert (ROOT / manifest["mcpServers"]).is_file()
    for filename in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"):
        catalog = json.loads((ROOT / filename).read_text())
        assert catalog["name"] == canonical["name"]
        assert catalog["plugins"][0]["name"] == canonical["name"]
        assert catalog["plugins"][0]["source"] == "./"
    for filename, variable in ((".mcp.json", "CLAUDE_PLUGIN_ROOT"), ("mcp.json", "PLUGIN_ROOT"), ("mcp_config.json", "PLUGIN_ROOT")):
        document = json.loads((ROOT / filename).read_text())
        if filename == "mcp.json":
            assert document["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
            assert document["mcpServers"]["policy-preview"]["type"] == "stdio"
        server = document["mcpServers"]["policy-preview"]
        assert server["command"] == "sh"
        path = server["args"][0].replace("${" + variable + "}", str(ROOT))
        assert Path(path).is_file()
        assert not server.get("env")  # No secrets or paid/mock mode imposed by installation.


@pytest.fixture
def bootstrap(tmp_path):
    """Only installer commands are fake; execute the real launcher and shell."""
    bundle = tmp_path / "plugin with spaces"
    (bundle / "scripts").mkdir(parents=True)
    (bundle / "engine").mkdir()
    (bundle / "pyproject.toml").write_text("[project]\nname='test'\n")
    (bundle / "engine/requirements-mcp.txt").write_text("")
    launcher = bundle / "scripts/plugin-mcp.sh"
    launcher.write_bytes((ROOT / "scripts/plugin-mcp.sh").read_bytes())
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("dirname", "cat", "cksum", "awk", "mkdir", "rmdir", "touch", "sleep"):
        import shutil
        (bin_dir / name).symlink_to(shutil.which(name))
    env = {"PATH": str(bin_dir), "HOME": str(tmp_path), "PP_PLUGIN_CACHE_DIR": str(tmp_path / "cache")}
    return launcher, bin_dir, env


def test_missing_runtime_has_actionable_korean_error(bootstrap):
    launcher, _, env = bootstrap
    response = subprocess.run(["/bin/sh", str(launcher)], env=env, text=True, capture_output=True)
    assert response.returncode != 0
    assert response.stdout == ""
    assert "uv 또는 Python 3.12 이상" in response.stderr
    assert "다시 켜세요" in response.stderr
    assert not list(Path(env["PP_PLUGIN_CACHE_DIR"]).rglob("ready"))
    assert not list(Path(env["PP_PLUGIN_CACHE_DIR"]).rglob("install.lock"))


def test_failed_download_can_be_retried(bootstrap):
    launcher, bin_dir, env = bootstrap
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/sh\necho dependency-fetch-failed >&2\nexit 2\n")
    uv.chmod(0o755)
    for _ in range(2):
        response = subprocess.run(["/bin/sh", str(launcher)], env=env, text=True, capture_output=True)
        assert response.returncode != 0 and response.stdout == ""
        assert "자동 설치에 실패" in response.stderr and "인터넷 연결" in response.stderr
        assert not list(Path(env["PP_PLUGIN_CACHE_DIR"]).rglob("ready"))
        assert not list(Path(env["PP_PLUGIN_CACHE_DIR"]).rglob("install.lock"))


def test_ready_runtime_does_not_call_installer(bootstrap):
    launcher, bin_dir, env = bootstrap
    # Ask the same POSIX utility, without duplicating its checksum algorithm.
    payload = (str(launcher.parents[1]) + "\n").encode() + (launcher.parents[1] / "pyproject.toml").read_bytes() + launcher.read_bytes()
    key = subprocess.run([str(bin_dir / "cksum")], input=payload, capture_output=True, check=True).stdout.split()[0].decode()
    runtime = Path(env["PP_PLUGIN_CACHE_DIR"]) / key
    (runtime / "venv/bin").mkdir(parents=True)
    python = runtime / "venv/bin/python"
    python.write_text('#!/bin/sh\n[ "$1" = "-m" ] && [ "$2" = "pp.cli" ] && [ "$3" = "mcp" ]\n')
    python.chmod(0o755)
    (runtime / "ready").touch()
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/sh\necho must-not-install >&2\nexit 2\n")
    uv.chmod(0o755)
    response = subprocess.run(["/bin/sh", str(launcher)], env=env, text=True, capture_output=True)
    assert response.returncode == 0 and response.stdout == "" and response.stderr == ""
