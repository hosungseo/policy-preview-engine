"""Regression tests for first-run blockers, .env parsing, Windows locking, scripts, and principle alignment."""
from __future__ import annotations

import builtins
import gzip
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pp import bundle_db, config, export, filelock_util, jev, llm
from ppservice import deep, jobs, settings
from ppservice.app import create_app
from ppservice.survey import panel

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_tiny_panel(path: Path) -> Path:
    row = {
        "uuid": "u0001", "sex": "여자", "age": 42, "age_band": "40대", "province": "서울", "capital": True,
        "profile": "이름: (익명)\n성별·나이: 여자, 42세\n사는 곳: 서울-종로구 (서울)\n직업: 사무원\n학력: 4년제 대학교 / 혼인: 기혼\n가구: 배우자와 거주 / 주거: 아파트\n\n소개\n직업소개\n가족소개\n문화배경",
    }
    path.write_bytes(gzip.compress((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")))
    return path


def test_api_config_does_not_require_numpy(tmp_path, monkeypatch):
    """Docker service image omits numpy; /api/config and pp.life_history import must still work."""
    bundle = _write_tiny_panel(tmp_path / "panel.jsonl.gz")
    monkeypatch.setattr(panel, "BUNDLE", bundle)
    monkeypatch.setattr(panel, "_cache", {})
    monkeypatch.setenv("PP_SERVICE_DATA", str(tmp_path / "svc"))
    monkeypatch.setenv("PP_WEB_OUT", str(tmp_path / "noweb"))
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")

    real_import = builtins.__import__

    def block_numpy(name, *args, **kwargs):
        if name == "numpy" or name.startswith("numpy."):
            raise ModuleNotFoundError("No module named 'numpy'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_numpy)
    monkeypatch.delitem(sys.modules, "numpy", raising=False)
    monkeypatch.delitem(sys.modules, "pp.life_history", raising=False)

    # Even importing pp.life_history itself succeeds without numpy.
    lh = importlib.import_module("pp.life_history")
    assert lh.FUTURE_YEAR == config.FUTURE_YEAR == 2030
    assert lh.np is None

    app = create_app(settings.load(), start_workers=False)
    res = TestClient(app).get("/api/config")
    assert res.status_code == 200
    body = res.json()
    assert body["service"] is True and body["future_year"] == 2030 and body["setup_warnings"] == []


def test_missing_panel_returns_503_korean_guidance(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, "BUNDLE", tmp_path / "missing-panel.jsonl.gz")
    monkeypatch.setattr(panel, "_cache", {})
    monkeypatch.setenv("PP_SERVICE_DATA", str(tmp_path / "svc"))
    monkeypatch.setenv("PP_WEB_OUT", str(tmp_path / "noweb"))
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")

    app = create_app(settings.load(), start_workers=False)
    res = TestClient(app).get("/api/config")
    assert res.status_code == 503
    err = res.json()["error"]
    assert err["code"] == "panel_missing"
    assert "build_panel_from_nemotron.py" in err["message"]


def test_missing_web_out_returns_503_korean_html_instead_of_404(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_SERVICE_DATA", str(tmp_path / "svc"))
    monkeypatch.setenv("PP_WEB_OUT", str(tmp_path / "missing-out"))
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")

    app = create_app(settings.load(), start_workers=False)
    client = TestClient(app)
    for path in ("/", "/review/"):
        res = client.get(path)
        assert res.status_code == 503
        assert "text/html" in res.headers["content-type"]
        assert "web/out" in res.text and "npm run build" in res.text
    # API 404 still returns JSON.
    missing_api = client.get("/api/does-not-exist")
    assert missing_api.status_code == 404 and missing_api.json()["error"]["code"] == "not_found"


def test_bad_env_and_missing_api_key_return_korean_guidance(tmp_path, monkeypatch):
    bundle = _write_tiny_panel(tmp_path / "panel.jsonl.gz")
    monkeypatch.setattr(panel, "BUNDLE", bundle)
    monkeypatch.setattr(panel, "_cache", {})
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("PP_SERVICE_DATA", str(tmp_path / "svc"))
    monkeypatch.setenv("PP_WEB_OUT", str(tmp_path / "noweb"))
    monkeypatch.setenv("PP_JEV_PROVIDER", "upstage")
    monkeypatch.setenv("PP_UPSTAGE_REGION", "invalid-region")
    monkeypatch.delenv("UPSTAGE_BASE_URL", raising=False)
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)

    app = create_app(settings.load(), start_workers=False)
    bad = TestClient(app).get("/api/config")
    assert bad.status_code == 503 and bad.json()["error"]["code"] == "config_error"
    assert "PP_UPSTAGE_REGION" in bad.json()["error"]["message"]

    # Valid region, missing .env / key -> 200 with Korean setup_warnings.
    monkeypatch.delenv("PP_UPSTAGE_REGION", raising=False)
    ok = TestClient(app).get("/api/config")
    assert ok.status_code == 200
    warnings = ok.json()["setup_warnings"]
    assert warnings and "UPSTAGE_API_KEY" in warnings[0] and ".env" in warnings[0]


def test_empty_env_vars_are_treated_as_unset(tmp_path, monkeypatch):
    for key in (
        "PP_JEV_PROVIDER", "PP_LLM_PROVIDER", "PP_SURVEY_N", "PP_DAILY_BUDGET_USD",
        "PP_JEV_RPS", "PP_JEV_CACHE", "PP_JEV_MODEL", "PP_JEV_URL",
        "PP_LLM_TEMPERATURE", "PP_EXAONE_MAX_TOKENS", "PP_LLM_BASE_URL", "PP_LLM_MODEL",
        "PP_DATA_DIR", "PP_COOKIE_SECURE", "PP_DEMO_LOGIN", "PP_MODEL_PROFILE",
    ):
        monkeypatch.setenv(key, "   " if key.endswith("N") else "")
    monkeypatch.setenv("PP_SERVICE_DATA", str(tmp_path / "svc"))

    s = settings.load()
    assert s.jev_provider == "api"
    assert s.n == 3000
    assert s.daily_budget_usd == 10.0
    assert s.cookie_secure is False
    assert s.demo_login is False
    assert settings.jev_price_per_m_input() == 0.042
    assert llm.provider() == "cli"
    assert llm._exaone_max_tokens() == 16384
    assert jev.provider() == "api"
    assert jev.model() == "jev-latest"
    assert jev.cache_enabled() is True
    assert jev._rps_from_env() == 18.0
    assert config.data_dir() == config.REPO_ROOT / "data"


def test_dotenv_parser_handles_quotes_crlf_and_export(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_bytes(
        b"# comment\r\n"
        b'export TYPESAFE_API_KEY="ts_quoted_key"\r\n'
        b"  UPSTAGE_API_KEY = 'up_single_key'  \r\n"
        b"EMPTY_KEY=\r\n"
        b"PP_JEV_PROVIDER=\r\n"
        b"PLAIN_KEY=plain_value"  # no trailing newline
    )
    monkeypatch.setattr(jev.config, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    assert jev._env_or_repo_key("TYPESAFE_API_KEY") == "ts_quoted_key"
    assert jev._env_or_repo_key("UPSTAGE_API_KEY") == "up_single_key"
    assert jev._env_or_repo_key("EMPTY_KEY") is None
    assert jev._env_or_repo_key("PLAIN_KEY") == "plain_value"

    # Also test scripts/serve-profile.sh's load_env_file on the same CRLF/quoted/export file.
    script = (REPO_ROOT / "scripts" / "serve-profile.sh").read_text(encoding="utf-8")
    func_def = script.split("load_env_file()", 1)[1].split("\nENV_FILE=", 1)[0]
    bash_cmd = (
        f"load_env_file(){func_def}\n"
        f"export PLAIN_KEY=caller_wins\n"
        f"load_env_file '{env_file}'\n"
        'printf "%s|%s|%s|%s\\n" "$TYPESAFE_API_KEY" "$UPSTAGE_API_KEY" "$PLAIN_KEY" "${EMPTY_KEY:-UNSET}"\n'
    )
    proc = subprocess.run(["bash", "-euo", "pipefail", "-c", bash_cmd], capture_output=True, text=True, check=True)
    assert proc.stdout.strip() == "ts_quoted_key|up_single_key|caller_wins|UNSET"


def test_filelock_posix_and_simulated_windows(tmp_path, monkeypatch):
    # Static check: no unconditional top-level `import fcntl` in jobs.py or bundle_db.py.
    for path in (REPO_ROOT / "engine" / "ppservice" / "jobs.py", REPO_ROOT / "engine" / "pp" / "bundle_db.py"):
        assert "import fcntl" not in path.read_text(encoding="utf-8")

    lock_path = tmp_path / "test.lock"
    with open(lock_path, "w+") as f1, open(lock_path, "w+") as f2:
        filelock_util.lock_file(f1, nonblocking=True)
        with pytest.raises(OSError):
            filelock_util.lock_file(f2, nonblocking=True)
        filelock_util.unlock_file(f1)
        filelock_util.lock_file(f2, nonblocking=True)
        filelock_util.unlock_file(f2)

    # Simulate Windows platform (no fcntl, msvcrt present).
    calls = []

    class FakeMsvcrt:
        LK_LOCK = 1
        LK_NBLCK = 2
        LK_UNLCK = 3

        @staticmethod
        def locking(fd, mode, nbytes):
            calls.append((mode, nbytes))
            if mode == FakeMsvcrt.LK_NBLCK and calls.count((FakeMsvcrt.LK_NBLCK, 1)) > 1:
                raise OSError("locked")

    monkeypatch.setattr(filelock_util, "_fcntl", None)
    monkeypatch.setattr(filelock_util, "_msvcrt", FakeMsvcrt)
    win_lock = tmp_path / "win.lock"
    with open(win_lock, "w+") as fh:
        filelock_util.lock_file(fh, nonblocking=True)
        with pytest.raises(OSError):
            filelock_util.lock_file(fh, nonblocking=True)
        filelock_util.unlock_file(fh)
    assert calls == [(2, 1), (2, 1), (3, 1)]


def test_helper_scripts_import_cleanly_without_pythonpath():
    """scripts/build_roster_1m.py and scripts/export_visit.py must import without PYTHONPATH."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    for name in ("build_roster_1m.py", "export_visit.py"):
        script = REPO_ROOT / "engine" / "scripts" / name
        code = f"import importlib.util; s = importlib.util.spec_from_file_location('m', r'{script}'); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); assert hasattr(m, 'main')"
        proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True)
        assert proc.returncode == 0, f"{name} failed: {proc.stderr}"


def test_synthetic_real_names_are_stripped_from_public_and_deep_outputs():
    person = {
        "uuid": "u1", "panel": "rep", "name": "민시온", "sex": "여자", "age": 35,
        "province": "서울", "district": "서울-강남구", "occupation": "사무원",
        "education_level": "4년제 대학교", "marital_status": "미혼",
        "family_type": "혼자 거주", "housing_type": "아파트",
        "persona": "민시온 씨는 ...", "professional_persona": "직장인",
    }
    assert export.public_person(person)["name"] == ""
    assert deep._who(person)["name"] == ""
