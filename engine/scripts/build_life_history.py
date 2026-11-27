"""Build panel life histories (pp/life_history.py) and check them against the published tables.

  ../.venv/bin/python scripts/build_life_history.py

Writes ppservice/data/persona-context/life-history-v1.jsonl.gz and report-history-v1.json.
"""
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from pp import life_context, life_history as lh  # noqa: E402
from build_life_context import load_people  # noqa: E402

OUT = lh.OUT
CONTEXT = OUT / "life-context-v2.jsonl.gz"
SEED = 2025
SWEEP = (0.10, 0.15, 0.20, 0.30)


def pct(x: float) -> float:
    return round(100 * x, 1)


def income_checks(people: list[dict], hist: dict, mob: dict) -> dict:
    by_uid = {p["uuid"]: p for p in people}
    margins, directions = [], []
    for year in lh.INCOME_YEARS:
        cells = defaultdict(lambda: [0] * 5)
        for uid, h in hist.items():
            if year in h:
                p = by_uid[uid]
                g = lh.age_group(lh.age_at(p, year - 1 if year > 2017 else year))
                cells[(p["sex"], g)][h[year] - 1] += 1
        for (sex, g), counts in cells.items():
            n = sum(counts)
            want = lh.quintile_shares(mob, year, sex, g)
            margins.append({"year": year, "sex": sex, "age": g, "n": n,
                            "max_gap_pp": round(max(abs(c / n - w) for c, w in zip(counts, want)) * 100, 2)})
    for year in lh.INCOME_YEARS[1:]:
        cells = defaultdict(lambda: {"up": 0, "stay": 0, "down": 0})
        for uid, h in hist.items():
            if year in h and year - 1 in h:
                p = by_uid[uid]
                g = lh.age_group(lh.age_at(p, year - 1))
                d = "up" if h[year] > h[year - 1] else "down" if h[year] < h[year - 1] else "stay"
                cells[(p["sex"], g)][d] += 1
        for (sex, g), c in cells.items():
            n = sum(c.values())
            want = mob["by_year"][str(year)][sex][g]["direction"]
            directions.append({"year": year, "sex": sex, "age": g, "n": n,
                               **{k: [pct(c[k] / n), pct(want[k])] for k in ("up", "stay", "down")}})
    stays = {}
    for q, key in ((1, "q1"), (5, "q5")):
        for year in lh.INCOME_YEARS[1:]:
            pairs = [h for h in hist.values() if year in h and year - 1 in h and h[year - 1] == q]
            got = sum(h[year] == q for h in pairs) / max(1, len(pairs))
            stays.setdefault(key, []).append({"year": year, "panel": pct(got),
                                              "official": pct(mob["persistence"][key]["stay"][str(year)])})
    return {"margins_max_gap_pp": max(m["max_gap_pp"] for m in margins), "margins": margins,
            "direction_mean_abs_gap_pp": round(sum(abs(d[k][0] - d[k][1]) for d in directions
                                                   for k in ("up", "stay", "down")) / (3 * len(directions)), 2),
            "directions": directions, "one_year_stay": stays}


def out_of_time(people: list[dict], mob: dict, stayers: dict, employed: dict) -> dict:
    """Run 2019->2020 on the 2024 transition matrices (a fixed-kernel forecast) and compare with the published
    2020 directions: how far a constant-2024 world drifts from a year that really happened."""
    frozen = {**mob, "by_year": {y: mob["by_year"]["2024"] for y in mob["by_year"]}}
    hist = lh.simulate_income(people, frozen, stayers, SEED + 9, employed=employed)
    rows = [d for d in income_checks(people, hist, mob)["directions"] if d["year"] == 2020]
    return {"kernel": "2024", "predicted_2020": rows,
            "mean_abs_gap_pp": round(sum(abs(d[k][0] - d[k][1]) for d in rows for k in ("up", "stay", "down"))
                                     / (3 * len(rows)), 2)}


def smoking_checks(people: list[dict], ctx: dict, hist: dict) -> dict:
    t = life_context.tables()
    series = t["history_smoking"]
    yearly = []
    for y in lh.SMOKING_YEARS:
        rows = [(p, hist[p["uuid"]][y]) for p in people if p["uuid"] in hist and y in hist[p["uuid"]]]
        ref = [series.get(p["district"], {}).get(str(y)) for p, _ in rows]
        ref = [r for r in ref if r is not None]
        yearly.append({"year": y, "n": len(rows), "panel": pct(sum(s for _, s in rows) / len(rows)),
                       "district_rate_mean": pct(sum(ref) / len(ref))})
    final_match = all(h[lh.BASE_YEAR] == ctx[uid]["smoking"] for uid, h in hist.items())
    sens = {}
    for c in (0.97, 0.985, 0.995):
        h = hist if c == lh.SMOKING_C else lh.simulate_smoking(people, ctx, SEED, c=c)
        smokers = [x for x in h.values() if x.get(2024) is not None and x.get(2024)]
        still = sum(x[2025] for x in smokers) / max(1, len(smokers))
        quit_line = sum(1 for x in h.values() if not x[2025] and any(x.values())) / len(h)
        sens[str(c)] = {"smoker_2024_still_2025": pct(still), "share_with_quit_line": pct(quit_line)}
    return {"yearly": yearly, "final_year_equals_life_context": final_match, "sensitivity": sens,
            "note": "district_rate_mean is the unweighted mean of the panel members' district rates (조율), which "
                    "the panel tracks by construction; it is not the national rate."}


