"""Field verification log (현장 확인 회수 기록) schema, I/O, PII guard, and hit/miss reconciliation.

Closes the Sim-to-Real loop (gemini.md #1/#8):
  - Records what policy officers actually heard in the field (CSV or JSON).
  - Blocks personal identifiers (RRN / mobile phone numbers) from entering logs.
  - Compares field findings against predicted groups and blockers (from visit.view(), plan.json,
    bundle.json, or a custom prediction JSON) to produce a hit / false-positive / miss / unchecked table.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from pathlib import Path

SCHEMA_VERSION = "1.0"
VALID_ITEM_KINDS = ("group", "blocker", "missing_party", "unpredicted")
VALID_OUTCOMES = ("hit", "false_positive", "miss", "unverified")
VALID_ACTIONS = ("revised", "planned", "no_change", "pending")

OUTCOME_LABEL = {
    "hit": "적중",
    "false_positive": "오탐(현장 불일치)",
    "miss": "놓침(현장 신규 발견)",
    "unverified": "미확인",
}
ITEM_KIND_LABEL = {
    "group": "예측 집단",
    "blocker": "예측 막힘·쟁점",
    "missing_party": "명단 외 당사자",
    "unpredicted": "예측 밖 현장 발견",
}
ACTION_LABEL = {
    "revised": "수정 반영",
    "planned": "수정 예정",
    "no_change": "변경 없음",
    "pending": "검토 중",
}

CSV_COLUMNS = [
    "entry_id",
    "visit_date",
    "group_label",
    "venue",
    "participant_count",
    "predicted_ref",
    "item_kind",
    "outcome",
    "field_finding",
    "action_taken",
    "review_minutes",
    "notes",
]

# Reuse the same PII detection patterns as ppservice/survey/lint.py (kept self-contained here).
RRN_RE = re.compile(r"(?<!\d)\d{6}\s*-\s*[1-8]\d{6}(?!\d)")
PHONE_RE = re.compile(r"(?<!\d)01[016789]\s*-?\s*\d{3,4}\s*-?\s*\d{4}(?!\d)")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class FieldLogError(ValueError):
    """Raised when a field verification log fails schema or PII validation."""


def _norm_key(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _check_pii(entry_id: str, entry: dict) -> list[str]:
    errs: list[str] = []
    for field in ("group_label", "venue", "predicted_ref", "field_finding", "notes"):
        val = str(entry.get(field) or "")
        if RRN_RE.search(val) or PHONE_RE.search(val):
            errs.append(f"{entry_id}: '{field}'에 주민등록번호 또는 휴대전화 번호로 보이는 값이 있습니다. 삭제해 주세요.")
    return errs


def validate_entry(entry: dict, idx: int = 1) -> list[str]:
    """Validate one field verification entry; returns a list of error strings (empty if valid)."""
    errs: list[str] = []
    eid = str(entry.get("entry_id") or f"row-{idx}").strip()
    if not str(entry.get("entry_id") or "").strip():
        errs.append(f"{eid}: entry_id가 비어 있습니다.")

    vdate = str(entry.get("visit_date") or "").strip()
    if not DATE_RE.match(vdate):
        errs.append(f"{eid}: visit_date는 YYYY-MM-DD 형식이어야 합니다(현재: {vdate!r}).")
    else:
        try:
            date.fromisoformat(vdate)
        except ValueError:
            errs.append(f"{eid}: visit_date가 올바른 날짜가 아닙니다({vdate!r}).")

    if not str(entry.get("group_label") or "").strip():
        errs.append(f"{eid}: group_label(만난 집단)이 비어 있습니다.")
    if not str(entry.get("venue") or "").strip():
        errs.append(f"{eid}: venue(만난 장소 유형)가 비어 있습니다.")

    pc = entry.get("participant_count")
    if isinstance(pc, bool) or not isinstance(pc, int) or pc < 1:
        errs.append(f"{eid}: participant_count는 1 이상의 정수여야 합니다.")

    kind = entry.get("item_kind")
    if kind not in VALID_ITEM_KINDS:
        errs.append(f"{eid}: item_kind는 {VALID_ITEM_KINDS} 중 하나여야 합니다(현재: {kind!r}).")

    outcome = entry.get("outcome")
    if outcome not in VALID_OUTCOMES:
        errs.append(f"{eid}: outcome은 {VALID_OUTCOMES} 중 하나여야 합니다(현재: {outcome!r}).")

    if not str(entry.get("field_finding") or "").strip():
        errs.append(f"{eid}: field_finding(현장에서 들은 내용)이 비어 있습니다.")

    action = entry.get("action_taken")
    if action not in VALID_ACTIONS:
        errs.append(f"{eid}: action_taken은 {VALID_ACTIONS} 중 하나여야 합니다(현재: {action!r}).")

    rmin = entry.get("review_minutes")
    if rmin is not None and (isinstance(rmin, bool) or not isinstance(rmin, int) or rmin < 0):
        errs.append(f"{eid}: review_minutes는 0 이상의 정수 또는 null이어야 합니다.")

    # Logical consistency: a 'hit' or 'false_positive' should name what prediction was tested
    pred_ref = str(entry.get("predicted_ref") or "").strip()
    if outcome in ("hit", "false_positive") and not pred_ref:
        errs.append(f"{eid}: outcome이 '{outcome}'일 때는 predicted_ref(비교한 예측 항목)를 적어야 합니다.")

    errs.extend(_check_pii(eid, entry))
    return errs


def validate_log(doc: dict) -> list[str]:
    """Validate a complete field verification log document."""
    errs: list[str] = []
    if not isinstance(doc, dict):
        return ["현장 기록 최상위 객체가 dict여야 합니다."]
    if str(doc.get("schema_version") or "") != SCHEMA_VERSION:
        errs.append(f"schema_version은 '{SCHEMA_VERSION}'이어야 합니다.")
    if not str(doc.get("policy_title") or "").strip():
        errs.append("policy_title이 비어 있습니다.")
    entries = doc.get("entries")
    if not isinstance(entries, list):
        errs.append("entries는 배열이어야 합니다.")
        return errs
    seen_ids: set[str] = set()
    for i, e in enumerate(entries, start=1):
        if not isinstance(e, dict):
            errs.append(f"row-{i}: 항목이 객체가 아닙니다.")
            continue
        eid = str(e.get("entry_id") or "").strip()
        if eid and eid in seen_ids:
            errs.append(f"{eid}: 중복된 entry_id입니다.")
        seen_ids.add(eid)
        errs.extend(validate_entry(e, i))
    return errs


def _parse_int(raw: str | int | None, *, allow_none: bool = False) -> int | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None if allow_none else -1
    if isinstance(raw, bool):
        return -1
    if isinstance(raw, int):
        return raw
    try:
        return int(str(raw).strip())
    except ValueError:
        return -1


def load_field_log(path: Path, *, policy_title: str = "", run_id: str = "") -> dict:
    """Load and validate a field verification log from `.json` or `.csv`."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        doc = json.loads(path.read_text(encoding="utf-8"))
        if policy_title and not doc.get("policy_title"):
            doc["policy_title"] = policy_title
        if run_id and not doc.get("run_id"):
            doc["run_id"] = run_id
    elif suffix == ".csv":
        text = path.read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise FieldLogError("CSV 헤더가 비어 있습니다.")
        missing_cols = [c for c in CSV_COLUMNS if c not in reader.fieldnames]
        if missing_cols:
            raise FieldLogError(f"CSV 필수 열이 빠져 있습니다: {', '.join(missing_cols)}")
        entries: list[dict] = []
        for row in reader:
            if not any((v or "").strip() for v in row.values()):
                continue
            entries.append(
                {
                    "entry_id": (row.get("entry_id") or "").strip(),
                    "visit_date": (row.get("visit_date") or "").strip(),
                    "group_label": (row.get("group_label") or "").strip(),
                    "venue": (row.get("venue") or "").strip(),
                    "participant_count": _parse_int(row.get("participant_count")),
                    "predicted_ref": (row.get("predicted_ref") or "").strip() or None,
                    "item_kind": (row.get("item_kind") or "").strip(),
                    "outcome": (row.get("outcome") or "").strip(),
                    "field_finding": (row.get("field_finding") or "").strip(),
                    "action_taken": (row.get("action_taken") or "").strip(),
                    "review_minutes": _parse_int(row.get("review_minutes"), allow_none=True),
                    "notes": (row.get("notes") or "").strip(),
                }
            )
        doc = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id or path.stem,
            "policy_title": policy_title or path.stem,
            "entries": entries,
        }
    else:
        raise FieldLogError(f"지원하지 않는 파일 형식입니다({suffix}). .csv 또는 .json 파일을 사용하세요.")

    errors = validate_log(doc)
    if errors:
        raise FieldLogError("; ".join(errors))
    return doc


