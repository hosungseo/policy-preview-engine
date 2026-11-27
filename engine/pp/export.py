"""Assemble a run into bundle.json, validate the honesty rules, write it for the web."""
from __future__ import annotations

import json
from pathlib import Path

from . import config, prompts, segment
from .jev_panel import LENSES, METHODS


class ExportError(RuntimeError):
    pass


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _person_jev(row: dict | None) -> dict | None:
    if not row:
        return None
    out = {k: row[k] for k in ("stance", "reserve", "direct", "comment")}
    if row.get("pos_oppose"):
        sid, prob = max(row["pos_oppose"].items(), key=lambda kv: (kv[1], kv[0]))
        out["oppose_most"] = {"segment_id": sid, "p": prob}
    if "understand" in row:
        out["understand"] = row["understand"]
    if row.get("methods"):
        key, prob = max(row["methods"].items(), key=lambda kv: (kv[1], kv[0]))
        out["best_method"] = {"key": key, "label": METHODS[key][0] if key in METHODS else key, "p": prob}
    return out


def public_person(p: dict, jev_row: dict | None = None) -> dict:
    return {
        "jev": _person_jev(jev_row),
        "uuid": p["uuid"], "panel": p["panel"], "found_by": p.get("found_by", []), "name": "",
        "sex": p["sex"], "age": p["age"], "age_band": config.age_band(int(p["age"])),
        "province": config.PROVINCE_DISPLAY.get(p["province"], p["province"]),
        "region": config.REGION_OF[p["province"]], "district": p["district"],
        "occupation": p["occupation"], "occupation_major": p.get("occupation_major", "무직·기타"),
        "education_level": p["education_level"], "marital_status": p["marital_status"],
        "family_type": p["family_type"], "family": config.family_bucket(p["family_type"]),
        "housing_type": p["housing_type"],
        "summary": prompts.clip(p.get("persona"), 240), "detail": prompts.clip(p.get("professional_persona"), 280),
        "similar": p.get("similar", []),
    }


def _with_consistency(reactions: list[dict], analysis: dict) -> list[dict]:
    """Attach Jev's reading of each reason and flag answers whose own support label disagrees with it."""
    cons = analysis.get("consistency") or {}
    by_rid = cons.get("by_rid") or {}
    if not by_rid:
        return reactions
    return [{**r, "jev_read": by_rid[r["rid"]], "flagged": abs(by_rid[r["rid"]] - r["support"]) >= cons["threshold"]}
            if r["rid"] in by_rid else r for r in reactions]


def _optional(path: Path) -> dict | None:
    data = _read(path) if path.exists() else None
    return data if data and data.get("available", True) else None


def _with_lenses(reactions: list[dict], review: dict | None, threshold: float = 0.5) -> list[dict]:
    """Lenses a reaction carries (Jev probability >= threshold), strongest first."""
    tags = (review or {}).get("lenses") or {}
    if not tags:
        return reactions
    return [{**r, "lenses": sorted((k for k, v in tags.get(r["rid"], {}).items() if v >= threshold),
                                   key=lambda k: -tags[r["rid"]][k])} for r in reactions]


def _with_reads(hearing: dict, debrief: dict | None) -> dict:
    if not debrief:
        return hearing
    return {**hearing, "reads": debrief["reads"],
            "trajectories": {k: debrief[k] for k in ("participants", "movers", "counts", "move") if k in debrief}}


