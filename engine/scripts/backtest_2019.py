"""Backtest of the world model: start the panel in 2019, roll it to 2023 on the kernels a forecaster had in 2019,
ask Jev the 2019 and the 2023 persona, and compare with the published 사회조사 (계층의식, 소득 만족도: 2019, 2021,
2023, 2025) — levels and, above all, the 2019 -> 2023 change.

  ../.venv/bin/python scripts/backtest_2019.py build     # projection + dynamics checks -> backtest-forecast.json(l)
  PP_JEV_PROVIDER=api ../.venv/bin/python scripts/backtest_2019.py run
  ../.venv/bin/python scripts/backtest_2019.py report

Arms: b2019 (the person as of 2019: age - 6, 2019 states), b2023 (the same person rolled forward to 2023), and
y2025 reused from eval_life_context answers-core-v3 (the person as of 2025). The 2025 add-on lines (housing, debt, ...)
stay in every arm — the test is the change between arms, not a clean 2019 persona.
"""
import gzip
import json
import re
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

ENGINE = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "scripts"))

from pp import jev, life_context, life_history as lh  # noqa: E402
from ppservice.survey.run import jev_questions, normalize, option_keys, state_for  # noqa: E402
import eval_life_context as base  # noqa: E402
import eval_future as fut  # noqa: E402
from build_life_context import load_people  # noqa: E402
import build_life_history as blh  # noqa: E402

START, END = 2019, 2023
OUT = fut.OUT
FORECAST = OUT / "backtest-forecast.jsonl.gz"
SUMMARY = OUT / "backtest-forecast.json"
ANSWERS = OUT / "backtest-answers.jsonl"
OFFICIAL = OUT / "official-series.json"
ARMS = ("b2019", "b2023", "b2019a", "b2023a", "b2023s")  # "a": income amounts with the change since 2019; "s": the
                                                          # 2023 amount alone (does Jev read a higher nominal level?)
SEED = 2025
ATTRS = ("province", "marital", "working", "income_q", "smoking")


def load_history() -> dict:
    hist = {}
    for x in gzip.decompress(fut.HISTORY.read_bytes()).decode().splitlines():
        r = json.loads(x)
        hist[r.pop("uuid")] = {k: {int(y): v for y, v in d.items()} for k, d in r.items() if isinstance(d, dict)}
    return hist


def state_at(hist: dict, p: dict, year: int) -> dict:
    """The person's state in `year` from the simulated history (what project() would return for that year)."""
    h = hist.get(p["uuid"], {})
    return {"alive": True, "age": lh.age_at(p, year), "province": (h.get("residence") or {}).get(year, p["province"]),
            "marital": (h.get("marital") or {}).get(year), "working": (h.get("employed") or {}).get(year),
            "smoking": (h.get("smoking") or {}).get(year),
            # the history ends in 2024: the 2025 reference state carries the 2024 quintile
            "income_q": (h.get("income_q") or {}).get(year) or (h.get("income_q") or {}).get(year - 1),
            "income_amt": (h.get("income_amt") or {}).get(year) or (h.get("income_amt") or {}).get(year - 1)}


