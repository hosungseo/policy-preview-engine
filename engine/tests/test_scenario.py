import json
from copy import deepcopy
from pathlib import Path

import pytest

from pp import __main__ as cli
from pp.scenario import SCHEMA_PATH, validate_scenario

EXAMPLE = Path(__file__).resolve().parents[1] / "scenarios/examples/offline-help-v1.json"


@pytest.fixture
def card():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def reviewed(card):
    card = deepcopy(card)
    card["guidance"]["placeholder"] = False
    for doc in card["reference_documents"]:
        doc.update(placeholder=False, review_status="reviewed")
    return card


def test_example_is_valid_but_cannot_be_treated_as_reviewed_evidence(card):
    result = validate_scenario(card)
    assert result["status"] == "deferred" and result["note"] == "판정 보류"
    assert len(result["reasons"]) == 2
    assert validate_scenario(reviewed(card))["status"] == "ready"


@pytest.mark.parametrize("field", json.loads(SCHEMA_PATH.read_text())["required"])
def test_missing_required_field_is_rejected(card, field):
    del card[field]
    with pytest.raises(ValueError, match="missing"):
        validate_scenario(card)


@pytest.mark.parametrize("field,value", [
    ("schema_version", "2"), ("persona_uuid", "not-a-uuid"), ("source_revision", "main"),
    ("as_of", "2026-02-30"), ("as_of", "20261127"), ("question", "  "),
    ("observed_fields", []), ("unknown_fields", ["income", "income"]),
    ("reference_documents", []), ("expected", []), ("forbidden", []),
])
def test_structural_errors(card, field, value):
    card[field] = value
    with pytest.raises(ValueError):
        validate_scenario(card)


@pytest.mark.parametrize("field", ["observed_fields", "assumed_context"])
def test_unknown_fields_cannot_be_silently_filled_in(card, field):
    card[field]["income"] = "임의 확정"
    with pytest.raises(ValueError, match="disjoint"):
        validate_scenario(card)


def test_assumptions_cannot_masquerade_as_observations(card):
    card["observed_fields"]["has_smartphone"] = False
    with pytest.raises(ValueError, match="disjoint"):
        validate_scenario(card)


@pytest.mark.parametrize("field", ["guidance", "reference_documents"])
def test_changed_text_must_change_its_hash(card, field):
    doc = card[field] if field == "guidance" else card[field][0]
    doc["text"] += "수정했습니다."
    with pytest.raises(ValueError, match="sha256 mismatch"):
        validate_scenario(card)


@pytest.mark.parametrize("field", ["expected", "forbidden"])
def test_behavior_cannot_reference_nonexistent_evidence(card, field):
    card[field][0]["reference_ids"] = ["nonexistent"]
    with pytest.raises(ValueError, match="unknown reference IDs"):
        validate_scenario(card)


@pytest.mark.parametrize("change", [
    {"placeholder": True}, {"review_status": "unreviewed"}, {"jurisdiction": "다른시"},
    {"effective_from": "2026-11-28"}, {"effective_until": "2026-11-26"},
])
def test_uncertain_or_inapplicable_evidence_defers_judgement(card, change):
    card = reviewed(card)
    card["reference_documents"][0].update(change)
    assert validate_scenario(card)["status"] == "deferred"


def test_duplicate_ids_and_inverted_dates_are_rejected(card):
    duplicate = deepcopy(card)
    duplicate["reference_documents"] *= 2
    with pytest.raises(ValueError, match="duplicate reference"):
        validate_scenario(duplicate)
    duplicate = deepcopy(card)
    duplicate["forbidden"][0]["id"] = duplicate["expected"][0]["id"]
    with pytest.raises(ValueError, match="duplicate behavior"):
        validate_scenario(duplicate)
    card["reference_documents"][0]["effective_until"] = "2025-12-31"
    with pytest.raises(ValueError, match="precedes"):
        validate_scenario(card)


def test_cli_checks_locally_and_reports_deferred(capsys):
    cli.main(["validate-scenario", str(EXAMPLE)])
    assert json.loads(capsys.readouterr().out)["status"] == "deferred"


def test_cli_rejects_invalid_card_before_any_run_is_started(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    with pytest.raises(SystemExit) as exc:
        cli.main(["validate-scenario", str(bad)])
    assert exc.value.code == 2