def extract_predictions(raw: dict) -> dict:
    """Normalize predicted groups and blockers from visit.view(), plan.json, bundle.json, or generic JSON."""
    items: list[dict] = []
    policy_title = raw.get("policy_title") or raw.get("title") or ""
    run_id = raw.get("run_id") or raw.get("id") or ""

    # Unwrap bundle.json if needed
    plan = raw.get("plan") if isinstance(raw.get("plan"), dict) else raw
    if isinstance(plan.get("overview"), dict):
        policy_title = policy_title or plan["overview"].get("title", "")

    # 1. Generic format: predicted_groups / predicted_blockers / predictions
    for idx, g in enumerate(raw.get("predicted_groups") or [], start=1):
        if isinstance(g, str):
            items.append({"ref": f"grp-{idx}", "kind": "group", "label": g, "detail": ""})
        elif isinstance(g, dict):
            label = str(g.get("label") or g.get("group") or g.get("name") or "")
            items.append(
                {
                    "ref": str(g.get("id") or g.get("ref") or label),
                    "kind": "group",
                    "label": label,
                    "detail": str(g.get("detail") or g.get("say") or ""),
                }
            )
    for idx, b in enumerate(raw.get("predicted_blockers") or [], start=1):
        if isinstance(b, str):
            items.append({"ref": f"blk-{idx}", "kind": "blocker", "label": b, "detail": ""})
        elif isinstance(b, dict):
            label = str(b.get("title") or b.get("label") or "")
            items.append(
                {
                    "ref": str(b.get("id") or b.get("ref") or label),
                    "kind": "blocker",
                    "label": label,
                    "detail": str(b.get("summary") or b.get("detail") or ""),
                }
            )

    # 2. visit.view() format: cards + missing
    for idx, card in enumerate(raw.get("cards") or [], start=1):
        group = str(card.get("group") or "")
        items.append(
            {
                "ref": str(card.get("id") or f"card-{idx}:{group}"),
                "kind": "group",
                "label": group,
                "detail": str(card.get("say") or card.get("title") or ""),
                "venues": list(card.get("venues") or []),
            }
        )
    for idx, m in enumerate(raw.get("missing") or [], start=1):
        if m.get("party"):
            who = str(m.get("who") or "")
            items.append(
                {
                    "ref": f"missing-{idx}:{who}",
                    "kind": "missing_party",
                    "label": who,
                    "detail": str(m.get("route") or ""),
                }
            )

    # 3. plan.json / analysis.json format: issues (blockers) + outreach (groups)
    for it in plan.get("issues") or []:
        items.append(
            {
                "ref": str(it.get("id") or it.get("title") or ""),
                "kind": "blocker",
                "label": str(it.get("title") or it.get("id") or ""),
                "detail": str(it.get("summary") or ""),
            }
        )
    for idx, o in enumerate(plan.get("outreach") or [], start=1):
        group = str(o.get("group") or "")
        items.append(
            {
                "ref": f"outreach-{idx}:{group}",
                "kind": "group",
                "label": group,
                "detail": str((o.get("suggestion") or {}).get("why") or ""),
                "venues": list(o.get("channels") or []),
            }
        )

    # Deduplicate by normalized (kind, label) while keeping order
    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for it in items:
        key = (it["kind"], _norm_key(it["label"]))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    return {"run_id": run_id, "policy_title": policy_title, "items": deduped}


