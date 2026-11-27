"""Pilot: does giving Jev each person's (statistically assigned) tenure and local housing-market facts change reactions?

  HF_HOME=../data/hf ../.venv/bin/python scripts/pilot_housing_context.py [--workers 24] [--analyze-only]

Sample (2,000 of the housing series panel): everyone in Seoul's four high-price districts (강남·서초·송파·용산) and six
lower-price districts (노원·도봉·강북·금천·중랑·관악), plus a seeded random draw from everyone else. Four measures,
the "measure alone" condition, asked twice: with the housing block (context) and with a same-shape block without
facts (placebo). The full run's answers for the same people are the baseline. Answers append to
runs/series-housing-ctxpilot/ and the script resumes; --analyze-only prints and saves the comparison.
"""
import argparse
import json
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))
from pp import config, housing_context, jev, personas, series, series_questions  # noqa: E402

MEASURES = ["2025-06-27-loan-cap", "2025-10-15-stabilization", "2026-01-29-urban-supply", "2026-08-03-tax"]
CONDITIONS = ("context", "placebo")
HIGH = {"서울-강남구", "서울-서초구", "서울-송파구", "서울-용산구"}
LOW = {"서울-노원구", "서울-도봉구", "서울-강북구", "서울-금천구", "서울-중랑구", "서울-관악구"}
N_TOTAL = 2000
SEED = 7


def group_of(district: str) -> str:
    return "서울 고가 4구" if district in HIGH else "서울 중저가 6구" if district in LOW else "그 밖"


def sample(panel: list[dict]) -> list[dict]:
    seoul = [p for p in panel if p["district"] in HIGH | LOW]
    rest = [p for p in panel if p["district"] not in HIGH | LOW]
    rng = random.Random(SEED)
    return seoul + rng.sample(rest, N_TOTAL - len(seoul))


def _mean(xs: list[float]) -> float:
    return round(statistics.mean(xs), 4) if xs else float("nan")


def summarise(rows: list[dict]) -> dict:
    favor = [r["favor"] for r in rows]
    oppose = [r["stance_probs"][0] + r["stance_probs"][1] for r in rows]
    neutral = [r["stance_probs"][2] for r in rows]
    f, o = _mean(favor), _mean(oppose)
    return {"n": len(rows), "favor": f, "neutral": _mean(neutral), "oppose": o,
            "decided_support": round(f / (f + o), 4) if f + o else float("nan"),
            "harm": _mean([r["housing"]["h_harm"] for r in rows]), "home": _mean([r["housing"]["h_home"] for r in rows])}


def analyse(run_dir: Path, people: list[dict], assigned: dict) -> dict:
    base_dir = config.runs_dir() / "series-housing" / "answers"
    out: dict = {}
    for mid in MEASURES:
        conds = {"baseline": series.read_rows(base_dir / f"{mid}__alone.jsonl")}
        for c in CONDITIONS:
            conds[c] = series.read_rows(run_dir / "answers" / f"{mid}__{c}.jsonl")
        by: dict = defaultdict(lambda: defaultdict(list))
        for p in people:
            keys = [("group", group_of(p["district"])), ("tenure", assigned[p["uuid"]]["tenure"]), ("all", "전체")]
            for cond, rows in conds.items():
                r = rows.get(p["uuid"])
                if r:
                    for k in keys:
                        by[k][cond].append(r)
        out[mid] = {f"{k[0]}:{k[1]}": {cond: summarise(rs) for cond, rs in v.items()} for k, v in by.items()}
    return out


def print_tables(res: dict) -> None:
    for mid, cells in res.items():
        print(f"\n## {mid}")
        print(f"{'집단':22} {'조건':9} {'n':>5} {'찬성쪽':>6} {'중립':>6} {'반대쪽':>6} {'결정중찬성':>9} {'불리함':>6}")
        for key in sorted(cells, key=lambda k: (k.split(':')[0] != 'all', k)):
            for cond in ("baseline", "placebo", "context"):
                s = cells[key].get(cond)
                if s:
                    print(f"{key:22} {cond:9} {s['n']:5d} {s['favor']*100:6.1f} {s['neutral']*100:6.1f} {s['oppose']*100:6.1f} "
                          f"{s['decided_support']*100:9.1f} {s['harm']*100:6.1f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--analyze-only", action="store_true")
    args = ap.parse_args()
    run_dir = config.runs_dir() / "series-housing-ctxpilot"
    (run_dir / "answers").mkdir(parents=True, exist_ok=True)
    s = series.load_series(ENGINE / "series" / "housing.json")
    measures = {m["id"]: m for m in s["measures"]}
    panel = json.loads((config.runs_dir() / "series-housing" / "panel.json").read_text(encoding="utf-8"))["people"]
    assigned = {p["uuid"]: housing_context.assign(p) for p in panel}
    (config.runs_dir() / "series-housing" / "tenure_assigned.json").write_text(
        json.dumps(assigned, ensure_ascii=False), encoding="utf-8")
    light = sample(panel)
    if not args.analyze_only:
        market = json.loads((ENGINE / "series" / "official" / "housing_market.json").read_text(encoding="utf-8"))
        conn = personas.connect()
        full = {r["uuid"]: r for r in personas.fetch(conn, personas.ids_for_uuids(conn, [p["uuid"] for p in light]))}
        people = [full[p["uuid"]] for p in light]
        jev.reset_usage()
        usage: dict = {}
        for mid in MEASURES:
            m = measures[mid]
            segs = series_questions.measure_segments(m["text"], m.get("provisions"))
            qs = series_questions.measure_questions(segs)
            for cond in CONDITIONS:
                def make_state(p, m=m, mid=mid, cond=cond):
                    block = (housing_context.housing_block(p, assigned[p["uuid"]], mid, market) if cond == "context"
                             else housing_context.PLACEBO)
                    return {**series.measure_state(m, p, []), "housing": block}
                started = time.time()
                rows, failures = series.ask_all(people, run_dir / "answers" / f"{mid}__{cond}.jsonl", make_state, qs,
                                                lambda a, sg=segs: series_questions.summarize_measure(a, sg),
                                                label=cond, workers=args.workers)
                print(f"[pilot] {m['short']} {cond}: {len(rows)}/{len(people)}, {len(failures)} failed, "
                      f"{time.time() - started:.0f}s", flush=True)
        for label, u in jev.usage().items():
            usage[label] = {**u, "cost_usd": jev.cost_usd(u["input_tokens"])}
        prev = json.loads((run_dir / "meta.json").read_text(encoding="utf-8")) if (run_dir / "meta.json").exists() else {}
        for label, u in usage.items():
            acc = prev.setdefault("jev_usage", {}).setdefault(label, {"calls": 0, "input_tokens": 0, "cached": 0})
            acc["calls"] += u["calls"]
            acc["input_tokens"] += u["input_tokens"]
            acc["cached"] += u.get("cached", 0)
            acc["cost_usd"] = jev.cost_usd(acc["input_tokens"])
        (run_dir / "meta.json").write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
        print("usage:", json.dumps(prev.get("jev_usage"), ensure_ascii=False))
    res = analyse(run_dir, light, assigned)
    (run_dir / "analysis.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print_tables(res)


if __name__ == "__main__":
    main()
