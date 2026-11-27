"""The policy world model end to end: policy -> state change (life_history.project) -> opinion (Jev).

  PP_JEV_PROVIDER=api ../.venv/bin/python scripts/eval_future.py run
  ../.venv/bin/python scripts/eval_future.py report

The same 3,000 people as eval_life_context. Arms:
  y2025  — core add-ons as of 2025 (reused from eval_life_context answers-core-v3)
  y2030  — the same persona five years on (baseline run: ageing, work, moves, marriage, smoking, income quintile)
  y2030s — five years on under the scenario "5 more in 100 of the bottom quintile leave it each year"
  s10..s30 — the same scenario at 10/15/20/30 more in 100 (a dose sweep; unchanged people hit the cache)
  retest — y2030 asked again with the cache off for a fixed sample, to measure Jev's own run-to-run spread
           (the report reads the pairs from retest.jsonl: {q, uuid, first, second})
People who died by 2030 are left out of both 2030 arms. Nothing here is checked against a real 2030; it shows how far
simulated life changes move the synthetic answers, and whether a policy that changes lives changes opinions.
"""
import gzip
import json
import re
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "scripts"))

from pp import jev, life_context  # noqa: E402
from ppservice.survey.run import jev_questions, normalize, option_keys, state_for  # noqa: E402
import eval_life_context as base  # noqa: E402

OUT = ENGINE.parent / "runs" / "life-history-eval"
FORECAST = ENGINE / "ppservice" / "data" / "persona-context" / "life-forecast-v1.jsonl.gz"
HISTORY = ENGINE / "ppservice" / "data" / "persona-context" / "life-history-v1.jsonl.gz"
CORE = "housing,finance,assets,welfare,work,health,elder,digital,belief"
QUESTIONS = {q: base.QUESTIONS[q] for q in ("class", "income_sat")}
ARMS = ("y2030", "y2030s")
SWEEP = {"s10": "0.10", "s15": "0.15", "s20": "0.20", "s30": "0.30"}
RETEST_N = 500
STATUS_KO = {"배우자있음": "배우자 있음", "미혼": "미혼", "이혼": "이혼", "사별": "사별"}
PROVINCE_KO = {"충청북": "충북", "충청남": "충남", "전라남": "전남", "경상북": "경북", "경상남": "경남"}


def load(path: Path) -> dict:
    return {r["uuid"]: r for r in (json.loads(x) for x in gzip.decompress(path.read_bytes()).decode().splitlines() if x)}


def future_block(person: dict, now: dict, then: dict) -> str:
    """Lines for the person in 2030; changes since 2025 are stated as changes."""
    lines = ["[2030년 시뮬레이션 — 공공통계의 연간 변화 확률로 5년을 굴린 가정이며 이 사람에 대한 사실이 아님]",
             f"- 지금은 2030년이고, 이 사람은 {then['age']}세입니다."]
    prov = lambda x: PROVINCE_KO.get(x, x)  # noqa: E731
    if then["province"] != person["province"]:
        lines.append(f"- 거주: 2025년 이후 {prov(person['province'])}에서 {prov(then['province'])}(으)로 이사함")
    m0, m1 = now.get("marital"), then.get("marital")
    if m0 and m1 and m0 != m1:
        lines.append(f"- 혼인: 2025년 {STATUS_KO[m0]} → 2030년 {STATUS_KO[m1]}")
    w0, w1 = now.get("working"), then.get("working")
    if w0 is not None and w1 is not None and w0 != w1:
        lines.append("- 일: 2025년 이후 " + ("일을 시작함" if w1 else "일을 그만둠"))
    q0, q1 = now.get("income_q"), then.get("income_q")
    if q1 and q0 and q0 != q1:
        lines.append(f"- 개인 근로·사업소득 분위: 2024년 {q0}분위 → 2030년 {q1}분위")
    elif q1 and q1 in (1, 5):
        lines.append(f"- 개인 근로·사업소득: 2030년 {'하위' if q1 == 1 else '상위'} 20%")
    s0, s1 = now.get("smoking"), then.get("smoking")
    if s0 is not None and s1 is not None and s0 != s1:
        lines.append("- 흡연: " + ("담배를 끊음" if s0 else "담배를 피우기 시작함"))
    return "\n".join(lines)