def reconcile(predictions_raw: dict, field_log: dict) -> dict:
    """Compare predicted blockers/groups against field verification entries.

    Returns a complete hit / false-positive / miss / unchecked reconciliation report.
    """
    preds = extract_predictions(predictions_raw)
    pred_items = preds["items"]
    entries = field_log.get("entries") or []

    # Index predictions by both exact ref and normalized label
    by_ref: dict[str, int] = {}
    by_label: dict[str, int] = {}
    for idx, p in enumerate(pred_items):
        if p.get("ref"):
            by_ref[_norm_key(p["ref"])] = idx
        by_label[_norm_key(p["label"])] = idx

    matched_entries: dict[int, list[dict]] = {i: [] for i in range(len(pred_items))}
    misses: list[dict] = []
    unmatched_non_miss: list[dict] = []

    for e in entries:
        outcome = e["outcome"]
        kind = e["item_kind"]
        if outcome == "miss" or kind == "unpredicted":
            misses.append(e)
            continue

        pred_idx = None
        ref_key = _norm_key(e.get("predicted_ref"))
        grp_key = _norm_key(e.get("group_label"))
        if ref_key and ref_key in by_ref:
            pred_idx = by_ref[ref_key]
        elif ref_key and ref_key in by_label:
            pred_idx = by_label[ref_key]
        elif grp_key and grp_key in by_label:
            pred_idx = by_label[grp_key]

        if pred_idx is not None:
            matched_entries[pred_idx].append(e)
        else:
            unmatched_non_miss.append(e)

    # Summarize each prediction row
    prediction_rows: list[dict] = []
    hits = 0
    false_positives = 0
    unverified_preds = 0
    unchecked_preds = 0

    for idx, p in enumerate(pred_items):
        linked = matched_entries[idx]
        if not linked:
            status = "unchecked"
            unchecked_preds += 1
            prediction_rows.append(
                {
                    "ref": p["ref"],
                    "kind": p["kind"],
                    "label": p["label"],
                    "detail": p.get("detail", ""),
                    "status": status,
                    "status_label": "미방문(기록 없음)",
                    "entries": [],
                    "participants": 0,
                    "findings": [],
                    "actions": [],
                }
            )
            continue

        outcomes = [x["outcome"] for x in linked]
        if "hit" in outcomes:
            status = "hit"
            hits += 1
        elif "false_positive" in outcomes:
            status = "false_positive"
            false_positives += 1
        else:
            status = "unverified"
            unverified_preds += 1

        prediction_rows.append(
            {
                "ref": p["ref"],
                "kind": p["kind"],
                "label": p["label"],
                "detail": p.get("detail", ""),
                "status": status,
                "status_label": OUTCOME_LABEL[status],
                "entries": [x["entry_id"] for x in linked],
                "participants": sum(int(x["participant_count"]) for x in linked),
                "findings": [x["field_finding"] for x in linked],
                "actions": [x["action_taken"] for x in linked],
            }
        )

    # Include any non-miss entries whose predicted_ref wasn't in the loaded predictions file
    for e in unmatched_non_miss:
        status = e["outcome"]
        if status == "hit":
            hits += 1
        elif status == "false_positive":
            false_positives += 1
        else:
            unverified_preds += 1
        prediction_rows.append(
            {
                "ref": e.get("predicted_ref") or e["entry_id"],
                "kind": e["item_kind"],
                "label": e.get("predicted_ref") or e["group_label"],
                "detail": "(예측 파일 외 추가 참조)",
                "status": status,
                "status_label": OUTCOME_LABEL[status],
                "entries": [e["entry_id"]],
                "participants": int(e["participant_count"]),
                "findings": [e["field_finding"]],
                "actions": [e["action_taken"]],
            }
        )

    checked_decided = hits + false_positives
    predicted_total = len(pred_items)
    checked_from_preds = sum(1 for r in prediction_rows[:predicted_total] if r["status"] in ("hit", "false_positive"))
    hit_rate = round(hits / checked_decided, 4) if checked_decided else None
    coverage = round(checked_from_preds / predicted_total, 4) if predicted_total else None

    revised_count = sum(1 for e in entries if e["action_taken"] == "revised")
    planned_count = sum(1 for e in entries if e["action_taken"] == "planned")
    total_participants = sum(int(e["participant_count"]) for e in entries)
    total_review_minutes = sum(int(e["review_minutes"]) for e in entries if e.get("review_minutes") is not None)

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": field_log.get("run_id") or preds["run_id"],
        "policy_title": field_log.get("policy_title") or preds["policy_title"],
        "summary": {
            "predicted_total": predicted_total,
            "checked_decided": checked_decided,
            "unchecked_predictions": unchecked_preds,
            "unverified_predictions": unverified_preds,
            "hits": hits,
            "false_positives": false_positives,
            "misses": len(misses),
            "hit_rate_checked": hit_rate,
            "prediction_coverage": coverage,
            "revised_count": revised_count,
            "planned_count": planned_count,
            "total_entries": len(entries),
            "total_participants": total_participants,
            "total_review_minutes": total_review_minutes,
        },
        "predictions": prediction_rows,
        "misses": [
            {
                "entry_id": m["entry_id"],
                "visit_date": m["visit_date"],
                "group_label": m["group_label"],
                "venue": m["venue"],
                "participant_count": m["participant_count"],
                "field_finding": m["field_finding"],
                "action_taken": m["action_taken"],
                "action_label": ACTION_LABEL[m["action_taken"]],
                "notes": m.get("notes", ""),
            }
            for m in misses
        ],
    }