def margins(states: list[dict]) -> dict:
    live = [s for s in states if s["alive"]]
    qs = [s["income_q"] for s in live if s["income_q"]]
    smk = [s["smoking"] for s in live if s["smoking"] is not None]
    amts = [s["income_amt"] for s in live if s.get("income_amt")]
    return {"n": len(live), "mean_amount": round(sum(amts) / len(amts), 1) if amts else None,
            "median_amount": round(sorted(amts)[len(amts) // 2], 1) if amts else None, "mean_age": round(sum(s["age"] for s in live) / len(live), 1),
            "working_share": round(sum(1 for s in live if s["working"]) / len(live), 4),
            "quintile_shares": [round(qs.count(i) / max(1, len(qs)), 4) for i in range(1, 6)],
            "smoking_share": round(sum(smk) / max(1, len(smk)), 4),
            "married_share": round(sum(1 for s in live if s["marital"] == lh.MARRIED) / len(live), 4),
            "capital_share": round(sum(1 for s in live if s["province"] in ("서울", "인천", "경기")) / len(live), 4)}


def build() -> None:
    people = load_people()
    ctx = {r["uuid"]: r for r in (json.loads(x) for x in gzip.decompress(blh.CONTEXT.read_bytes()).decode().splitlines() if x)}
    hist = load_history()
    mob = life_context.tables()["history_income_mobility"]
    stayers = {int(k): v for k, v in json.loads(
        (lh.OUT / "report-history-v1.json").read_text(encoding="utf-8"))["income"]["stayers"].items()}
    employed = lh.simulate_employment(people, SEED)
    flags: dict = {}
    lh.simulate_income(people, mob, stayers, SEED, employed=employed, flags=flags)
    adults = [p for p in people if lh.age_at(p, START) >= 19]
    fc = lh.project(adults, hist, ctx, flags, SEED, until=END, base_year=START)
    # the history is anchored to the published yearly figures, so its 2023 margins stand in for "what happened"
    realized = {y: margins([state_at(hist, p, y) for p in adults]) for y in range(START, END + 1)}
    summary = {"start": START, "end": END, "n_adults_2019": len(adults),
               "forecast": fc["years"], "realized_history": realized,
               "note": "forecast = frozen 2019 kernels (2018 income transitions/margins, 2019 migration, marriage, "
                       "divorce, employment and district smoking rates); realized = the simulated history, which is "
                       "re-fitted each year to the published figures"}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    by_uid = {p["uuid"]: p for p in adults}
    FORECAST.write_bytes(gzip.compress("\n".join(
        json.dumps({"uuid": u, "y2019": state_at(hist, by_uid[u], START), "y2023": v}, ensure_ascii=False)
        for u, v in fc["people"].items()).encode("utf-8"), mtime=0))
    for y in (START, END):
        f, r = fc["years"][y], realized[y]
        print(y, "forecast", {k: f[k] for k in ("working_share", "quintile_shares", "smoking_share", "married_share",
                                                 "capital_share")})
        print(y, "realized", {k: r[k] for k in ("working_share", "quintile_shares", "smoking_share", "married_share",
                                                 "capital_share")})


def load_forecast() -> dict:
    return {r["uuid"]: r["y2023"] for r in (json.loads(x) for x in gzip.decompress(FORECAST.read_bytes()).decode().splitlines())}


STATUS_KO, PROVINCE_KO = fut.STATUS_KO, fut.PROVINCE_KO


def block(year: int, ref: dict, then: dict, since: dict | None, amounts: bool = False) -> str:
    """Lines for the person in `year`. `ref` is the 2025 state the profile text describes; a state that differs from
    it is stated; `since` (the 2019 state) adds the change since then for the 2023 arm. With `amounts` the income
    line carries the nominal annual amount (one economic line per profile)."""
    prov = lambda x: PROVINCE_KO.get(x, x)  # noqa: E731
    lines = [f"[{year}년 시뮬레이션 — 공공통계의 연간 변화 확률로 이 사람의 {year}년 모습을 가정한 것이며 사실이 아님]",
             f"- 지금은 {year}년이고, 이 사람은 {then['age']}세입니다."]
    if then["province"] != ref["province"]:
        lines.append(f"- 거주: {year}년 현재 {prov(then['province'])}에 살고 있음")
    if since and since["province"] != then["province"]:
        lines.append(f"- 이사: {START}년 이후 {prov(since['province'])}에서 {prov(then['province'])}(으)로 옮김")
    if then["marital"] and then["marital"] != ref.get("marital"):
        lines.append(f"- 혼인: {year}년 현재 {STATUS_KO[then['marital']]}")
    if since and since["marital"] and then["marital"] and since["marital"] != then["marital"]:
        lines.append(f"- 혼인: {START}년 {STATUS_KO[since['marital']]} → {year}년 {STATUS_KO[then['marital']]}")
    if then["working"] is not None and then["working"] != ref.get("working"):
        lines.append(f"- 일: {year}년 현재 " + ("일하고 있음" if then["working"] else "일하지 않음"))
    if since and since["working"] is not None and then["working"] is not None and since["working"] != then["working"]:
        lines.append(f"- 일: {START}년 이후 " + ("일을 시작함" if then["working"] else "일을 그만둠"))
    q = then["income_q"]
    a0, a1 = (since or {}).get("income_amt"), then.get("income_amt")
    tag = lambda k: {1: "(하위 20%)", 5: "(상위 20%)"}.get(k, "")  # noqa: E731
    if amounts and a1 and q:
        if since and a0 and since["income_q"] and amounts != "state":
            lines.append(f"- 개인 근로·사업소득: {START}년 연 {lh.fmt_amount(a0)}{tag(since['income_q'])} → {year}년 연 "
                         f"{lh.fmt_amount(a1)}{tag(q)} ({(a1 / a0 - 1) * 100:+.0f}%)")
        else:
            lines.append(f"- 개인 근로·사업소득: {year}년 연 {lh.fmt_amount(a1)}{tag(q)}")
    elif since and since["income_q"] and q and since["income_q"] != q:
        lines.append(f"- 개인 근로·사업소득 분위: {START}년 {since['income_q']}분위 → {year}년 {q}분위")
    elif q in (1, 5):
        lines.append(f"- 개인 근로·사업소득: {year}년 {'하위' if q == 1 else '상위'} 20%")
    if then["smoking"] is not None and then["smoking"] != ref.get("smoking"):
        lines.append(f"- 흡연: {year}년 현재 " + ("담배를 피움" if then["smoking"] else "담배를 피우지 않음"))
    return "\n".join(lines)


def profile(person: dict, ctx: dict, year: int, ref: dict, then: dict, since: dict | None, amounts: bool = False) -> dict:
    text = re.sub(r"(성별·나이: [^,\n]+, )\d+세", lambda m: f"{m.group(1)}{then['age']}세", person["profile"])
    addons = fut.CORE if then.get("working") else fut.CORE.replace(",work", "")
    extra = life_context.block(ctx, addons)
    return {**person, "age": then["age"], "profile": text + "\n\n" + extra + "\n" + block(year, ref, then, since, amounts)}


def setup():
    people, ctx = base.people_and_context()
    hist, fc = load_history(), load_forecast()
    people = [p for p in people if p["uuid"] in fc and fc[p["uuid"]]["alive"]]
    s19 = {p["uuid"]: state_at(hist, p, START) for p in people}
    ref = {p["uuid"]: state_at(hist, p, lh.BASE_YEAR) for p in people}
    for u in ref:  # 2025 smoking is the assigned attribute, not a history entry
        ref[u]["smoking"] = ctx[u].get("smoking")
    return people, ctx, fc, s19, ref


def run() -> None:
    people, ctx, fc, s19, ref = setup()
    done = set()
    if ANSWERS.exists():
        for line in ANSWERS.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done.add((r["q"], r["arm"], r["uuid"]))
    tasks = [(q, arm, p) for q in fut.QUESTIONS for arm in ARMS for p in people if (q, arm, p["uuid"]) not in done]
    print(f"{len(tasks)} calls ({len(done)} done)", flush=True)
    lock = threading.Lock()
    jev.reset_usage()

    def one(task) -> None:
        q, arm, p = task
        u = p["uuid"]
        amounts = "state" if arm.endswith("s") else arm.endswith("a")
        prof = (profile(p, ctx[u], START, ref[u], s19[u], None, amounts) if arm.startswith("b2019")
                else profile(p, ctx[u], END, ref[u], fc[u], s19[u], amounts))
        spec = {**{k: fut.QUESTIONS[q][k] for k in ("title", "question", "options")}, "policy_text": base.NEUTRAL}
        keys = option_keys(spec["options"])
        try:
            out = jev.evaluate(state_for("main", spec, prof), jev_questions(spec["options"]), label="backtest-2019")
            probs = normalize(out["answers"]["q"]["probabilities"], keys)
        except Exception as e:  # recorded as missing; a rerun fills it
            print("fail", q, arm, u, type(e).__name__, e, flush=True)
            return
        with lock, ANSWERS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"q": q, "arm": arm, "uuid": u, "probs": probs}) + "\n")

    with ThreadPoolExecutor(max_workers=24) as pool:
        list(pool.map(one, tasks))
    print(json.dumps(jev.usage(), ensure_ascii=False), flush=True)