def assemble(run_dir: Path) -> dict:
    policy = _read(run_dir / "policy.json")
    analysis = _read(run_dir / "analysis.json")
    review = _optional(run_dir / "review.json")
    population = _read(config.population_json()) if config.population_json().exists() else {}
    jev_rows = {}
    if (run_dir / "jev.jsonl").exists():
        for line in (run_dir / "jev.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                jev_rows[row["uuid"]] = row
    return {
        "id": policy["id"], "title": policy["title"], "kind": policy["kind"], "agency": policy.get("agency", ""),
        "source": policy.get("source", {}), "policy_text": policy["text"],
        "segments": _read(run_dir / "segments.json"), "population": population,
        "panel": _read(run_dir / "panel.json"),
        "selection": _optional(run_dir / "selection.json"),
        "personas": [public_person(p, jev_rows.get(p["uuid"])) for p in _read(run_dir / "personas.json")],
        "reactions": _with_lenses(_with_consistency(_read(run_dir / "reactions.json"), analysis), review),
        "analysis": analysis, "clarity": _optional(run_dir / "clarity.json"),
        "hearing": _with_reads(_read(run_dir / "hearing.json"), _optional(run_dir / "debrief.json")),
        "plan": _read(run_dir / "plan.json"),
        "meta": _read(run_dir / "meta.json"),
    }


def validate_bundle(b: dict, allow_mock: bool = False) -> list[str]:
    errors: list[str] = []
    if b["meta"].get("provider") == "mock" and not allow_mock:
        errors.append("mock provider bundle cannot be exported to the public site")
    panel_of = {p["uuid"]: p["panel"] for p in b["personas"]}
    rids: dict[str, dict] = {}
    for r in b["reactions"]:
        if r["uuid"] not in panel_of:
            errors.append(f"reaction {r['rid']} for unknown persona")
        if r["rid"] in rids:
            errors.append(f"duplicate rid {r['rid']}")
        rids[r["rid"]] = r
        if r.get("quote_verified") and segment.locate(r.get("trigger_quote", ""), b["policy_text"]) is None:
            errors.append(f"verified quote not found in policy ({r['rid']})")
    reasons = {r["reason"] for r in b["reactions"]}
    suggestions = {r.get("suggestion") for r in b["reactions"] if r.get("suggestion")}
    analysis = b["analysis"]
    for issue in analysis["issues"]:
        for member in issue["member_ids"]:
            if member not in rids:
                errors.append(f"issue {issue['id']} has unknown member {member}")
        for quote in issue["quotes"]:
            if rids.get(quote["rid"], {}).get("reason") != quote["text"]:
                errors.append(f"issue {issue['id']} quote not verbatim ({quote['rid']})")
    for item in (analysis.get("alternatives") or {}).get("items", []):
        if item.get("source_example") not in suggestions:
            errors.append(f"amendment source not verbatim: {item.get('title', '')[:20]}")
    for group in analysis["outreach"]:
        for quote in group.get("sample_quotes", []):
            if quote not in reasons:
                errors.append(f"outreach {group['group']} quote not verbatim")
    for item in analysis.get("suggestions", []) + b["plan"].get("suggestions", []):
        if item["example"] not in suggestions:
            errors.append(f"suggestion example not verbatim: {item['example'][:20]}")
    for item in b["plan"]["issues"]:
        if item.get("quote") and item["quote"] not in reasons:
            errors.append(f"plan issue quote not verbatim: {item['title']}")
    for r in b["reactions"]:
        unknown = [k for k in r.get("lenses", []) if k not in LENSES]
        if unknown:
            errors.append(f"unknown lens {unknown[0]} on {r['rid']}")
    turns = b["hearing"].get("turns", [])
    for read in b["hearing"].get("reads", []):
        i = read.get("index", -1)
        if not (0 <= i < len(turns)) or turns[i]["speaker"] == "사회자" or turns[i]["speaker"] != read.get("speaker"):
            errors.append(f"hearing read {i} does not match a participant's speech")
    participants = set(b["hearing"]["participants"])
    if not participants <= set(panel_of):
        errors.append("hearing participant not in personas")
    for turn in b["hearing"]["turns"]:
        if turn["speaker"] != "사회자" and turn["speaker"] not in participants:
            errors.append(f"unknown speaker {turn['speaker']}")
    for person in b["personas"]:
        for other in person.get("similar", []):
            if other not in panel_of:
                errors.append(f"similar {other} not in personas")
    rep_n = sum(1 for r in b["reactions"] if panel_of.get(r["uuid"]) == "rep")
    if analysis["overall"]["n"] != rep_n:
        errors.append(f"overall n {analysis['overall']['n']} != representative reactions {rep_n}")
    return errors


def summary(b: dict) -> dict:
    panel_of = {p["uuid"]: p["panel"] for p in b["personas"]}
    issues = b["analysis"]["issues"]
    return {
        "id": b["id"], "title": b["title"], "kind": b["kind"], "agency": b.get("agency", ""),
        "created_at": b["meta"]["created_at"],
        "n_rep": sum(1 for r in b["reactions"] if panel_of.get(r["uuid"]) == "rep"),
        "n_aff": sum(1 for r in b["reactions"] if panel_of.get(r["uuid"]) == "aff"),
        "n_issues": len(issues), "top_issue": issues[0]["title"] if issues else "",
        "seconds": round(sum(s.get("seconds", 0) for s in b["meta"].get("stages", [])), 1),
    }


def write(bundle: dict, allow_mock: bool = False) -> Path:
    errors = validate_bundle(bundle, allow_mock=allow_mock)
    if errors:
        raise ExportError("; ".join(errors[:10]))
    is_mock = bundle["meta"].get("provider") == "mock"
    target = config.web_dev_runs_dir() if is_mock else config.web_runs_dir()
    target.mkdir(parents=True, exist_ok=True)
    dest = target / f"{bundle['id']}.json"
    dest.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    index_path = target / "index.json"
    index = _read(index_path) if index_path.exists() else []
    index = [e for e in index if e["id"] != bundle["id"]] + [summary(bundle)]
    index.sort(key=lambda e: e["created_at"], reverse=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return dest