def render_reconciliation_markdown(report: dict) -> str:
    """Render the hit/miss reconciliation table as plain-Korean Markdown."""
    s = report["summary"]
    hit_rate_str = f"{round(s['hit_rate_checked'] * 100, 1)}%" if s["hit_rate_checked"] is not None else "산출 불가(확인 0건)"
    cov_str = f"{round(s['prediction_coverage'] * 100, 1)}%" if s["prediction_coverage"] is not None else "-"

    lines = [
        f"# 현장 확인 회수 대조표 — {report['policy_title'] or '(정책명 미기재)'}",
        "",
        f"- **실행 ID**: `{report['run_id'] or '미기재'}`",
        f"- **실제 현장 면담 인원**: {s['total_participants']:,}명 (기록 {s['total_entries']}건)",
        f"- **담당자 현장 확인·검토 시간**: {s['total_review_minutes']:,}분",
        "",
        "## 1. 적중·오탐·놓침 요약",
        "",
        "| 지표 | 값 | 설명 |",
        "|---|---:|---|",
        f"| 미리 예측한 항목 수 | {s['predicted_total']}건 | 합성 미리보기가 짚은 집단·막힘 수 |",
        f"| 현장 확인 완료(적중+오탐) | {s['checked_decided']}건 (확인율 {cov_str}) | 실제 방문·면담으로 판정한 항목 수 |",
        f"| 적중 (Hit) | {s['hits']}건 | 예측한 막힘·집단이 현장에서 확인됨 |",
        f"| 오탐 (False Positive) | {s['false_positives']}건 | 예측했으나 현장에서 확인되지 않음 |",
        f"| 확인 항목 대비 적중률 | {hit_rate_str} | 적중 ÷ (적중 + 오탐) |",
        f"| 미방문·미확인 예측 | {s['unchecked_predictions'] + s['unverified_predictions']}건 | 아직 확인 기록이 없거나 미확인인 예측 |",
        f"| 놓침 (Miss · 현장 신규 발견) | {s['misses']}건 | 합성이 못 짚었지만 현장에서 새로 발견함 |",
        f"| 실제 문안·정책 수정 반영 | {s['revised_count']}건 (예정 {s['planned_count']}건) | 현장 확인 뒤 실제 수정으로 이어진 건수 |",
        "",
        "## 2. 예측 항목별 적중·오탐 대조표",
        "",
        "| 구분 | 예측 항목 | 현장 판정 | 실제 들은 내용 | 면담 인원 | 수정 여부 |",
        "|---|---|---|---|---:|---|",
    ]
    if report["predictions"]:
        for r in report["predictions"]:
            kind_lbl = ITEM_KIND_LABEL.get(r["kind"], r["kind"])
            finding = " / ".join(r["findings"]) if r["findings"] else "-"
            action = ", ".join(ACTION_LABEL.get(a, a) for a in r["actions"]) if r["actions"] else "-"
            lines.append(
                f"| {kind_lbl} | {r['label']} | {r['status_label']} | {finding} | {r['participants']}명 | {action} |"
            )
    else:
        lines.append("| - | 예측 항목 없음 | - | - | 0명 | - |")

    lines += [
        "",
        "## 3. 합성이 놓친 현장 발견 목록 (Miss)",
        "",
        "| 기록 ID | 날짜 | 만난 집단 | 장소 유형 | 실제 들은 내용 | 면담 인원 | 수정 여부 |",
        "|---|---|---|---|---|---:|---|",
    ]
    if report["misses"]:
        for m in report["misses"]:
            lines.append(
                f"| {m['entry_id']} | {m['visit_date']} | {m['group_label']} | {m['venue']} | "
                f"{m['field_finding']} | {m['participant_count']}명 | {m['action_label']} |"
            )
    else:
        lines.append("| - | - | 합성이 놓친 추가 발견 기록 없음 | - | - | 0명 | - |")

    lines.append("")
    return "\n".join(lines)