def employment_checks(people: list[dict], employed: dict) -> dict:
    """Yearly working share in the panel vs the published employment rate change (the panel's level is its own)."""
    rates = life_context.tables()["history_employment"]
    by_uid = {p["uuid"]: p for p in people}
    rows = []
    for y in lh.HISTORY_YEARS:
        cohort = [u for u, h in employed.items() if y in h]
        got = sum(employed[u][y] for u in cohort) / len(cohort)
        expect = sum(lh.employment_prob(rates, y, by_uid[u]["sex"], lh.age_at(by_uid[u], y)) for u in cohort) / len(cohort)
        rows.append({"year": y, "n": len(cohort), "panel": pct(got), "official_rate_same_people": pct(expect)})
    stays = [sum(h[y] and h[y + 1] for h in employed.values() if y in h and y + 1 in h)
             / max(1, sum(h[y] for h in employed.values() if y in h and y + 1 in h)) for y in lh.HISTORY_YEARS[:-1]]
    return {"yearly": rows, "working_still_working_next_year": pct(sum(stays) / len(stays)),
            "note": "Personas work more often than the survey (2025 level = panel); the change over years follows the "
                    "published rates, so the panel - official gap should stay roughly constant."}


def residence_checks(people: list[dict], res: dict) -> dict:
    mig = life_context.tables()["history_migration"]
    rows = []
    for y in lh.HISTORY_YEARS[1:]:
        moved = sum(1 for h in res.values() if h[y] != h[y - 1]) / len(res)
        national = sum(mig[str(y)]["od"][d][o] for d in mig[str(y)]["od"] for o in mig[str(y)]["od"][d])
        rows.append({"year": y, "panel_moved_pct": pct(moved), "official_movers_pct_of_2025_pop": pct(national / 51_700_000)})
    ever = sum(1 for h in res.values() if len(set(h.values())) > 1) / len(res)
    by_uid = {p["uuid"]: p for p in people}
    census = life_context.tables()["history_repeat_movers"]
    five = []
    for sex in ("남자", "여자"):
        for b in ("20", "25", "30", "35", "40", "50", "60"):
            members = [u for u, h in res.items() if by_uid[u]["sex"] == sex and int(b) <= lh.age_at(by_uid[u], 2025) < int(b) + 5]
            if members and b in census.get(sex, {}):
                got = sum(res[u][2025] != res[u][2020] for u in members) / len(members)
                five.append({"sex": sex, "age_2025": b, "panel_2020_2025": pct(got),
                             "census_2005_five_year": pct(census[sex][b]["five_year"])})
    return {"yearly": rows, "ever_moved_2017_2025": pct(ever), "five_year_by_age": five,
            "mover_shape_k": lh.fit_mover_shape(),
            "note": "Panel is 19+, the official yearly share is of all ages (movers / ~51.7M). Mobility propensity "
                    "(Gamma, mean 1, shape k) is sized on the 2005 census five-year question, the latest published "
                    "by age; today's moves are rarer, so the panel five-year shares should sit somewhat below 2005."}


def marital_checks(people: list[dict], mar: dict) -> dict:
    t = life_context.tables()
    by_uid = {p["uuid"]: p for p in people}
    out = {}
    for kind, table, to in (("marriage", t["history_marriage"], lh.MARRIED), ("divorce", t["history_divorce"], lh.DIVORCED)):
        gaps, rates = [], []
        for y in lh.HISTORY_YEARS[1:]:
            for sex in ("남자", "여자"):
                for a in range(20, 60, 5):
                    pop = [u for u in mar if by_uid[u]["sex"] == sex and a <= lh.age_at(by_uid[u], y) < a + 5]
                    ev = sum(1 for u in pop if mar[u][y] == to and mar[u][y - 1] != to)
                    want = table[str(y)][sex].get(str(a))
                    if pop and want is not None:
                        gaps.append(abs(ev / len(pop) - want))
                        rates.append(want)
        out[kind] = {"mean_abs_gap_per_1000": round(1000 * sum(gaps) / len(gaps), 2),
                     "mean_rate_per_1000": round(1000 * sum(rates) / len(rates), 2)}
    out["changed_2017_2025_pct"] = pct(sum(1 for h in mar.values() if h[2017] != h[2025]) / len(mar))
    return out


