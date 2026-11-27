"""Survey-to-deep identity and split counts on an invented 170-person bundle (no 20k data needed)."""
import gzip
import json

from pp import config, prompts, provenance
from ppservice.survey import panel
from conftest import make_rows
from test_svc_deep import api, drain_deep, survey_run  # noqa: F401
from test_svc_survey import H, login


def test_small_bundle_deep_preserves_revision_and_panel_counts(api, tmp_path, monkeypatch):  # noqa: F811
    bundle = tmp_path / "small-panel.jsonl.gz"
    rows = [{"uuid": p["uuid"], "sex": p["sex"], "age": p["age"], "age_band": config.age_band(p["age"]),
             "province": p["province"], "capital": p["province"] in {"서울", "경기", "인천"},
             "profile": prompts.persona_profile(p)} for p in make_rows()]
    bundle.write_bytes(gzip.compress(('\n'.join(json.dumps(p, ensure_ascii=False) for p in rows) + '\n').encode()))
    provenance.write_metadata(bundle, {"source_repo": "invented-fixture", "source_revision": "c" * 40,
                                       "revision_status": "user_supplied"})
    monkeypatch.setenv("PP_PANEL_BUNDLE", str(bundle))
    monkeypatch.setenv("PP_PANEL_ADDONS", "off")
    original_load = panel.load
    monkeypatch.setattr(panel, "BUNDLE", bundle)
    monkeypatch.setattr(panel, "load", lambda addons=None: original_load(bundle, addons=addons))
    app, codes = api
    client = login(app, codes, "a@x.go.kr")
    _, rid = survey_run(client, app)
    assert client.post(f"/api/runs/{rid}/deep", headers=H).status_code == 202
    drain_deep(app)
    deep = client.get(f"/api/runs/{rid}/deep").json()["deep"]
    assert deep["status"] == "succeeded", deep
    result = deep["result"]
    assert result["source_revision"] == "c" * 40
    assert result["panel_version"] == provenance.artifact(bundle, compressed=True)["panel_version"]
    full = client.get(f"/api/runs/{rid}/deep/bundle").json()["bundle"]
    assert full["meta"]["source_revision"] == result["source_revision"]
    assert full["meta"]["panel_version"] == result["panel_version"]
    assert all(it["n"] == it["by_panel"]["rep"]["n"] for it in result["issues"])
    assert all(it["by_panel"]["aff"]["caution"] == "전체 비율로 읽지 않음" for it in result["issues"])
    assert full["analysis"]["overall"]["n"] == 24
    assert full["analysis"]["overall_aff"]["n"] == 6
