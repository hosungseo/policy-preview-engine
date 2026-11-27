"""1단계 실험: does changing only the income amount of the people a policy is for
move their answer to a policy approval question — and by how much, against Jev's own re-ask noise?

  PP_JEV_PROVIDER=api ../.venv/bin/python scripts/eval_policy_amount.py run
  ../.venv/bin/python scripts/eval_policy_amount.py report

Seven arms on up to 300 people per time point, every call with the cache off (about 2,100 calls, ~$0.14):
  f0 / f360 / f1200 / f0_retest  — the 2030 projected state, with +0 / +360 / +1,200만 원 on the income line, and f0 asked again
  b0 / b360 / b0_retest          — the 2025 state block (2024 amounts), with +0 / +360, and b0 asked again
States only, never change sentences (the backtest rule). The judgement rule is fixed below (OPEN_IF); the result is
recorded whichever way it goes.
"""
from __future__ import annotations

import json
import math
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from pp import jev  # noqa: E402
from pp import life_history as lh  # noqa: E402
from ppservice.survey import aggregate, panel  # noqa: E402
from ppservice.survey.run import jev_questions, normalize, option_keys, state_for  # noqa: E402

OUT = ENGINE.parent / "runs" / "policy-amount-eval"
SEED = 2024                      # the same 3,000 people as eval_life_context
N_MAX, N_MIN = 300, 200
EFFECTS = {"f360": 360, "f1200": 1200, "b360": 360}
ARMS = ("f0", "f360", "f1200", "f0_retest", "b0", "b360", "b0_retest")
SPEC = {"title": "저소득 근로자 소득 보전",
        "policy_text": "개인 근로·사업소득이 하위 20%인 근로자에게 월 30만 원의 소득 보전금을 2027년부터 지급한다.",
        "question": "이 소득 보전금 지급에 찬성하십니까?", "options": ["찬성", "반대", "잘 모르겠다"]}
TOP = 0  # 찬성
OPEN_IF = {"direction": "+", "floor_pp": aggregate.FLOOR_PP, "z": aggregate.Z_MULTI}


def setup() -> tuple[list[dict], dict, list[dict], list[dict]]:
    """(sample, states, 2030 subjects, 2025 subjects): working, bottom quintile, with an income amount in that year."""
    people_all, _ = panel.load(addons=panel.addons_setting(panel.spec_text(SPEC)))
    sample = panel.sample(people_all, 3000, SEED)
    states = panel.states(sample)

    def subjects(key: str) -> list[dict]:
        out = []
        for p in sorted(sample, key=lambda x: x["uuid"]):
            st = states[p["uuid"]].get(key)
            if st and lh.eligible({"working": True}, st) is True and st.get("income_q") == 1 and st.get("income_amt"):
                out.append(p)
        return out[:N_MAX]
    return sample, states, subjects("then"), subjects("now")


def profile(arm: str, p: dict, st: dict) -> str:
    then, now = st["then"], st["now"]
    if arm.startswith("f"):
        state = {**then, "income_amt": then["income_amt"] + EFFECTS.get(arm, 0)}
        return lh.future_profile(p, state)
    state = {**now, "income_amt": now["income_amt"] + EFFECTS.get(arm, 0)}
    return p["profile"] + "\n\n" + lh.state_block(state, lh.BASE_YEAR, amount_year=lh.BASE_YEAR - 1)


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    _, states, f_people, b_people = setup()
    for label, group in (("2030", f_people), ("2025", b_people)):
        print(f"{label} subjects: {len(group)}", flush=True)
        if len(group) < N_MIN:
            print(f"fewer than {N_MIN} subjects for {label}; stopping (record this in the README)")
            return
    path = OUT / "answers.jsonl"
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done.add((r["arm"], r["uuid"]))
    tasks = [(arm, p) for arm in ARMS for p in (f_people if arm.startswith("f") else b_people) if (arm, p["uuid"]) not in done]
    print(f"{len(tasks)} calls ({len(done)} done)", flush=True)
    keys = option_keys(SPEC["options"])
    questions = jev_questions(SPEC["options"])
    lock = threading.Lock()
    jev.reset_usage()

    def one(task) -> None:
        arm, p = task
        try:
            out = jev.evaluate(state_for("main", SPEC, {**p, "profile": profile(arm, p, states[p["uuid"]])}), questions,
                               label="policy-amount-eval", cache=False)
            probs = normalize(out["answers"]["q"]["probabilities"], keys)
        except Exception as e:  # recorded as missing; a rerun fills it
            print("fail", arm, p["uuid"], type(e).__name__, e, flush=True)
            return
        with lock, path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"arm": arm, "uuid": p["uuid"], "probs": probs}) + "\n")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, tasks))
    usage = jev.usage()
    print(json.dumps(usage, ensure_ascii=False), flush=True)
    u = usage.get("policy-amount-eval") or {}
    print(f"cost ≈ ${jev.cost_usd(int(u.get('input_tokens') or 0)):.3f}")