def build_template_entries(predictions_raw: dict | None = None) -> list[dict]:
    """Create starter rows for CSV/JSON templates, optionally seeded from a predictions file."""
    today_iso = date.today().isoformat()
    if predictions_raw:
        preds = extract_predictions(predictions_raw)["items"]
        rows = []
        for idx, p in enumerate(preds, start=1):
            venues = p.get("venues") or []
            rows.append(
                {
                    "entry_id": f"fv-{idx:03d}",
                    "visit_date": today_iso,
                    "group_label": p["label"],
                    "venue": venues[0] if venues else "행정복지센터",
                    "participant_count": 1,
                    "predicted_ref": p["ref"],
                    "item_kind": p["kind"],
                    "outcome": "unverified",
                    "field_finding": "(현장에서 실제로 들은 핵심 내용을 요약해 적습니다. 실명·연락처 금지)",
                    "action_taken": "pending",
                    "review_minutes": 30,
                    "notes": p.get("detail", ""),
                }
            )
        rows.append(
            {
                "entry_id": f"fv-{len(rows) + 1:03d}",
                "visit_date": today_iso,
                "group_label": "(합성이 놓친 집단 또는 막힘)",
                "venue": "현장 간담회",
                "participant_count": 1,
                "predicted_ref": "",
                "item_kind": "unpredicted",
                "outcome": "miss",
                "field_finding": "(미리보기에는 없었으나 현장에서 새로 확인한 막힘을 적습니다)",
                "action_taken": "pending",
                "review_minutes": 30,
                "notes": "",
            }
        )
        return rows

    return [
        {
            "entry_id": "fv-001",
            "visit_date": today_iso,
            "group_label": "70세 이상",
            "venue": "경로당·노인복지관",
            "participant_count": 5,
            "predicted_ref": "card-1:70세 이상",
            "item_kind": "group",
            "outcome": "hit",
            "field_finding": "온라인 신청 절차 안내가 작아 주민센터 방문 신청 가능 여부를 묻는 의견이 많았습니다.",
            "action_taken": "revised",
            "review_minutes": 60,
            "notes": "안내문 첫머리에 방문 창구 안내 문구 추가",
        },
        {
            "entry_id": "fv-002",
            "visit_date": today_iso,
            "group_label": "대리 신청 보호자",
            "venue": "행정복지센터",
            "participant_count": 3,
            "predicted_ref": "",
            "item_kind": "unpredicted",
            "outcome": "miss",
            "field_finding": "가족이 대신 신청할 때 필요한 위임장 서류 안내가 빠져 있었습니다.",
            "action_taken": "planned",
            "review_minutes": 40,
            "notes": "합성 미리보기에서 놓친 절차 막힘",
        },
    ]


def write_template_csv(path: Path, predictions_raw: dict | None = None) -> Path:
    rows = build_template_entries(predictions_raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in CSV_COLUMNS})
    return path


def write_template_json(
    path: Path,
    predictions_raw: dict | None = None,
    *,
    run_id: str = "example-run",
    policy_title: str = "예시 정책 안내문",
) -> Path:
    rows = build_template_entries(predictions_raw)
    if predictions_raw:
        meta = extract_predictions(predictions_raw)
        run_id = meta["run_id"] or run_id
        policy_title = meta["policy_title"] or policy_title
    doc = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "policy_title": policy_title,
        "recorded_at": date.today().isoformat(),
        "entries": [
            {**r, "predicted_ref": r["predicted_ref"] or None}
            for r in rows
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