def main() -> None:
    people = load_people()
    ctx = {r["uuid"]: r for r in (json.loads(x) for x in gzip.decompress(CONTEXT.read_bytes()).decode().splitlines() if x)}
    mob = life_context.tables()["history_income_mobility"]
    employed = lh.simulate_employment(people, SEED)
    corr = lh.fit_one_year_corr(mob)
    lam, copula_fit = lh.fit_lambda_copula(people, mob, corr, SEED)
    print("copula (rejected)", corr, lam, flush=True)
    stayers, stay_fit = lh.fit_stayers(people, mob, SEED, employed=employed)
    print("stayers", stayers, flush=True)
    flags: dict = {}
    income = lh.simulate_income(people, mob, stayers, SEED, employed=employed, flags=flags)
    tables = life_context.tables()
    amounts = lh.simulate_amounts(people, income, SEED, tables["history_wage_level"])
    smoking = lh.simulate_smoking(people, ctx, SEED)
    residence = lh.simulate_residence(people, SEED)
    marital = lh.simulate_marital(people, SEED)
    hist_s = {u: {int(k): v for k, v in h.items()} for u, h in smoking.items()}
    hist = {}
    for p in people:
        h = {}
        for key, src in (("employed", employed), ("income_q", income), ("income_amt", amounts), ("smoking", smoking),
                         ("residence", residence), ("marital", marital)):
            if p["uuid"] in src:
                h[key] = src[p["uuid"]]
        hist[p["uuid"]] = h
    base = lh.project(people, hist, ctx, flags, SEED)
    scen = lh.project(people, hist, ctx, flags, SEED, bottom_exit_extra=0.05, kernels=base["kernels"])
    # a dose sweep: how large the assumed effect must be before the whole-panel opinion moves
    sweep = {f"{x:.2f}": lh.project(people, hist, ctx, flags, SEED, bottom_exit_extra=x,
                                         kernels=base["kernels"]) for x in SWEEP}
    report = {
        "version": "life-history-v1",
        "assumptions": {"panel_age_year": lh.BASE_YEAR,
                        "income_quintile": "personal labour + business income quintile among two-year earners, "
                                           "followed in employed years; independent of the household income band (v1)",
                        "smoking_c_lam": [lh.SMOKING_C, lh.SMOKING_LAM], "employment_c_lam": [lh.EMPLOY_C, lh.EMPLOY_LAM],
                        "forward_kernels": "2024 income transitions re-fitted to 2024 margins on the baseline (frozen for scenarios), 2025 employment level (panel), 2025 "
                                           "migration flows, 2025 marriage/divorce rates, 2024 life table"},
        "employment": employment_checks(people, employed),
        "income": {"model": "Markov on published 5x5 transitions by year x sex x prior-year age, mover-stayer mix, "
                            "transitions re-fitted each year to the published margins; stayers lapse at 65",
                   "stayers": stayers, "persistence_since_2017": stay_fit,
                   "rejected_gaussian_copula": {"one_year_corr": corr, "lambda": lam, "persistence": copula_fit},
                   "checks": income_checks(people, income, mob),
                   "out_of_time": out_of_time(people, mob, stayers, employed), "followed": len(income)},
        "income_amount": {"model": "nominal annual labour + business income: sex x age-band lognormal from the published "
                                   "wage-job mean/median of the year, truncated to the national band of the person's "
                                   "quintile; within-band rank = sqrt(%s) person + AR(1) noise, one-year corr %s; levels beyond "
                                   "the last table extrapolate each cell's %d-year compound growth" % (lh.RANK_LAM, lh.RANK_C, lh.LEVEL_WINDOW),
                          "checks": lh.amount_checks(people, amounts, tables["history_wage_level"],
                                                     tables["history_income_change"], income)},
        "smoking": smoking_checks(people, ctx, hist_s),
        "residence": residence_checks(people, residence),
        "marital": marital_checks(people, marital),
        "forward": {"baseline": base["years"],
                    "scenario_bottom_exit_plus_5pp": scen["years"],
                    "scenario": "each year 5 more in 100 of the bottom quintile move up one quintile (an assumed "
                                "policy effect, not an estimate); same random numbers as the baseline",
                    "sweep": {k: v["years"] for k, v in sweep.items()}},
    }
    lines = defaultdict(int)
    rows = []
    for p in people:
        h = hist[p["uuid"]]
        if h:
            rows.append({"uuid": p["uuid"], **h})
            for line in lh.history_lines(h):
                lines[line.split(":")[0]] += 1
    report["line_counts"] = dict(lines)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "life-history-v1.jsonl.gz").write_bytes(gzip.compress(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8"), mtime=0))
    (OUT / "life-forecast-v1.jsonl.gz").write_bytes(gzip.compress("\n".join(
        json.dumps({"uuid": u, "baseline": base["people"][u], "scenario": scen["people"][u],
                    "sweep": {k: v["people"][u] for k, v in sweep.items()}}, ensure_ascii=False)
        for u in base["people"]).encode("utf-8"), mtime=0))
    (OUT / "report-history-v1.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    inc = report["income"]["checks"]
    print(json.dumps({"margins_max_gap_pp": inc["margins_max_gap_pp"],
                      "direction_mean_abs_gap_pp": inc["direction_mean_abs_gap_pp"],
                      "persistence": stay_fit["fitted"], "target": stay_fit["target"],
                      "out_of_time_gap_pp": report["income"]["out_of_time"]["mean_abs_gap_pp"],
                      "employment": report["employment"], "residence": report["residence"],
                      "marital": report["marital"], "forward": report["forward"],
                      "lines": report["line_counts"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