def report() -> None:
    _, states, f_people, b_people = setup()
    answers: dict[str, dict[str, list[float]]] = {}
    for line in (OUT / "answers.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        answers.setdefault(r["arm"], {})[r["uuid"]] = r["probs"]
    lines = [f"# 1단계 실험 — 소득 금액만 바꿔 다시 묻기 (seed {SEED}, 2030 표본 {len(f_people)}명 · 2025 표본 {len(b_people)}명 · "
             f"겹침 {len({p['uuid'] for p in f_people} & {p['uuid'] for p in b_people})}명)", "",
             "| 팔 | n | ‘찬성’ 평균 % |", "|---|---|---|"]
    for arm in ARMS:
        rows = answers.get(arm, {})
        if rows:
            lines.append(f"| `{arm}` | {len(rows)} | {100 * aggregate.mean_shares(list(rows.values()), 3)[TOP]:.1f} |")

    def pair(a: str, b: str) -> dict | None:
        ids = [u for u in answers.get(a, {}) if u in answers.get(b, {})]
        if not ids:
            return None
        diffs = [answers[b][u][TOP] - answers[a][u][TOP] for u in ids]
        mean = sum(diffs) / len(ids)
        sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / len(ids))
        return {"n": len(ids), "shift_pp": 100 * mean, "sd_pair": sd, "abs_mean_pp": 100 * sum(abs(d) for d in diffs) / len(ids),
                "over5_share": sum(abs(d) > 0.05 for d in diffs) / len(ids)}

    lines += ["", "| 비교 | n | 이동 %p | 1인당 차이 SD | 1인당 |차| 평균 %p | |차|>5%p 비율 |", "|---|---|---|---|---|---|"]
    stats = {}
    for a, b in (("f0", "f360"), ("f0", "f1200"), ("f0", "f0_retest"), ("b0", "b360"), ("b0", "b0_retest")):
        s = pair(a, b)
        stats[(a, b)] = s
        if s:
            lines.append(f"| `{a}`→`{b}` | {s['n']} | {s['shift_pp']:+.2f} | {s['sd_pair']:.3f} | {s['abs_mean_pp']:.2f} | {100 * s['over5_share']:.0f}% |")

    # Cross-sectional slope inside f0: equal-count income quintiles → top share, slope × 360 (reference only)
    f0 = answers.get("f0", {})
    rows = sorted((states[u]["then"]["income_amt"], f0[u][TOP]) for u in f0 if states[u]["then"])
    if len(rows) >= 50:
        n = len(rows)
        xs = [sum(r[0] for r in rows[i * n // 5:(i + 1) * n // 5]) / max(1, (i + 1) * n // 5 - i * n // 5) for i in range(5)]
        ys = [100 * sum(r[1] for r in rows[i * n // 5:(i + 1) * n // 5]) / max(1, (i + 1) * n // 5 - i * n // 5) for i in range(5)]
        mx, my = sum(xs) / 5, sum(ys) / 5
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / max(1e-9, sum((x - mx) ** 2 for x in xs))
        lines += ["", f"횡단 기울기(참고, 판정에 쓰지 않음): `f0` 소득 5분위 평균 소득 {', '.join(f'{x:,.0f}' for x in xs)}만 원 → ‘찬성’ "
                  f"{', '.join(f'{y:.1f}' for y in ys)}% · 기울기 × 360만 원 = {360 * slope:+.2f}%p"]

    def judge(key: tuple, retest: tuple) -> tuple[str, float, float]:
        s, r = stats.get(key), stats.get(retest)
        if not s or not r:
            return "자료 없음", 0.0, 0.0
        t = max(OPEN_IF["floor_pp"], 100 * OPEN_IF["z"] * s["sd_pair"] / math.sqrt(s["n"]), abs(r["shift_pp"]))
        if s["shift_pp"] > t:
            return "열림", s["shift_pp"], t
        if s["shift_pp"] < -t:
            return "닫힘(음의 방향 유의)", s["shift_pp"], t
        return "닫힘", s["shift_pp"], t

    vf, sf, tf = judge(("f0", "f360"), ("f0", "f0_retest"))
    vb, sb, tb = judge(("b0", "b360"), ("b0", "b0_retest"))
    lines += ["", f"판정 기준 T = max({OPEN_IF['floor_pp']}, {OPEN_IF['z']}·sd_pair/√n, |retest 집단 이동|)",
              f"- 2030(`f360`): 이동 {sf:+.2f}%p, T_f {tf:.2f}%p → **{vf}**",
              f"- 2025(`b360`): 이동 {sb:+.2f}%p, T_b {tb:.2f}%p → **{vb}**"]
    if vf == "열림" and vb == "열림":
        pick = "2025" if sb / tb > sf / tf else "2030"
        lines.append(f"- 둘 다 열림 → 2단계 시점 {pick} (이동/T가 큰 쪽; 같으면 2030)")
    elif vf == "열림" or vb == "열림":
        lines.append(f"- 2단계 시점 {'2030' if vf == '열림' else '2025'}")
    else:
        lines.append("- 2단계는 닫힘. `future_policy` 팔은 만들지 않는다.")
    text = "\n".join(lines)
    print(text)
    (OUT / "report.md").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    {"run": run, "report": report}[sys.argv[1]]()