def official_row(cells: dict, row: str, items: list[str]) -> list[float] | None:
    c = cells.get(row.replace(" ", ""))
    if not c or any(i not in c for i in items):
        return None
    t = sum(c[i] for i in items)
    return [c[i] / t for i in items] if t else None


def age_row(age: int) -> str:
    return "19∼29세" if age < 30 else "60세이상" if age >= 60 else f"{age // 10 * 10}∼{age // 10 * 10 + 9}세"


def report() -> None:
    people, ctx, fc, s19, ref = setup()
    official = json.loads(OFFICIAL.read_text(encoding="utf-8"))
    answers: dict = defaultdict(dict)
    for line in ANSWERS.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        answers[(r["q"], r["arm"])][r["uuid"]] = r["probs"]
    for line in (base.OUT / "answers-core-v3.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["q"] in fut.QUESTIONS and r["arm"] == "ctx":
            answers[(r["q"], "y2025")][r["uuid"]] = r["probs"]
    arms = (("b2019", START), ("b2023", END), ("y2025", lh.BASE_YEAR), ("b2019a", START), ("b2023a", END), ("b2023s", END))

    def groups(year: int) -> dict:
        g = {"전체": ("계", people), "남자": ("남자", [p for p in people if p["sex"] == "남자"]),
             "여자": ("여자", [p for p in people if p["sex"] == "여자"])}
        for row in ("19∼29세", "30∼39세", "40∼49세", "50∼59세", "60세이상"):
            g[row] = (row, [p for p in people if age_row(lh.age_at(p, year)) == row])
        return g

    def mean(q, arm, members):
        rows = [answers[(q, arm)][p["uuid"]] for p in members if p["uuid"] in answers[(q, arm)]]
        return [sum(r[i] for r in rows) / len(rows) for i in range(len(rows[0]))] if rows else None

    result = {}
    for q, spec in fut.QUESTIONS.items():
        items = official[q]["items"]
        low = (lambda d: d[2]) if q == "class" else (lambda d: d[3] + d[4])
        out = {"options": spec["options"], "headline": "하층" if q == "class" else "약간+매우 불만족", "groups": {}}
        for label in groups(START):
            row = {}
            for arm, year in arms:
                orow, members = groups(year)[label]
                off = official_row(official[q]["by_year"][str(year)], orow, items)
                jv = mean(q, arm, members)
                key = str(year) if arm[-1].isdigit() else f"{year}{arm[-1]}"
                row[key] = {"n": len(members), "official": [round(x, 4) for x in off] if off else None,
                            "jev": [round(x, 4) for x in jv] if jv else None,
                            "official_low": round(100 * low(off), 1) if off else None,
                            "jev_low": round(100 * low(jv), 1) if jv else None}
            for suffix in ("", "a", "s"):
                a, b = row[f"{START}{'a' if suffix == 's' else suffix}"], row[f"{END}{suffix}"]
                if a["jev_low"] is not None and b["jev_low"] is not None and a["official_low"] is not None:
                    row[f"change_2019_2023{suffix}"] = {"official_pp": round(b["official_low"] - a["official_low"], 1),
                                                        "jev_pp": round(b["jev_low"] - a["jev_low"], 1)}
            out["groups"][label] = row
        result[q] = out
    (OUT / "backtest-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for q, v in result.items():
        print(f"## {fut.QUESTIONS[q]['title']} — {v['headline']} 비율 (실측 사회조사 / Jev)")
        for label, row in v["groups"].items():
            cells = " | ".join(f"{y} {r['official_low']}/{r['jev_low']}" for y, r in row.items() if y[:4].isdigit())
            ch, cha, chs = (row.get(f"change_2019_2023{k}", {}) for k in ("", "a", "s"))
            print(f"  {label:8s} n={row[str(START)]['n']:5d}  {cells}  변화19→23 실측 {ch.get('official_pp')} / Jev 분위 "
                  f"{ch.get('jev_pp')} / 금액+변화 {cha.get('jev_pp')} / 금액만 {chs.get('jev_pp')}")


if __name__ == "__main__":
    {"build": build, "run": run, "report": report}[sys.argv[1]]()