def profile_2030(person: dict, ctx: dict, now: dict, then: dict) -> dict:
    text = re.sub(r"(성별·나이: [^,\n]+, )\d+세", lambda m: f"{m.group(1)}{then['age']}세", person["profile"])
    # the 2025 work lines would contradict a 2030 person who no longer works
    addons = CORE if then.get("working") else CORE.replace(",work", "")
    extra = life_context.block(ctx, addons)
    return {**person, "age": then["age"], "profile": text + "\n\n" + extra + "\n" + future_block(person, now, then)}


def setup():
    people, ctx = base.people_and_context()
    fc, hist = load(FORECAST), load(HISTORY)
    now = {}
    for p in people:
        h = hist.get(p["uuid"], {})
        q = {int(k): v for k, v in (h.get("income_q") or {}).items()}
        now[p["uuid"]] = {"marital": (h.get("marital") or {}).get("2025"), "working": (h.get("employed") or {}).get("2025"),
                          "income_q": q.get(2024), "smoking": ctx[p["uuid"]].get("smoking")}
    return people, ctx, fc, now


def state_of(row: dict, arm: str) -> dict:
    if arm in ("y2030", "retest"):
        return row["baseline"]
    if arm == "y2030s":
        return row["scenario"]
    return row["sweep"][SWEEP[arm]]


def run(arms: tuple = ARMS) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    people, ctx, fc, now = setup()
    alive = [p for p in people if fc[p["uuid"]]["baseline"]["alive"]]
    retest = {p["uuid"] for p in sorted(alive, key=lambda p: p["uuid"])[:RETEST_N]}
    path = OUT / "answers.jsonl"
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done.add((r["q"], r["arm"], r["uuid"]))
    tasks = [(q, arm, p) for q in QUESTIONS for arm in arms for p in alive
             if (q, arm, p["uuid"]) not in done and (arm != "retest" or p["uuid"] in retest)]
    print(f"{len(tasks)} calls ({len(done)} done)", flush=True)
    lock = threading.Lock()
    jev.reset_usage()

    def one(task) -> None:
        q, arm, p = task
        then = state_of(fc[p["uuid"]], arm)
        spec = {**{k: QUESTIONS[q][k] for k in ("title", "question", "options")}, "policy_text": base.NEUTRAL}
        keys = option_keys(spec["options"])
        try:
            out = jev.evaluate(state_for("main", spec, profile_2030(p, ctx[p["uuid"]], now[p["uuid"]], then)),
                               jev_questions(spec["options"]), label="life-history-eval",
                               cache=arm != "retest")
            probs = normalize(out["answers"]["q"]["probabilities"], keys)
        except Exception as e:  # recorded as missing; a rerun fills it
            print("fail", q, arm, p["uuid"], type(e).__name__, e, flush=True)
            return
        with lock, path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"q": q, "arm": arm, "uuid": p["uuid"], "probs": probs}) + "\n")

    with ThreadPoolExecutor(max_workers=24) as pool:
        list(pool.map(one, tasks))
    print(json.dumps(jev.usage(), ensure_ascii=False), flush=True)


