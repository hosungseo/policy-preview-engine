"""Does life context make synthetic answers track real group differences? Same 3,000 people, two profiles.

  PP_JEV_PROVIDER=api ../.venv/bin/python scripts/eval_life_context.py run      # ~24k Jev calls, resumable
  ../.venv/bin/python scripts/eval_life_context.py report

Arms: `orig` = the service profile as is; `ctx` = the same profile plus pp/life_context.block(). Four questions from
통계청 사회조사 (2024 health, 2025 others) whose published tables break answers down by monthly household income,
tenure, smoking and disability. Both arms are grouped by the *assigned* attributes, so `orig` shows how much of a
group difference the original personas already carry and `ctx` how much the added context brings. The official
numbers are survey estimates for real people; the comparison is diagnostic, not a calibration.
"""
import gzip
import json
import os
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from pp import jev, life_context  # noqa: E402
from ppservice.survey import panel  # noqa: E402
from ppservice.survey.run import jev_questions, normalize, option_keys, state_for  # noqa: E402

OUT = ENGINE.parent / "runs" / "life-context-eval"
OFFICIAL = OUT / "official.json"
CONTEXT = ENGINE / "ppservice" / "data" / "persona-context" / "life-context-v2.jsonl.gz"
N, SEED = 3000, 2024
NEUTRAL = "(이 문항은 특정 정책에 관한 것이 아닙니다.)"
QUESTIONS = {
    "class": {"tbl": "DT_1SSSP232R", "year": "2025", "title": "계층의식",
              "question": "귀하는 우리 사회에서 귀하 자신이 어느 계층에 속한다고 생각하십니까?",
              "options": ["상층", "중간층", "하층"], "items": ["T10", "T20", "T30"]},
    "income_sat": {"tbl": "DT_1SSIC050R", "year": "2025", "title": "소득 만족도",
                   "question": "귀하는 현재 자신의 소득에 대해 어느 정도 만족하십니까?",
                   "options": ["매우 만족", "약간 만족", "보통", "약간 불만족", "매우 불만족"],
                   "items": ["T21", "T22", "T30", "T41", "T42"]},
    "health": {"tbl": "DT_1SSHE010R", "year": "2024", "title": "건강평가",
               "question": "귀하는 평소 자신의 건강이 어떻다고 생각하십니까?",
               "options": ["매우 좋다", "좋은 편이다", "보통이다", "나쁜 편이다", "매우 나쁘다"],
               "items": ["T21", "T22", "T30", "T41", "T42"]},
    "donation": {"tbl": "DT_1SSSP060R", "year": "2025", "title": "기부 경험",
                 "question": "귀하는 지난 1년 동안 현금이나 물품을 기부한 적이 있습니까?",
                 "options": ["기부한 적 있음", "기부한 적 없음"], "items": ["T10", "T20"]},
}
ARMS = ("orig", "ctx")
# Official monthly household-income rows -> three groups comparable with the assigned annual bands
MONTHLY_GROUP = {"100만원 미만": "low", "100∼200만원 미만": "low", "200∼300만원 미만": "low",
                 "300∼400만원 미만": "mid", "400∼500만원 미만": "mid", "500∼600만원 미만": "mid", "600만원 이상": "high"}
ANNUAL_GROUP = {"lt10": "low", "10_30": "low", "30_50": "mid", "50_70": "mid", "70_100": "high", "ge100": "high"}
TENURE_ROWS = {"자기 집": "own", "전세": "jeonse", "보증금 있는 월세": "monthly", "보증금 없는 월세": "monthly"}


def people_and_context() -> tuple[list[dict], dict]:
    everyone, _ = panel.load(addons="off")
    people = panel.sample(everyone, N, SEED)
    rows = [json.loads(x) for x in gzip.decompress(CONTEXT.read_bytes()).decode("utf-8").splitlines() if x]
    return people, {r["uuid"]: r for r in rows}


ADDONS = os.environ.get("LCE_ADDONS", "all")  # which add-ons the ctx arm gets
HISTORY = os.environ.get("LCE_HISTORY") == "1"  # ctx arm also gets life-history change lines (pp/life_history.py)
HISTORY_FILE = ENGINE / "ppservice" / "data" / "persona-context" / "life-history-v1.jsonl.gz"
_history: dict = {}


def history_for(uid: str) -> dict:
    if not _history and HISTORY:
        _history.update({r["uuid"]: r for r in (json.loads(x) for x in gzip.decompress(
            HISTORY_FILE.read_bytes()).decode("utf-8").splitlines() if x)})
    return _history.get(uid, {})
TAG = os.environ.get("LCE_TAG", "")  # a variant's ctx answers go to answers-<tag>.jsonl


