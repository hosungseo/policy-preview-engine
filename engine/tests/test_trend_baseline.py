"""Publication-time leakage, exact cohort matching, and CLI isolation checks."""
import copy
import json

import pytest

from pp import cli, trend_baseline as trend


def row(year, probabilities, **updates):
    return dict(question_id="q", group="20대", definition_id="q-v1-age20-29",
                year=year, fieldwork_end=f"{year}-05-30", released_at=f"{year}-11-20",
                source_url="https://kosis.kr/example", options=["찬성", "기타"],
                probabilities=probabilities, **updates)


def predict(rows, **kwargs):
    return trend.predict(rows, question_id="q", group="20대", definition_id="q-v1-age20-29",
                         target_year=2024, as_of="2023-12-31", **kwargs)


def test_future_and_unpublished_rows_cannot_change_prediction():
    rows = [row(2020, [.4, .6]), row(2022, [.5, .5])]
    expected = predict(rows, method="linear")
    future = row(2024, [float("nan"), 0])
    late = row(2023, [0, 1])
    late["released_at"] = "2024-01-01"
    assert predict(rows + [future, late], method="linear") == expected
    assert expected["probabilities"] == pytest.approx([.6, .4])
    assert expected["history_years"] == [2020, 2022]


def test_exact_definition_and_group_and_publication_boundary():
    source = row(2022, [.3, .7])
    other = row(2023, [1, 0])
    other["definition_id"] = "different-population"
    assert predict([source, other])["probabilities"] == [.3, .7]
    source["released_at"] = "2023-12-31"
    assert predict([source])["history_years"] == [2022]
    source["released_at"] = "2024-01-01"
    with pytest.raises(ValueError, match="no_available_history"):
        predict([source])


@pytest.mark.parametrize("values", [[float("nan"), 0], [float("inf"), 0], [-.1, 1.1], [.1, .1], [True, 0], [.1]])
def test_bad_history_is_rejected(values):
    with pytest.raises(ValueError):
        predict([row(2022, values)])


def test_duplicates_and_changed_options_and_insufficient_history():
    source = row(2022, [.2, .8])
    with pytest.raises(ValueError, match="duplicate_year"):
        predict([source, source])
    older = row(2020, [.3, .7])
    older["options"] = ["기타", "찬성"]
    with pytest.raises(ValueError, match="option_definition_changed"):
        predict([older, source])
    with pytest.raises(ValueError, match="two_history"):
        predict([source], method="linear")


def test_clipping_returns_a_distribution_without_mutating_history():
    rows = [row(2020, [.9, .1]), row(2022, [.1, .9])]
    before = copy.deepcopy(rows)
    assert predict(rows, method="linear")["probabilities"] == [0, 1]
    assert rows == before
    assert trend.distribution_error([.3, .7], [.2, .8])["mae_pp"] == pytest.approx(10)


def test_cli_runs_without_model_or_policy_input(tmp_path, monkeypatch, capsys):
    history = tmp_path / "history.json"
    history.write_text(json.dumps([row(2022, [.5, .5])]))
    monkeypatch.setattr(cli.service, "estimate", lambda *a, **kw: pytest.fail("model policy flow entered"))
    args = ["trend", "--history", str(history), "--question-id", "q", "--group", "20대",
            "--definition-id", "q-v1-age20-29", "--target-year", "2024", "--as-of", "2023-12-31"]
    assert cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["model_calls"] == 0
    assert "공개 집계" in result["notice"]
    history.write_text("{}")
    assert cli.main(args) == 2
    assert "과거 집계" in capsys.readouterr().err


def test_dates_and_scope_are_required():
    source = row(2022, [.2, .8])
    source["fieldwork_end"] = "2023-05-01"
    with pytest.raises(ValueError, match="invalid_observation_date"):
        predict([source])
    with pytest.raises(ValueError, match="target_must_be_after"):
        trend.predict([], question_id="q", group="g", definition_id="d", target_year=2024, as_of="2024-01-01")