def report() -> None:
    people, ctx, fc, now = setup()
    answers: dict = defaultdict(dict)
    for line in (OUT / "answers.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        answers[(r["q"], r["arm"])][r["uuid"]] = r["probs"]
    for line in (base.OUT / "answers-core-v3.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["q"] in QUESTIONS and r["arm"] == "ctx":
            answers[(r["q"], "y2025")][r["uuid"]] = r["probs"]
    # pairs written by the retest arm: the first (cached) answer and a second asked with the cache off
    path = OUT / "retest.jsonl"
    retest = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    alive = [p["uuid"] for p in people if fc[p["uuid"]]["baseline"]["alive"]]
    bottom = [u for u in alive if now[u]["income_q"] == 1]
    changed = [u for u in alive if fc[u]["baseline"] != fc[u]["scenario"]]
    groups = {"생존자 전체": alive, "2024년 개인소득 하위 20%": bottom, "시나리오로 상태가 달라진 사람": changed}

    def mean(q, arm, members):
        rows = [answers[(q, arm)][u] for u in members if u in answers[(q, arm)]]
        return [round(sum(r[i] for r in rows) / len(rows), 4) for i in range(len(rows[0]))] if rows else None

    result = {}
    for q, spec in QUESTIONS.items():
        result[q] = {"options": spec["options"], "groups": {
            g: {"n": len(m), **{arm: mean(q, arm, m) for arm in ("y2025", "y2030", "y2030s")}} for g, m in groups.items()}}

    def low(q, probs):  # the headline share: 하층, or 약간+매우 불만족
        return probs[2] if q == "class" else probs[3] + probs[4]

    # dose sweep: people whose 2030 state differs from the baseline, and the whole-panel shift
    for q in QUESTIONS:
        sweep = {}
        for arm, key in (("y2030s", "0.05"), *((a, k) for a, k in SWEEP.items())):
            state = (lambda u: fc[u]["scenario"]) if arm == "y2030s" else (lambda u, k=key: fc[u]["sweep"][k])
            moved = [u for u in alive if state(u) != fc[u]["baseline"]]
            have = [u for u in alive if u in answers[(q, arm)] or state(u) == fc[u]["baseline"]]
            if len(have) < len(alive):
                continue
            pick = lambda u: answers[(q, arm)].get(u) or answers[(q, "y2030")][u]  # noqa: E731
            d = [low(q, pick(u)) - low(q, answers[(q, "y2030")][u]) for u in moved]
            sweep[key] = {"changed": len(moved),
                          "changed_mean_pp": round(100 * sum(d) / len(d), 2) if d else 0.0,
                          "panel_shift_pp": round(100 * sum(d) / len(alive), 3),
                          "bottom_left_by_2030": round(sum(1 for u in alive if now[u]["income_q"] == 1
                                                           and state(u)["income_q"] not in (None, 1)) / len(bottom), 4)}
        result[q]["sweep"] = sweep
        # Jev's own spread: the same prompt asked twice (first answer cached, second with the cache off)
        pairs = [(r["first"], r["second"]) for r in retest if r["q"] == q]
        if pairs:
            dd = sorted(abs(low(q, b) - low(q, a)) for a, b in pairs)
            mean_a = sum(low(q, a) for a, _ in pairs) / len(pairs)
            mean_b = sum(low(q, b) for _, b in pairs) / len(pairs)
            result[q]["retest"] = {"n": len(pairs), "mean_abs_pp": round(100 * sum(dd) / len(dd), 2),
                                   "p90_abs_pp": round(100 * dd[int(0.9 * len(dd))], 2),
                                   "identical": round(sum(x == 0 for x in dd) / len(dd), 3),
                                   "group_mean_shift_pp": round(100 * (mean_b - mean_a), 2)}
    (OUT / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for q, v in result.items():
        print("##", QUESTIONS[q]["title"], v["options"])
        for g, row in v["groups"].items():
            print(f"  {g:24s} n={row['n']:5d}  2025 {base.fmt(row['y2025'])} | 2030 {base.fmt(row['y2030'])} | "
                  f"2030 시나리오 {base.fmt(row['y2030s'])}")
        for k, r in v.get("sweep", {}).items():
            print(f"  +{float(k) * 100:.0f}pp: 처지 바뀐 {r['changed']}명 평균 {r['changed_mean_pp']:+.1f}pp, "
                  f"전체 {r['panel_shift_pp']:+.2f}pp, 2024년 하위20% 탈출 {r['bottom_left_by_2030']:.1%}")
        if "retest" in v:
            print("  재질문:", v["retest"])


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(tuple(sys.argv[2].split(",")) if len(sys.argv) > 2 else ARMS)
    else:
        report()