def profile(arm: str, person: dict, ctx: dict) -> dict:
    if arm == "orig":
        return person
    extra = life_context.block(ctx[person["uuid"]], ADDONS)
    if HISTORY:
        from pp import life_history
        lines = life_history.history_lines(history_for(person["uuid"]))
        if lines:
            extra = (extra + "\n" if extra else "") + "\n".join(lines)
    return {**person, "profile": person["profile"] + ("\n\n" + extra if extra else "")}


def answer_paths() -> list[Path]:
    return [OUT / "answers.jsonl"] + ([OUT / f"answers-{TAG}.jsonl"] if TAG else [])


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    people, ctx = people_and_context()
    path = OUT / (f"answers-{TAG}.jsonl" if TAG else "answers.jsonl")
    done = set()
    for f in {OUT / "answers.jsonl", path}:
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if f == path or r["arm"] == "orig":
                    done.add((r["q"], r["arm"], r["uuid"]))
    tasks = [(q, arm, p) for q in QUESTIONS for arm in ARMS for p in people if (q, arm, p["uuid"]) not in done]
    print(f"{len(tasks)} calls to make ({len(done)} done)", flush=True)
    lock = threading.Lock()
    jev.reset_usage()

    def one(task) -> None:
        q, arm, p = task
        spec = {**{k: QUESTIONS[q][k] for k in ("title", "question", "options")}, "policy_text": NEUTRAL}
        keys = option_keys(spec["options"])
        try:
            out = jev.evaluate(state_for("main", spec, profile(arm, p, ctx)), jev_questions(spec["options"]),
                               label="life-context-eval")
            probs = normalize(out["answers"]["q"]["probabilities"], keys)
        except Exception as e:  # recorded as missing; a rerun fills it
            print("fail", q, arm, p["uuid"], type(e).__name__, e, flush=True)
            return
        with lock, path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"q": q, "arm": arm, "uuid": p["uuid"], "probs": probs}) + "\n")

    with ThreadPoolExecutor(max_workers=24) as pool:
        list(pool.map(one, tasks))
    usage = jev.usage()
    print(json.dumps(usage, ensure_ascii=False), flush=True)
    (OUT / "usage.json").write_text(json.dumps(usage, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def fetch_official() -> dict:
    sys.path.insert(0, str(ENGINE / "scripts"))
    from fetch_persona_context import fetch  # noqa: E402
    out = {}
    for q, spec in QUESTIONS.items():
        rows = fetch("101", spec["tbl"], "F", objL1="00", objL2="ALL", startPrdDe=spec["year"], endPrdDe=spec["year"])
        cells: dict = defaultdict(dict)
        for r in rows:
            try:
                cells[r["C2_NM"].replace("\xa0", "").replace(" ", "")][r["ITM_ID"]] = float(r["DT"])
            except (TypeError, ValueError):
                pass
        out[q] = {"source": f"통계청 사회조사 {spec['year']}, KOSIS 101 {spec['tbl']}", "rows": cells}
    OUT.mkdir(parents=True, exist_ok=True)
    OFFICIAL.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def official_dist(cells: dict, row: str, items: list[str]) -> list[float] | None:
    c = cells.get(row.replace(" ", ""))
    if not c or any(i not in c for i in items):
        return None
    total = sum(c[i] for i in items)
    return [c[i] / total for i in items] if total else None


def age_row(age: int, q: str) -> str:
    if age < 30:
        return "20∼29세" if q in ("health", "donation") else "19∼29세"
    if age >= 60:
        return "60세이상" if q == "health" else "60세 이상"
    return f"{age // 10 * 10}∼{age // 10 * 10 + 9}세"


def report() -> None:
    official = json.loads(OFFICIAL.read_text(encoding="utf-8")) if OFFICIAL.exists() else fetch_official()
    people, ctx = people_and_context()
    by_uuid = {p["uuid"]: p for p in people}
    answers: dict = defaultdict(dict)
    for f in answer_paths():
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if TAG and f.name == "answers.jsonl" and r["arm"] == "ctx":
                continue  # a variant replaces the default ctx arm
            answers[(r["q"], r["arm"])][r["uuid"]] = r["probs"]

    def panel_mean(q: str, arm: str, members) -> list[float] | None:
        rows = [answers[(q, arm)][u] for u in members if u in answers[(q, arm)]]
        if len(rows) < 30:
            return None
        k = len(rows[0])
        return [sum(r[i] for r in rows) / len(rows) for i in range(k)]

    def groups(q: str) -> dict:
        """{group label: (official row name or list of rows, member uuids)}"""
        g: dict = {"전체": (["계"], [p["uuid"] for p in people])}
        for sex in ("남자", "여자"):
            g[sex] = ([sex], [p["uuid"] for p in people if p["sex"] == sex])
        ages: dict = defaultdict(list)
        for p in people:
            ages[age_row(int(p["age"]), q)].append(p["uuid"])
        for row, members in ages.items():
            g[row] = ([row], members)
        inc: dict = defaultdict(list)
        for p in people:
            band = ctx[p["uuid"]].get("income")
            if band:
                inc[ANNUAL_GROUP[band]].append(p["uuid"])
        for grp, label in (("low", "소득 하(월 300만 미만)"), ("mid", "소득 중(월 300~600만)"), ("high", "소득 상(월 600만 이상)")):
            g[label] = ([r for r, x in MONTHLY_GROUP.items() if x == grp], inc[grp])
        if q == "class":
            for row, t in (("자기 집", "own"), ("전세", "jeonse")):
                g["점유 " + row] = ([row], [p["uuid"] for p in people if ctx[p["uuid"]]["tenure"] == t])
            g["점유 월세"] = (["보증금 있는 월세", "보증금 없는 월세"],
                            [p["uuid"] for p in people if ctx[p["uuid"]]["tenure"] == "monthly"])
        if q == "health":
            for row, val in (("피운다", True), ("피우지 않는다", False)):
                g["흡연 " + row] = ([row], [p["uuid"] for p in people if ctx[p["uuid"]].get("smoking") is val])
            for row, val in (("장애인 복지카드 있음", True), ("장애인 복지카드 없음", False)):
                g[row] = ([row], [p["uuid"] for p in people if ctx[p["uuid"]].get("disability") is val])
        return g

    result = {}
    for q, spec in QUESTIONS.items():
        cells = official[q]["rows"]
        rows_out = []
        for label, (orows, members) in groups(q).items():
            dists = [d for d in (official_dist(cells, r, spec["items"]) for r in orows) if d]
            if not dists:
                continue
            off = [sum(d[i] for d in dists) / len(dists) for i in range(len(spec["items"]))]
            row = {"group": label, "n": len(members), "official": [round(x, 4) for x in off]}
            for arm in ARMS:
                m = panel_mean(q, arm, members)
                if m:
                    row[arm] = [round(x, 4) for x in m]
                    row[arm + "_mae"] = round(sum(abs(a - b) for a, b in zip(m, off)) / len(off), 4)
            rows_out.append(row)
        result[q] = {"title": spec["title"], "options": spec["options"], "source": official[q]["source"],
                     "rows": rows_out, "gaps": gaps(q, rows_out)}
    (OUT / (f"report-{TAG}.json" if TAG else "report.json")).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for q, r in result.items():
        print(f"\n## {r['title']} {r['options']}")
        for row in r["rows"]:
            print(f"  {row['group']:<22} n={row['n']:<5} 실측 {fmt(row['official'])} | 원본 {fmt(row.get('orig'))} "
                  f"({row.get('orig_mae', '-')}) | 보강 {fmt(row.get('ctx'))} ({row.get('ctx_mae', '-')})")
        for g in r["gaps"]:
            print("  격차", g)


# Group contrasts on one headline share: (question, option index set, high group, low group)
CONTRASTS = {
    "class": [((2,), "소득 하(월 300만 미만)", "소득 상(월 600만 이상)"), ((2,), "점유 월세", "점유 자기 집"),
              ((0, 1), "점유 자기 집", "점유 월세")],
    "income_sat": [((3, 4), "소득 하(월 300만 미만)", "소득 상(월 600만 이상)")],
    "health": [((3, 4), "장애인 복지카드 있음", "장애인 복지카드 없음"), ((0, 1), "흡연 피우지 않는다", "흡연 피운다"),
               ((0, 1), "소득 상(월 600만 이상)", "소득 하(월 300만 미만)")],
    "donation": [((0,), "소득 상(월 600만 이상)", "소득 하(월 300만 미만)")],
}


def gaps(q: str, rows: list[dict]) -> list[dict]:
    by = {r["group"]: r for r in rows}
    out = []
    for idx, a, b in CONTRASTS.get(q, []):
        if a not in by or b not in by:
            continue
        item = {"share": "+".join(QUESTIONS[q]["options"][i] for i in idx), "groups": f"{a} − {b}"}
        for src in ("official", *ARMS):
            if src in by[a] and src in by[b]:
                item[src] = round(100 * (sum(by[a][src][i] for i in idx) - sum(by[b][src][i] for i in idx)), 1)
        out.append(item)
    return out


def fmt(xs) -> str:
    return "-" if not xs else "/".join(f"{100 * x:.0f}" for x in xs)


if __name__ == "__main__":
    {"run": run, "report": report, "official": fetch_official}[sys.argv[1]]()
