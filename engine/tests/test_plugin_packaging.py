"""The three hosts must discover the same skill and boot a private MCP runtime."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

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
    for name in ("dirname", "cat", "cksum", "awk", "mkdir", "rmdir", "touch", "sleep", "rm"):
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


def runtime_path(bootstrap):
    launcher, bin_dir, env = bootstrap
    # Ask the same POSIX utility, without duplicating its checksum algorithm.
    payload = (str(launcher.parents[1].resolve()) + "\n").encode() + (launcher.parents[1] / "pyproject.toml").read_bytes() + launcher.read_bytes()
    key = subprocess.run([str(bin_dir / "cksum")], input=payload, capture_output=True, check=True).stdout.split()[0].decode()
    return Path(env["PP_PLUGIN_CACHE_DIR"]) / key


def test_ready_runtime_does_not_call_installer(bootstrap):
    launcher, bin_dir, env = bootstrap
    runtime = runtime_path(bootstrap)
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


@pytest.mark.parametrize("installer", ["uv", "uvx", "python3"])
def test_dependency_failure_after_venv_creation_recovers(bootstrap, installer):
    launcher, bin_dir, env = bootstrap
    runtime = runtime_path(bootstrap)
    attempts = launcher.parent / "dependency-attempts"
    env["PP_TEST_ATTEMPTS"] = str(attempts)
    # Real shell/filesystem and launch ordering, but no package downloads. Like uv,
    # the fake creator refuses an existing environment so reuse cannot mask the bug.
    stub = f"#!{sys.executable}\n" + textwrap.dedent('''\
        import os
        from pathlib import Path
        import sys

        args = sys.argv[1:]
        if args[:3] == ["--from", "uv", "uv"]:
            args = args[3:]
        if args[:1] == ["-c"]:
            if args[1].startswith("from pp.mcp"):
                assert (Path(__file__).parent.parent / "installed").exists()
            sys.exit(0)
        if args[:1] == ["venv"] or args[:2] == ["-m", "venv"]:
            target = Path(args[-1])
            if target.exists():
                sys.exit("venv already exists")
            (target / "bin").mkdir(parents=True)
            python = target / "bin/python"
            python.write_text(Path(__file__).read_text())
            python.chmod(0o755)
            sys.exit(0)
        if args[:2] == ["pip", "install"] or args[:3] == ["-m", "pip", "install"]:
            attempt_file = Path(os.environ["PP_TEST_ATTEMPTS"])
            attempt = int(attempt_file.read_text()) + 1 if attempt_file.exists() else 1
            attempt_file.write_text(str(attempt))
            if attempt == 1:
                sys.exit("simulated dependency download failure")
            python = Path(args[args.index("--python") + 1]) if "--python" in args else Path(__file__)
            (python.parent.parent / "installed").touch()
            sys.exit(0)
        sys.exit("unexpected installer arguments")
    ''')
    executable = bin_dir / installer
    executable.write_text(stub)
    executable.chmod(0o755)

    first = subprocess.run(["/bin/sh", str(launcher), "--prepare"], env=env, text=True, capture_output=True)
    assert first.returncode != 0 and first.stdout == ""
    assert "자동 설치에 실패" in first.stderr
    assert (runtime / "venv/bin/python").exists()
    assert not (runtime / "ready").exists()
    assert not (runtime / "install.lock").exists()
    stale = runtime / "venv/partial-from-failed-run"
    stale.touch()
    keep = runtime / "keep-outside-venv"
    keep.write_text("keep")

    second = subprocess.run(["/bin/sh", str(launcher), "--prepare"], env=env, text=True, capture_output=True)
    assert second.returncode == 0, second.stderr
    assert second.stdout == ""
    assert attempts.read_text() == "2"
    assert (runtime / "ready").exists() and (runtime / "venv/installed").exists()
    assert not stale.exists() and keep.read_text() == "keep"
    assert not (runtime / "install.lock").exists()
    third = subprocess.run(["/bin/sh", str(launcher), "--prepare"], env=env, text=True, capture_output=True)
    assert third.returncode == 0 and third.stdout == "" and third.stderr == ""
    assert attempts.read_text() == "2"


@pytest.mark.parametrize("target", ["runtime", "venv", "dangling-venv", "venv-file"])
def test_cleanup_refuses_unexpected_paths(bootstrap, target):
    launcher, _, _ = bootstrap
    runtime = runtime_path(bootstrap)
    outside = launcher.parent / "unrelated"
    outside.mkdir()
    keep = outside / "keep"
    keep.write_text("untouched")
    if target == "runtime":
        runtime.parent.mkdir(parents=True)
        runtime.symlink_to(outside, target_is_directory=True)
    else:
        runtime.mkdir(parents=True)
        if target == "venv-file":
            (runtime / "venv").write_text("not a directory")
        else:
            destination = outside if target == "venv" else outside / "missing"
            (runtime / "venv").symlink_to(destination, target_is_directory=True)
    response = subprocess.run(["/bin/sh", str(launcher), "--prepare"], env=bootstrap[2], text=True, capture_output=True)
    assert response.returncode != 0 and response.stdout == ""
    assert "경로" in response.stderr
    assert keep.read_text() == "untouched"
    assert not (runtime / "ready").exists()
    assert not (runtime / "install.lock").exists()


@pytest.mark.parametrize("key", ["", "../outside", "/"])
def test_invalid_cache_key_stops_before_cleanup(bootstrap, key):
    launcher, bin_dir, env = bootstrap
    # Replace only the private cksum symlink, never its system target.
    checksum = bin_dir / "cksum"
    checksum.unlink()
    checksum.write_text(f"#!/bin/sh\nprintf '%s\\n' '{key}'\n")
    checksum.chmod(0o755)
    response = subprocess.run(["/bin/sh", str(launcher), "--prepare"], env=env, text=True, capture_output=True)
    assert response.returncode != 0 and response.stdout == ""
    assert "폴더 번호" in response.stderr
    assert not Path(env["PP_PLUGIN_CACHE_DIR"]).exists()


def test_filesystem_root_is_not_a_plugin_cache(bootstrap):
    launcher, _, env = bootstrap
    env["PP_PLUGIN_CACHE_DIR"] = "/"
    response = subprocess.run(["/bin/sh", str(launcher), "--prepare"], env=env, text=True, capture_output=True)
    assert response.returncode != 0 and response.stdout == ""
    assert "플러그인 전용 폴더" in response.stderr
