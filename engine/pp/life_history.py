"""Life histories: the same panel member followed over several years, built from yearly published tables.

Each year's distribution is fixed by that year's table (the person's age that year, their district). What ties the
years together is a person-level latent score (Gaussian copula):

    z[i, t] = sqrt(lam) * u[i] + sqrt(1 - lam) * e[i, t],   e[i, t] = rho * e[i, t-1] + sqrt(1 - rho^2) * eps

`u` is a lasting personal trait, `e` drifts year to year. The state in year t is z against that year's threshold(s),
so every yearly share matches its table whatever (lam, rho) are; (lam, rho) only decide *who* changes. The one-year
correlation c = lam + (1 - lam) * rho is fitted to published one-year transitions, and lam to long-run persistence
(a pure AR(1) that matches one-year stays under-predicts eight-year persistence).

* personal income quintile (근로+사업소득) 2017-2024 — 소득이동통계 gives yearly shares by sex x age and the
  transitions, so both c (per age group) and lam are calibrated and checked (grade A).
* current smoking 2018-2025 — 지역사회건강조사 gives yearly district rates only; the final year is the life-context
  draw, earlier years are drawn backwards from it. (lam, rho) are an assumption with a sensitivity band (grade C).

* employment (working or not) 2017-2025 — yearly employment rates by sex x age (경제활동인구조사); 2025 = the persona's
  occupation (무직 or not), earlier years drawn backwards with the copula (grade C). The income quintile is followed
  only in employed years.
* 시도 of residence 2017-2025 — drawn backwards from the 2025 시도 with the published interprovincial flows: the chance
  of having moved in during a year is the sex x age in-migration rate scaled by the destination's in-flow rate, the
  origin follows that year's origin x destination table (grade A for flows).
* marital status 2017-2025 — drawn backwards from the 2025 status with sex x age marriage and divorce rates
  (인구동향) divided by the panel's share married / divorced at that age (grade B). Widowhood is kept as is.

`project()` runs the panel forward from 2025: ageing, deaths (2024 life table), and every attribute on its latest
kernel, with an optional policy scenario that swaps one transition while keeping the same random numbers.

Assumption recorded in the report: panel ages are as of 2025 (the life-context base year).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
from pathlib import Path

try:
    import numpy as np
except ImportError:  # service image omits numpy; non-array helpers and constants still load cleanly
    np = None  # type: ignore[assignment]

from pp import config, life_context

BASE_YEAR = 2025
INCOME_YEARS = list(range(2017, 2025))
SMOKING_YEARS = list(range(2018, 2026))
AGE_GROUPS = ("19~39세", "40~64세", "65세 이상")
# Smoking persistence is not published as a transition. c = 0.985 keeps ~90% of this year's smokers smoking next
# year (an assumption in line with low yearly quit success); the report shows c in {0.97, 0.985, 0.995}.
SMOKING_C, SMOKING_LAM = 0.985, 0.8
# Employment persistence is not published for persons either; c = 0.95 keeps ~93% of the employed in work a year
# later at prime-age rates (assumption; report shows a sensitivity).
EMPLOY_C, EMPLOY_LAM = 0.95, 0.6
HISTORY_YEARS = list(range(2017, 2026))
MARRIED, SINGLE, DIVORCED, WIDOWED = "배우자있음", "미혼", "이혼", "사별"
OUT = Path(__file__).resolve().parents[1] / "ppservice" / "data" / "persona-context"


def age_at(person: dict, year: int) -> int:
    return int(person["age"]) - (BASE_YEAR - year)


def age_group(age: int) -> str | None:
    if age < 19:
        return None
    return AGE_GROUPS[0] if age < 40 else AGE_GROUPS[1] if age < 65 else AGE_GROUPS[2]


def _rng(seed: int, name: str, uid: str) -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha256(f"{seed}|{name}|{uid}".encode()).hexdigest()[:16], 16))


def _ppf(p: np.ndarray) -> np.ndarray:
    from statistics import NormalDist
    nd = NormalDist()
    return np.vectorize(lambda x: nd.inv_cdf(min(max(x, 1e-9), 1 - 1e-9)))(p)


def _ar_path(lam: list[float], rho: list[float], u: float, draws: np.ndarray) -> np.ndarray:
    """z over len(draws) years; lam/rho may differ per year (age group), each z stays N(0, 1)."""
    z = np.empty(len(draws))
    e = draws[0]
    for t in range(len(draws)):
        if t:
            e = rho[t] * e + math.sqrt(1 - rho[t] ** 2) * draws[t]
        z[t] = math.sqrt(lam[t]) * u + math.sqrt(1 - lam[t]) * e
    return z


# ---- shared helpers ------------------------------------------------------------------------------------------------

def band_rate(rates: dict, age: int) -> float | None:
    """Rate for an age from {band lower bound (or 'N+'): rate} tables."""
    best = None
    for b, v in rates.items():
        lo = int(b.rstrip("+"))
        if age >= lo and (b.endswith("+") or age < lo + 5) and (best is None or lo > best[0]):
            best = (lo, v)
    return best[1] if best else None


def backward_binary(final: bool, probs: dict, c: float, lam: float, rng: np.random.Generator) -> dict:
    """{year: state} drawn backwards from the final year's known state with the Gaussian copula (time-reversible AR)."""
    from statistics import NormalDist
    nd = NormalDist()
    years = sorted(probs)
    rho = (c - lam) / (1 - lam)
    cut = nd.inv_cdf(min(max(probs[years[-1]], 1e-6), 1 - 1e-6))
    lo, hi = (0.0, nd.cdf(cut)) if final else (nd.cdf(cut), 1.0)
    z_last = nd.inv_cdf(min(max(lo + rng.random() * (hi - lo), 1e-9), 1 - 1e-9))
    u = math.sqrt(lam) * z_last + math.sqrt(1 - lam) * rng.standard_normal()
    e = (z_last - math.sqrt(lam) * u) / math.sqrt(1 - lam)
    states = {years[-1]: bool(final)}
    for y in reversed(years[:-1]):
        e = rho * e + math.sqrt(1 - rho ** 2) * rng.standard_normal()
        states[y] = math.sqrt(lam) * u + math.sqrt(1 - lam) * e < nd.inv_cdf(min(max(probs[y], 1e-6), 1 - 1e-6))
    return dict(sorted(states.items()))


# ---- employment ---------------------------------------------------------------------------------------------------

def employment_prob(rates: dict, year: int, sex: str, age: int) -> float:
    return band_rate(rates.get(str(year), rates[max(rates)])[sex], age) or 0.0


def panel_working_share(people: list[dict]) -> dict:
    """{sex: {age5: share not 무직}}: the personas work more often than the survey says, so the 2025 level comes from
    the panel itself and the published rates only supply the change over the years."""
    c: dict = {}
    for p in people:
        k = c.setdefault(p["sex"], {}).setdefault(min(int(p["age"]) // 5 * 5, 75), [0, 0])
        k[0] += p.get("occupation") != "무직"
        k[1] += 1
    return {sex: {a: w / n for a, (w, n) in by.items()} for sex, by in c.items()}


def simulate_employment(people: list[dict], seed: int, c: float = EMPLOY_C, lam: float = EMPLOY_LAM) -> dict:
    """{uid: {year: working}} 2017-2025 for ages 19+; 2025 = occupation is not 무직. P(working) in year y = the panel's
    2025 share at the person's age then, moved on the logit scale by the published rate change y -> 2025 at that age."""
    rates = life_context.tables()["history_employment"]
    level = panel_working_share(people)
    out = {}
    for p in people:
        sex = p["sex"]
        probs = {}
        for y in HISTORY_YEARS:
            age = age_at(p, y)
            if age < 19:
                continue
            base = level.get(sex, {}).get(min(age // 5 * 5, 75))
            then, now = employment_prob(rates, y, sex, age), employment_prob(rates, BASE_YEAR, sex, age)
            if base is None or not then or not now:
                continue
            probs[y] = 1 / (1 + math.exp(-(_logit(base) + _logit(then) - _logit(now))))
        if BASE_YEAR not in probs:
            continue
        out[p["uuid"]] = backward_binary(p.get("occupation") != "무직", probs, c, lam,
                                         _rng(seed, "employed", p["uuid"]))
    return out


# ---- residence ----------------------------------------------------------------------------------------------------

def fit_mover_shape() -> float:
    """Shape k of a mean-1 Gamma mobility propensity (theta) such that P(moved in five years) = E[1 - prod(1 - theta
    r_t)] matches the 2005 census share living in another 시도 five years earlier, given that band's five yearly
    in-mover rates (ages 20-64, both sexes). Without it moves are independent across years and the share who ever
    moved is far too high."""
    data = life_context.tables()["history_repeat_movers"]
    rng = np.random.default_rng(11)
    cells = [(v["five_year"], np.array(v["annual"])) for sex in data.values() for b, v in sex.items()
             if 20 <= int(b.rstrip("+")) < 65 and v["five_year"] is not None
             and all(rate is not None for rate in v["annual"])]
    if not cells:
        raise ValueError("no complete repeat-mover cells; cannot fit mobility")
    best = None
    for k in [0.1 * i for i in range(1, 21)]:
        theta = rng.gamma(k, 1 / k, 20000)
        err = 0.0
        for target, rates in cells:
            scaled = np.array([r * propensity_scale(r, k) for r in rates])
            stay = np.prod(1 - np.minimum(np.outer(theta, scaled), 0.95), axis=1)
            err += (float(np.mean(1 - stay)) - target) ** 2
        if best is None or err < best[0]:
            best = (err, k)
    return round(best[1], 2)


_SCALE_CACHE: dict = {}


def propensity_scale(rate: float, k: float) -> float:
    """Multiplier s with E[min(s * theta * rate, 0.95)] = rate for theta ~ Gamma(k, 1/k): the cap on very mobile
    people would otherwise lose part of the published yearly rate."""
    if rate <= 0:
        return 1.0
    key = (round(k, 3), round(math.log(rate), 2))
    if key not in _SCALE_CACHE:
        theta = np.random.default_rng(13).gamma(k, 1 / k, 40000)
        lo, hi = 1.0, 50.0
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if np.minimum(mid * theta * rate, 0.95).mean() < rate else (lo, mid)
        _SCALE_CACHE[key] = (lo + hi) / 2
    return _SCALE_CACHE[key]


def mover_theta(seed: int, uid: str, k: float) -> float:
    return float(_rng(seed, "mover_theta", uid).gamma(k, 1 / k))


def simulate_residence(people: list[dict], seed: int, k: float | None = None) -> dict:
    """{uid: {year: 시도 at the end of that year}} 2017-2025, drawn backwards: in year t a resident of `d` had moved in
    from another 시도 with probability (sex x age in-migration rate) x (d's in-flow rate / the national one); the origin
    follows that year's origin x destination table."""
    mig = life_context.tables()["history_migration"]
    k = k or fit_mover_shape()
    out = {}
    for p in people:
        rng = _rng(seed, "residence", p["uuid"])
        theta = mover_theta(seed, p["uuid"], k)
        here = p["province"]
        path = {BASE_YEAR: here}
        for y in range(BASE_YEAR, HISTORY_YEARS[0], -1):
            m = mig.get(str(y))
            if not m or here not in m["od"]:
                path[y - 1] = here
                continue
            national = sum(m["inflow"].values()) / len(m["inflow"])
            base = (band_rate(m["age"].get(p["sex"], {}), age_at(p, y)) or 0.0) * m["inflow"][here] / national
            if rng.random() < min(theta * base * propensity_scale(base, k), 0.95):
                origins = m["od"][here]
                names, w = list(origins), np.array(list(origins.values()), dtype=float)
                here = names[int(np.searchsorted(np.cumsum(w / w.sum()), rng.random()))]
            path[y - 1] = here
        out[p["uuid"]] = dict(sorted(path.items()))
    return out


# ---- marital status -----------------------------------------------------------------------------------------------

def _norm_marital(m: str | None) -> str | None:
    m = (m or "").replace(" ", "")
    return {"배우자있음": MARRIED, "미혼": SINGLE, "이혼": DIVORCED, "사별": WIDOWED}.get(m)


def status_shares(people: list[dict]) -> dict:
    """{sex: {age5: {status: share}}} in the 2025 panel (the denominator for event rates per person of an age)."""
    counts: dict = {}
    for p in people:
        st = _norm_marital(p.get("marital_status"))
        if st:
            c = counts.setdefault(p["sex"], {}).setdefault(int(p["age"]) // 5 * 5, {})
            c[st] = c.get(st, 0) + 1
    return {sex: {a: {k: v / sum(c.values()) for k, v in c.items()} for a, c in by.items()} for sex, by in counts.items()}


def simulate_marital(people: list[dict], seed: int) -> dict:
    """{uid: {year: status}} 2017-2025 drawn backwards, one year at a time over the whole panel: among those married
    at the end of year t, the share who married during t is marriage rate(sex, age) / share married at that age in
    the panel at t; divorced likewise with the divorce rate; widowed with the spouse's death probability x married /
    widowed at that age. Remarriage is approximated (a marriage at 45+ is half from divorce)."""
    t = life_context.tables()
    marry, divorce, life = t["history_marriage"], t["history_divorce"], t["life_table"]
    people = [p for p in people if _norm_marital(p.get("marital_status"))]
    state = {p["uuid"]: _norm_marital(p["marital_status"]) for p in people}
    paths = {p["uuid"]: {BASE_YEAR: state[p["uuid"]]} for p in people}
    rngs = {p["uuid"]: _rng(seed, "marital", p["uuid"]) for p in people}
    for y in range(BASE_YEAR, HISTORY_YEARS[0], -1):
        cells: dict = {}
        for p in people:
            c = cells.setdefault((p["sex"], age_at(p, y) // 5 * 5), {})
            c[state[p["uuid"]]] = c.get(state[p["uuid"]], 0) + 1
        for p in people:
            uid, age = p["uuid"], age_at(p, y)
            c = cells[(p["sex"], age // 5 * 5)]
            n, st = sum(c.values()), state[uid]
            if st == MARRIED and age >= 19:
                rate = band_rate(marry.get(str(y), {}).get(p["sex"], {}), age) or 0.0
                if rngs[uid].random() < min(rate * n / c[MARRIED], 0.9):
                    state[uid] = SINGLE if age < 45 or rngs[uid].random() < 0.5 else DIVORCED
            elif st == DIVORCED:
                rate = band_rate(divorce.get(str(y), {}).get(p["sex"], {}), age) or 0.0
                if rngs[uid].random() < min(rate * n / c[DIVORCED], 0.9):
                    state[uid] = MARRIED
            elif st == WIDOWED and c.get(MARRIED):
                # widowed during t: spouse death probability x married at that age / widowed at that age
                spouse = "여자" if p["sex"] == "남자" else "남자"
                if rngs[uid].random() < min(death_prob(life, spouse, age) * c[MARRIED] / c[WIDOWED], 0.9):
                    state[uid] = MARRIED
            paths[uid][y - 1] = state[uid]
    return {u: dict(sorted(v.items())) for u, v in paths.items()}


# ---- personal income quintile -----------------------------------------------------------------------------------

def quintile_shares(mob: dict, year: int, sex: str, group: str) -> list[float]:
    """Shares of quintiles 1-5 in `year` for a sex x age group (age group of the prior year, as the table does)."""
    by_year = mob["by_year"]
    if str(year) in by_year:
        cell = by_year[str(year)][sex][group]
        shares = cell["current"]
    else:  # 2017: the prior-year margin of the 2018 table
        shares = by_year[str(year + 1)][sex][group]["prior"]
    if any(x is None for x in shares):
        raise ValueError("unpublished income quintile shares; cannot infer a transition")
    total = sum(shares)
    return [x / total for x in shares]


def _cuts(shares: list[float]) -> np.ndarray:
    return _ppf(np.cumsum(shares)[:4])


def fit_one_year_corr(mob: dict, years: tuple[str, ...] | None = None) -> dict:
    """c per age group: the bivariate-normal correlation whose quintile stay rate matches the group's published stay
    rate (both sexes, all transition years)."""
    rng = np.random.default_rng(7)
    a, b = rng.standard_normal(200_000), rng.standard_normal(200_000)
    out = {}
    for group in AGE_GROUPS:
        targets = []
        for year, by_sex in mob["by_year"].items():
            if years and year not in years:
                continue
            for sex in ("남자", "여자"):
                cell = by_sex[sex][group]
                if any(x is None for x in cell["prior"] + cell["current"]) or cell["direction"].get("stay") is None:
                    continue
                targets.append((cell["prior"], cell["current"], cell["direction"]["stay"]))
        if not targets:
            raise ValueError(f"no complete income mobility cells for {group}")

        def stay(c: float) -> float:
            z2 = c * a + math.sqrt(1 - c * c) * b
            got = []
            for prior, current, _ in targets:
                q1 = np.searchsorted(_cuts([x / sum(prior) for x in prior]), a)
                q2 = np.searchsorted(_cuts([x / sum(current) for x in current]), z2)
                got.append(float(np.mean(q1 == q2)))
            return float(np.mean(got))

        want = float(np.mean([t[2] for t in targets]))
        lo, hi = 0.3, 0.995
        for _ in range(22):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if stay(mid) < want else (lo, mid)
        out[group] = round((lo + hi) / 2, 4)
    return out


def earners(people: list[dict]) -> list[dict]:
    return [p for p in people if p.get("occupation") != "무직"]


def simulate_income_copula(people: list[dict], mob: dict, corr: dict, lam: float, seed: int, reps: int = 1) -> dict:
    """Gaussian-copula quintile paths, kept as the comparison: it cannot fit the asymmetric persistence (the bottom
    quintile is left far more often than the top), so the Markov model below is used. {uid: {year: q}}."""
    out: dict = {}
    cache: dict = {}
    for p in earners(people):
        sex = p["sex"]
        years = [y for y in INCOME_YEARS if age_group(age_at(p, y - 1 if y > 2017 else y))]
        if not years:
            continue
        groups = [age_group(age_at(p, y - 1 if y > 2017 else y)) for y in years]
        cuts = [cache.setdefault((y, sex, g), _cuts(quintile_shares(mob, y, sex, g))) if (y, sex, g) not in cache
                else cache[(y, sex, g)] for y, g in zip(years, groups)]
        lam_t = [min(lam, corr[g] - 1e-4) for g in groups]
        rho_t = [(corr[g] - l) / (1 - l) for g, l in zip(groups, lam_t)]
        rng = _rng(seed, "income_q", p["uuid"])
        runs = []
        for _ in range(reps):
            draws = rng.standard_normal(len(years) + 1)
            z = _ar_path(lam_t, rho_t, draws[0], draws[1:])
            runs.append({y: int(np.searchsorted(c, zt)) + 1 for y, c, zt in zip(years, cuts, z)})
        out[p["uuid"]] = runs if reps > 1 else runs[0]
    return out


def persistence_since_2017(hist: dict, q: int) -> dict:
    """S(k): of those in quintile q in 2017 and observed every year to 2024, share in q for k consecutive years."""
    rows = [h for h in hist if all(y in h for y in INCOME_YEARS) and h[2017] == q]
    out = {}
    for k in range(1, 9):
        out[k] = round(sum(all(h[y] == q for y in INCOME_YEARS[:k]) for h in rows) / max(1, len(rows)), 4)
    return out


def fit_lambda_copula(people: list[dict], mob: dict, corr: dict, seed: int) -> tuple[float, dict]:
    """lam minimising the squared gap to the published 2017-2024 bottom and top quintile persistence curves."""
    target = {q: {int(k): v for k, v in mob["persistence"][f"q{q}"]["since_2017"]["2024"].items()} for q in (1, 5)}
    best = None
    for lam in [x / 20 for x in range(0, 19)]:
        sims = simulate_income_copula(people, mob, corr, lam, seed + 1, reps=6)
        hist = [run for runs in sims.values() for run in runs]
        got = {q: persistence_since_2017(hist, q) for q in (1, 5)}
        err = sum((got[q][k] - target[q][k]) ** 2 for q in (1, 5) for k in range(2, 9))
        if best is None or err < best[0]:
            best = (err, lam, got)
    return best[1], {"fitted": best[2], "target": target}


def transition(mob: dict, year: int, sex: str, group: str) -> np.ndarray:
    """5x5 P(q_t = j | q_{t-1} = i) for a sex x prior-year age group (published joint shares / prior shares)."""
    values = mob["by_year"][str(year)][sex][group]["joint"]
    if any(x is None for row in values for x in row):
        raise ValueError("unpublished joint income shares; cannot infer a transition")
    joint = np.array(values)
    rows = joint.sum(axis=1, keepdims=True)
    return np.where(rows > 0, joint / np.where(rows > 0, rows, 1), np.eye(5))


def anchored(P: np.ndarray, prior: np.ndarray, target: np.ndarray, rounds: int = 50) -> np.ndarray:
    """Re-fit the transition so that this cell's actual prior counts land on the published current shares: rake the
    joint diag(prior) @ P to the target column margin with its rows fixed (keeps the published odds ratios). Without
    it the panel's quintile mix drifts as people age across the 39/40 and 64/65 boundaries."""
    if prior.sum() == 0:
        return P
    J = prior[:, None] * P
    cols = target * prior.sum()
    for _ in range(rounds):
        c = J.sum(axis=0)
        J = J * np.where(c > 0, cols / np.where(c > 0, c, 1), 1)[None, :]
        r = J.sum(axis=1)
        J = J * np.where(r > 0, prior / np.where(r > 0, r, 1), 1)[:, None]
    rows = J.sum(axis=1, keepdims=True)
    return np.where(rows > 0, J / np.where(rows > 0, rows, 1), P)


def simulate_income(people: list[dict], mob: dict, stayers: dict, seed: int, rep: int = 0,
                    employed: dict | None = None, flags: dict | None = None) -> dict:
    """Markov chain on the published transition matrices with a mover-stayer mix: a share `stayers[q]` of those who
    start (or enter the panel) in quintile 1 or 5 never leave it; everyone else moves on a row adjusted so that each
    sex x age x quintile cell still leaves at the published rate. {uid: {year: quintile}}."""
    if employed is not None:
        people = [p for p in people if p["uuid"] in employed]
    else:
        people = earners(people)
    n, ny = len(people), len(INCOME_YEARS)
    sexes = np.array([p["sex"] for p in people])
    u = np.array([_rng(seed, f"income_q{rep}", p["uuid"]).random(ny + 1) for p in people])
    q = np.zeros((n, ny), dtype=int)  # 0 = not followed that year
    stayer = np.zeros(n, dtype=bool)
    for t, year in enumerate(INCOME_YEARS):
        ref = year if t == 0 else year - 1
        groups = np.array([age_group(age_at(p, ref)) or "" for p in people])
        # a person not working this year leaves the income panel; coming back counts as a new entrant
        if employed is not None:
            work_now = np.array([bool(employed[p["uuid"]].get(year)) for p in people])
            groups = np.where(work_now, groups, "")
            q[~work_now, t] = 0
        # stayers stop being stayers once they reach 65 (retirement ends top and bottom spells alike)
        if t:
            old = np.array([age_at(p, ref) >= 65 and age_at(p, ref - 1) < 65 for p in people])
            stayer[old] = False
        # entrants (first followed year): draw from that year's margin
        new = (groups != "") & ((q[:, t - 1] == 0) if t else True)
        for sex in ("남자", "여자"):
            for g in AGE_GROUPS:
                idx = np.where(new & (sexes == sex) & (groups == g))[0]
                if idx.size:
                    cum = np.cumsum(quintile_shares(mob, year, sex, g))
                    q[idx, t] = np.minimum(np.searchsorted(cum, u[idx, t]) + 1, 5)
                    for k in (1, 5):
                        hit = idx[q[idx, t] == k]
                        stayer[hit] = u[hit, ny] < stayers[k]
        if t == 0:
            continue
        moving = (groups != "") & (q[:, t - 1] > 0)
        for sex in ("남자", "여자"):
            for g in AGE_GROUPS:
                cell = moving & (sexes == sex) & (groups == g)
                P = anchored(transition(mob, year, sex, g),
                             np.bincount(q[cell, t - 1], minlength=6)[1:].astype(float),
                             np.array(quintile_shares(mob, year, sex, g)))
                for i in range(5):
                    idx = np.where(moving & (sexes == sex) & (groups == g) & (q[:, t - 1] == i + 1))[0]
                    if not idx.size:
                        continue
                    f = stayer[idx].mean()
                    row = P[i].copy()
                    stay = row[i]
                    m = max(0.0, (stay - f) / (1 - f)) if f < 1 else 1.0
                    off = row.copy()
                    off[i] = 0
                    row_m = off * ((1 - m) / off.sum()) if off.sum() > 0 else np.eye(5)[i]
                    row_m[i] = m
                    cum = np.cumsum(row_m)
                    draw = np.minimum(np.searchsorted(cum, u[idx, t]) + 1, 5)
                    q[idx, t] = np.where(stayer[idx], i + 1, draw)
    if flags is not None:
        flags.update({p["uuid"]: bool(stayer[k]) for k, p in enumerate(people)})
    return {p["uuid"]: {y: int(q[k, t]) for t, y in enumerate(INCOME_YEARS) if q[k, t]}
            for k, p in enumerate(people) if q[k].any()}


def fit_stayers(people: list[dict], mob: dict, seed: int, reps: int = 4, employed: dict | None = None) -> tuple[dict, dict]:
    """Stayer shares for quintiles 1 and 5 fitted to the published 2017-2024 persistence curves S(2..8)."""
    target = {q: {int(k): v for k, v in mob["persistence"][f"q{q}"]["since_2017"]["2024"].items()} for q in (1, 5)}
    grid = [x / 40 for x in range(0, 33)]
    best: dict = {}
    sims_by_s = {}
    for s in grid:
        hist = [h for r in range(reps)
                for h in simulate_income(people, mob, {1: s, 5: s}, seed + 1, rep=r, employed=employed).values()]
        sims_by_s[s] = {q: persistence_since_2017(hist, q) for q in (1, 5)}
    for q in (1, 5):
        err = {s: sum((got[q][k] - target[q][k]) ** 2 for k in range(2, 9)) for s, got in sims_by_s.items()}
        s = min(err, key=err.get)
        best[q] = s
    fitted = {q: sims_by_s[best[q]][q] for q in (1, 5)}
    markov = {q: sims_by_s[0.0][q] for q in (1, 5)}
    return best, {"fitted": fitted, "pure_markov": markov, "target": target}


# ---- smoking ------------------------------------------------------------------------------------------------------

def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def smoking_probs(person: dict, final_prob: float, series: dict, shape: dict, years: list[int] | None = None,
                  district_year: int | None = None) -> dict:
    """P(smoking) by year: the person's 2025 probability shifted on the logit scale by the change in their district's
    rate and in the national sex x age profile between that year and 2025. `district_year` freezes the district rate
    at that year (a forecast made then would not know the later rates)."""
    raw_d = series.get(person["district"], {})
    # three-year moving average: district rates rest on ~900 respondents and jump by a few points from sampling alone
    district = {y: sum(v for k, v in raw_d.items() if abs(int(k) - int(y)) <= 1)
                / sum(1 for k in raw_d if abs(int(k) - int(y)) <= 1) for y in raw_d}
    sex = person["sex"]

    def age_key(age: int) -> str:
        return "19" if age < 30 else str(min(70, age // 10 * 10))

    base_d = district.get(str(BASE_YEAR))
    base_s = shape.get(sex, {}).get(age_key(int(person["age"])))
    out = {}
    for y in years or SMOKING_YEARS:
        age = age_at(person, y)
        if age < 19:
            continue
        shift = 0.0
        dy = str(district_year or y)
        if base_d and district.get(dy):
            shift += _logit(district[dy]) - _logit(base_d)
        s = shape.get(sex, {}).get(age_key(age))
        if base_s and s:
            shift += _logit(s) - _logit(base_s)
        out[y] = 1 / (1 + math.exp(-(_logit(final_prob) + shift)))
    return out


def simulate_smoking(people: list[dict], ctx: dict, seed: int, c: float = SMOKING_C, lam: float = SMOKING_LAM) -> dict:
    """{uid: {year: bool}}; the 2025 state is the life-context draw, earlier years are drawn backwards from it (a
    stationary Gaussian AR(1) is time-reversible)."""
    from statistics import NormalDist
    nd = NormalDist()
    t = life_context.tables()
    series, shape = t["history_smoking"], t["knhanes_smoking"]
    rho = (c - lam) / (1 - lam)
    out = {}
    for p in people:
        a = ctx.get(p["uuid"], {})
        if "smoking" not in a:
            continue
        probs = smoking_probs(p, a["probs"]["smoking"], series, shape)
        years = sorted(probs)
        rng = _rng(seed, "smoking_hist", p["uuid"])
        cut = nd.inv_cdf(min(max(probs[BASE_YEAR], 1e-6), 1 - 1e-6))
        # z_2025 from the normal truncated to the side of the drawn state
        lo, hi = (0.0, nd.cdf(cut)) if a["smoking"] else (nd.cdf(cut), 1.0)
        z_last = nd.inv_cdf(min(max(lo + rng.random() * (hi - lo), 1e-9), 1 - 1e-9))
        u = math.sqrt(lam) * z_last + math.sqrt(1 - lam) * rng.standard_normal()
        e = (z_last - math.sqrt(lam) * u) / math.sqrt(1 - lam)
        states = {BASE_YEAR: bool(a["smoking"])}
        for y in reversed(years[:-1]):
            e = rho * e + math.sqrt(1 - rho ** 2) * rng.standard_normal()
            z = math.sqrt(lam) * u + math.sqrt(1 - lam) * e
            states[y] = z < nd.inv_cdf(min(max(probs[y], 1e-6), 1 - 1e-6))
        out[p["uuid"]] = dict(sorted(states.items()))
    return out


# ---- forward runs ---------------------------------------------------------------------------------------------------

def forward_binary(start: bool, probs: dict, c: float, lam: float, rng: np.random.Generator) -> dict:
    """{year: state} for the years after the first key of `probs`, continuing from its known state (copula)."""
    from statistics import NormalDist
    nd = NormalDist()
    years = sorted(probs)
    rho = (c - lam) / (1 - lam)
    cut = nd.inv_cdf(min(max(probs[years[0]], 1e-6), 1 - 1e-6))
    lo, hi = (0.0, nd.cdf(cut)) if start else (nd.cdf(cut), 1.0)
    z0 = nd.inv_cdf(min(max(lo + rng.random() * (hi - lo), 1e-9), 1 - 1e-9))
    u = math.sqrt(lam) * z0 + math.sqrt(1 - lam) * rng.standard_normal()
    e = (z0 - math.sqrt(lam) * u) / math.sqrt(1 - lam)
    out = {}
    for y in years[1:]:
        e = rho * e + math.sqrt(1 - rho ** 2) * rng.standard_normal()
        out[y] = math.sqrt(lam) * u + math.sqrt(1 - lam) * e < nd.inv_cdf(min(max(probs[y], 1e-6), 1 - 1e-6))
    return out


def death_prob(table: dict, sex: str, age: int) -> float:
    keys = sorted(int(k) for k in table[sex])
    lo = max(k for k in keys if k <= age)
    return table[sex][str(lo)]


def exit_bottom(P: np.ndarray, extra: float) -> np.ndarray:
    """Scenario kernel: `extra` more of the bottom quintile leave it each year, moving up one quintile."""
    P = P.copy()
    move = min(extra, P[0, 0])
    P[0, 0] -= move
    P[0, 1] += move
    return P


def project(people: list[dict], hist: dict, ctx: dict, stayer_flags: dict, seed: int, until: int = 2030,
            bottom_exit_extra: float = 0.0, kernels: dict | None = None, base_year: int = BASE_YEAR) -> dict:
    """Run the panel forward from 2025 to `until` on the latest kernels (2024 income transitions and margins, 2025
    employment levels and district smoking rates, 2025 migration flows, 2025 marriage and divorce rates, 2024 life
    table). Random numbers are keyed by person, year and attribute, so a scenario differs from the baseline only
    through what it changes. Income transitions are re-fitted each year to the 2024 margins on the baseline run and
    those fitted kernels are returned; a scenario passes them back in (`kernels`) so it keeps the baseline's margin
    correction without being pulled back to the margins itself. Returns {"years", "people", "kernels"}.
    `base_year` < 2025 runs a backtest: the start states come from the history at that year and every kernel is the
    one a forecaster had then (income transitions and margins of base_year - 1, the rest of base_year)."""
    t = life_context.tables()
    mob, life = t["history_income_mobility"], t["life_table"]
    mig, marry, divorce = t["history_migration"], t["history_marriage"], t["history_divorce"]
    emp_rates = t["history_employment"]
    level = panel_working_share(people)
    years = list(range(base_year, until + 1))
    inc_year = base_year - 1  # the latest income-mobility table a forecaster had
    alive = {p["uuid"]: True for p in people}
    by_uid = {p["uuid"]: p for p in people}
    # employment and smoking paths (copula continued from the 2025 state)
    emp, smoke = {}, {}
    for p in people:
        h = hist.get(p["uuid"], {})
        if (h.get("employed") or {}).get(base_year) is not None:
            probs = {}
            for y in years:
                age = age_at(p, y)
                base = level.get(p["sex"], {}).get(min(age // 5 * 5, 75)) or 0.01
                if base_year != BASE_YEAR:  # the panel level is a 2025 level: move it to the base year's rate
                    then, now = employment_prob(emp_rates, base_year, p["sex"], age), employment_prob(emp_rates, BASE_YEAR, p["sex"], age)
                    if then and now:
                        base = 1 / (1 + math.exp(-(_logit(base) + _logit(then) - _logit(now))))
                probs[y] = base
            emp[p["uuid"]] = {base_year: h["employed"][base_year],
                              **forward_binary(h["employed"][base_year], probs, EMPLOY_C, EMPLOY_LAM,
                                               _rng(seed, "employed_fwd", p["uuid"]))}
        a = ctx.get(p["uuid"], {})
        start_smoking = a.get("smoking") if base_year == BASE_YEAR else (h.get("smoking") or {}).get(base_year)
        if "smoking" in a and start_smoking is not None:
            probs = smoking_probs(p, a["probs"]["smoking"], t["history_smoking"], t["knhanes_smoking"], years,
                                  district_year=None if base_year == BASE_YEAR else base_year)
            smoke[p["uuid"]] = {base_year: start_smoking, **forward_binary(
                start_smoking, probs, SMOKING_C, SMOKING_LAM, _rng(seed, "smoking_fwd", p["uuid"]))}
    # income quintile: continue from 2024 on the 2024 kernel (2025 is the first projected year)
    q = {u: h["income_q"][inc_year] for u, h in ((u, hist[u]) for u in hist) if (h.get("income_q") or {}).get(inc_year)}
    stay = {u: stayer_flags.get(u, False) for u in q}
    fitted = {} if kernels is None else kernels
    first_bottom = {u for u, v in q.items() if v == 1}
    ever_left = set()
    if base_year == BASE_YEAR:
        province = {p["uuid"]: p["province"] for p in people}
        marital = {p["uuid"]: _norm_marital(p.get("marital_status")) for p in people}
    else:
        province = {p["uuid"]: (hist.get(p["uuid"], {}).get("residence") or {}).get(base_year, p["province"])
                    for p in people}
        marital = {p["uuid"]: (hist.get(p["uuid"], {}).get("marital") or {}).get(base_year)
                   or _norm_marital(p.get("marital_status")) for p in people}
    kern = mob["by_year"][str(inc_year)]
    # income amounts: published levels up to the base year's last table, then each cell's recent compound growth
    levels = extrapolate_levels(t["history_wage_level"], min(inc_year, int(max(t["history_wage_level"]))), until)
    from statistics import NormalDist
    nd = NormalDist()
    amt, erank = {}, {}
    cuts0 = national_cuts([by_uid[u] for u in q], levels[str(inc_year)], inc_year)
    for u in q:
        a0 = (hist[u].get("income_amt") or {}).get(inc_year)
        if a0:
            p = by_uid[u]
            amt[u] = a0
            z0 = nd.inv_cdf(band_rank(p["sex"], age_at(p, inc_year), q[u], levels[str(inc_year)], cuts0, a0))
            erank[u] = (z0 - math.sqrt(RANK_LAM) * _perm(seed, u)) / math.sqrt(1 - RANK_LAM)
    m25 = mig.get(str(base_year)) or mig[max(mig)]
    outflow: dict = {}
    residents: dict = {}
    for d, src in m25["od"].items():
        for o, v in src.items():
            outflow.setdefault(o, {})[d] = v
    for o in outflow:
        residents[o] = sum(m25["od"][o].values()) / m25["inflow"][o] if m25["inflow"].get(o) else None
    national = sum(m25["inflow"].values()) / len(m25["inflow"])
    k = fit_mover_shape()
    thetas = {p["uuid"]: mover_theta(seed, p["uuid"], k) for p in people}
    summary = {}
    for y in years:
        if y > base_year:
            for p in people:
                uid = p["uuid"]
                if alive[uid] and _rng(seed, f"death{y}", uid).random() < death_prob(life, p["sex"], age_at(p, y - 1)):
                    alive[uid] = False
        # income step for every working survivor (2025 included: history ends in 2024)
        cells: dict = {}
        for uid in list(q):
            p = by_uid[uid]
            working = emp.get(uid, {}).get(y, False)
            if not alive[uid] or not working or age_at(p, y - 1) < 19:
                q.pop(uid)
                stay.pop(uid, None)
                continue
            if age_at(p, y - 1) >= 65:  # as in the history: stayer spells end at 65
                stay[uid] = False
            cells.setdefault((p["sex"], age_group(age_at(p, y - 1))), []).append(uid)
        prev = dict(q)  # quintiles at the start of the year: a person who moves up must not be moved again below
        for (sex, g), uids in cells.items():
            # the baseline re-fits to the 2024 margins (without it the top quintile swells to a third by 2030);
            # a scenario reuses the baseline's fitted kernel, since re-fitting its own would cancel the policy
            if kernels is None:
                prior = np.bincount([prev[u] for u in uids], minlength=6)[1:].astype(float)
                fitted[(y, sex, g)] = anchored(transition({"by_year": {"2024": kern}}, 2024, sex, g), prior,
                                               np.array(quintile_shares(mob, inc_year, sex, g)))
            P = fitted.get((y, sex, g))
            if P is None:
                P = transition({"by_year": {"2024": kern}}, 2024, sex, g)
            for i in range(5):
                members = [u for u in uids if prev[u] == i + 1]
                if not members:
                    continue
                f = sum(stay[u] for u in members) / len(members)
                row = P[i].copy()
                m = max(0.0, (row[i] - f) / (1 - f)) if f < 1 else 1.0
                off = row.copy()
                off[i] = 0
                row_m = off * ((1 - m) / off.sum()) if off.sum() > 0 else np.eye(5)[i]
                row_m[i] = m
                if i == 0 and bottom_exit_extra:
                    # the scenario gives every bottom-quintile person, stayers included, the same extra chance of
                    # moving up one quintile; loading it all on the movers would saturate once they all leave
                    row_m = exit_bottom(row_m[None, :], bottom_exit_extra)[0]
                cum = np.cumsum(row_m)
                for u in members:
                    if stay[u] and i == 0 and bottom_exit_extra \
                            and _rng(seed, f"policy{y}", u).random() < bottom_exit_extra:
                        stay[u], q[u] = False, 2
                    elif not stay[u]:
                        q[u] = int(min(np.searchsorted(cum, _rng(seed, f"income{y}", u).random()) + 1, 5))
                    if q[u] != 1 and u in first_bottom:
                        ever_left.add(u)
        # entrants: working now, not followed
        for p in people:
            uid = p["uuid"]
            if alive[uid] and emp.get(uid, {}).get(y) and uid not in q and age_at(p, y - 1) >= 19:
                g = age_group(age_at(p, y - 1))
                cum = np.cumsum(quintile_shares(mob, inc_year, p["sex"], g))
                q[uid] = int(min(np.searchsorted(cum, _rng(seed, f"entry{y}", uid).random()) + 1, 5))
                stay[uid] = False
        # amounts follow the quintile: a new draw inside this year's band, the rank inside the band persisting
        cuts_y = national_cuts([by_uid[u] for u in q], levels[str(y)], y)
        for u in list(amt):
            if u not in q:
                amt.pop(u)
                erank.pop(u, None)
        for u in q:
            p = by_uid[u]
            rng = _rng(seed, f"amt_fwd{y}", u)
            erank[u] = _rank_e_step(erank[u], rng) if u in erank else rng.standard_normal()
            amt[u] = round(draw_amount(p["sex"], age_at(p, y), q[u], levels[str(y)], cuts_y,
                                       nd.cdf(_rank_z(_perm(seed, u), erank[u]))), 1)
        if y > base_year:
            # residence and marital events
            shares: dict = {}
            for p in people:
                if alive[p["uuid"]] and marital[p["uuid"]]:
                    c = shares.setdefault((p["sex"], age_at(p, y) // 5 * 5), {})
                    c[marital[p["uuid"]]] = c.get(marital[p["uuid"]], 0) + 1
            for p in people:
                uid = p["uuid"]
                if not alive[uid]:
                    continue
                age, rng = age_at(p, y), _rng(seed, f"life{y}", uid)
                here = province[uid]
                if residents.get(here):
                    out_rate = sum(outflow[here].values()) / residents[here]
                    base = (band_rate(m25["age"].get(p["sex"], {}), age) or 0.0) * out_rate / national
                    if rng.random() < min(thetas[uid] * base * propensity_scale(base, k), 0.95):
                        names = list(outflow[here])
                        w = np.array([outflow[here][d] for d in names], dtype=float)
                        province[uid] = names[int(np.searchsorted(np.cumsum(w / w.sum()), rng.random()))]
                st = marital[uid]
                c = shares.get((p["sex"], age // 5 * 5), {})
                n = sum(c.values()) or 1
                r_m = band_rate((marry.get(str(base_year)) or marry[max(marry)]).get(p["sex"], {}), age) or 0.0
                r_d = band_rate((divorce.get(str(base_year)) or divorce[max(divorce)]).get(p["sex"], {}), age) or 0.0
                x = rng.random()
                if st in (SINGLE, DIVORCED, WIDOWED) and c.get(st):
                    unmarried = sum(v for k, v in c.items() if k != MARRIED)
                    if unmarried and x < min(r_m * n / unmarried, 0.9):
                        marital[uid] = MARRIED
                elif st == MARRIED and c.get(MARRIED):
                    spouse = "여자" if p["sex"] == "남자" else "남자"
                    if x < min(r_d * n / c[MARRIED], 0.9):
                        marital[uid] = DIVORCED
                    elif x < min(r_d * n / c[MARRIED], 0.9) + death_prob(life, spouse, age):
                        marital[uid] = WIDOWED
        live = [p for p in people if alive[p["uuid"]]]
        working = [p for p in live if emp.get(p["uuid"], {}).get(y)]
        smokers = [p for p in live if smoke.get(p["uuid"], {}).get(y)]
        qs = [q[p["uuid"]] for p in working if p["uuid"] in q]
        summary[y] = {
            "alive": len(live), "mean_age": round(sum(age_at(p, y) for p in live) / len(live), 1),
            "working_share": round(len(working) / len(live), 4),
            "smoking_share": round(len(smokers) / max(1, sum(1 for p in live if p["uuid"] in smoke)), 4),
            "bottom_quintile_share": round(qs.count(1) / max(1, len(qs)), 4),
            "quintile_shares": [round(qs.count(i) / max(1, len(qs)), 4) for i in range(1, 6)],
            "mean_amount": round(float(np.mean(list(amt.values()))), 1) if amt else None,
            "median_amount": round(float(np.median(list(amt.values()))), 1) if amt else None,
            "bottom_2024_ever_left": round(len(ever_left & first_bottom) / max(1, len(first_bottom)), 4),
            "bottom_2024_still_bottom": round(sum(1 for u in first_bottom if q.get(u) == 1)
                                              / max(1, len(first_bottom)), 4),
            "married_share": round(sum(1 for p in live if marital[p["uuid"]] == MARRIED) / len(live), 4),
            "capital_share": round(sum(1 for p in live if province[p["uuid"]] in ("서울", "인천", "경기")) / len(live), 4),
        }
    final = {p["uuid"]: {"alive": alive[p["uuid"]], "age": age_at(p, until), "province": province[p["uuid"]],
                         "marital": marital[p["uuid"]], "working": emp.get(p["uuid"], {}).get(until),
                         "smoking": smoke.get(p["uuid"], {}).get(until), "income_q": q.get(p["uuid"]),
                         "income_amt": amt.get(p["uuid"])}
             for p in people}
    return {"years": summary, "people": final, "kernels": fitted}



# ---- income amounts ------------------------------------------------------------------------------------------------
# The quintile is a rank: it cannot say that everyone earned more in 2023 than in 2019. The amount layer puts a nominal
# annual labour + business income (만원) on every followed person-year. Each year the amount is drawn from the person's
# sex x age-band lognormal (published wage-job mean and median of that year), truncated to the national band of the
# person's quintile that year; the person's rank inside the band persists across years as a Gaussian AR(1), so the
# published distribution of individual year-on-year % changes (7 categories) is a check, not an input. Years beyond
# the last published level extrapolate each cell's recent compound growth.

LEVEL_WINDOW = 5         # years of published levels used for the growth extrapolation
RANK_C = 0.6             # one-year correlation of the within-band rank (fitted: 32-34% of changes within ±10%)
RANK_LAM = 0.0           # permanent share of that rank (person trait + AR(1) noise, as the other copulas). No published
                         # target; 0.3-0.7 leaves the one-year checks and the 4-year change mix unchanged, so 0 is kept
CHANGE_CATS = ("down_50", "down_10_50", "down_0_10", "same", "up_0_10", "up_10_50", "up_50")


def change_category(ratio: float) -> str:
    """The published 7-category band of an amount ratio a_t / a_{t-1} (만원 rounded as the statistic does)."""
    if abs(ratio - 1) < 0.0005:
        return "same"
    if ratio < 0.5:
        return "down_50"
    if ratio < 0.9:
        return "down_10_50"
    if ratio < 1:
        return "down_0_10"
    if ratio < 1.1:
        return "up_0_10"
    if ratio < 1.5:
        return "up_10_50"
    return "up_50"


def wage_band(age: int) -> str:
    return str(min(70, max(20, age // 10 * 10)))


def extrapolate_levels(levels: dict, base_year: int, until: int, window: int = LEVEL_WINDOW) -> dict:
    """Published levels up to `base_year`, then each cell grown at its compound rate over the last `window` years."""
    out = {y: v for y, v in levels.items() if int(y) <= base_year}
    last, first = levels[str(base_year)], levels[str(max(int(min(levels)), base_year - window))]
    span = base_year - int(max(int(min(levels)), base_year - window))
    for y in range(base_year + 1, until + 1):
        out[str(y)] = {sex: {band: {k: round(last[sex][band][k] * (last[sex][band][k] / first[sex][band][k]) ** ((y - base_year) / span), 4)
                                    for k in ("mean", "median")} for band in last[sex]} for sex in last}
    return out


def _lognormal(level: dict) -> tuple[float, float]:
    mu = math.log(level["median"] * 12)
    sigma = math.sqrt(max(2 * math.log(level["mean"] / level["median"]), 1e-4))
    return mu, sigma


def national_cuts(people: list[dict], levels: dict, year: int) -> list[float]:
    """Quintile cut points (annual 만원) of the mixture of sex x age-band lognormals weighted by the people given."""
    from statistics import NormalDist
    nd = NormalDist()
    cells: dict = {}
    for p in people:
        k = (p["sex"], wage_band(age_at(p, year)))
        cells[k] = cells.get(k, 0) + 1
    n = sum(cells.values())
    params = {k: _lognormal(levels[k[0]][k[1]]) for k in cells}

    def cdf(x: float) -> float:
        return sum(w / n * nd.cdf((math.log(x) - params[k][0]) / params[k][1]) for k, w in cells.items())

    cuts = []
    for target in (0.2, 0.4, 0.6, 0.8):
        lo, hi = 1.0, 1e6
        for _ in range(60):
            mid = math.sqrt(lo * hi)
            lo, hi = (mid, hi) if cdf(mid) < target else (lo, mid)
        cuts.append(round(lo, 1))
    return cuts


def _band(sex: str, age: int, q: int, levels: dict, cuts: list[float]) -> tuple[float, float, float, float]:
    from statistics import NormalDist
    nd = NormalDist()
    mu, sigma = _lognormal(levels[sex][wage_band(age)])
    lo = 0.0 if q == 1 else nd.cdf((math.log(cuts[q - 2]) - mu) / sigma)
    hi = 1.0 if q == 5 else nd.cdf((math.log(cuts[q - 1]) - mu) / sigma)
    return mu, sigma, lo, hi


def draw_amount(sex: str, age: int, q: int, levels: dict, cuts: list[float], u: float) -> float:
    """An annual amount from the person's sex x age-band lognormal, truncated to the national band of quintile q;
    `u` in (0, 1) is the rank inside the band."""
    from statistics import NormalDist
    mu, sigma, lo, hi = _band(sex, age, q, levels, cuts)
    if hi - lo < 1e-9:  # the band is far out in this cell's tail: take the band's edge
        return cuts[q - 2] if q > 1 else cuts[0] * 0.5
    return math.exp(mu + sigma * NormalDist().inv_cdf(min(max(lo + u * (hi - lo), 1e-9), 1 - 1e-9)))


def band_rank(sex: str, age: int, q: int, levels: dict, cuts: list[float], amount: float) -> float:
    """Inverse of draw_amount: the rank of `amount` inside its band."""
    from statistics import NormalDist
    mu, sigma, lo, hi = _band(sex, age, q, levels, cuts)
    if hi - lo < 1e-9:
        return 0.5
    f = NormalDist().cdf((math.log(max(amount, 1e-6)) - mu) / sigma)
    return min(max((f - lo) / (hi - lo), 1e-6), 1 - 1e-6)


def _perm(seed: int, uid: str) -> float:
    """The person's permanent rank component (the same in the history and in every forward run)."""
    return float(_rng(seed, "amt_perm", uid).standard_normal())


def _rank_rho(c: float = RANK_C, lam: float = RANK_LAM) -> float:
    return (c - lam) / (1 - lam)


def _rank_z(perm: float, e: float, lam: float = RANK_LAM) -> float:
    return math.sqrt(lam) * perm + math.sqrt(1 - lam) * e


def _rank_e_step(e: float, rng: np.random.Generator, c: float = RANK_C, lam: float = RANK_LAM) -> float:
    rho = _rank_rho(c, lam)
    return rho * e + math.sqrt(1 - rho ** 2) * rng.standard_normal()


def simulate_amounts(people: list[dict], income: dict, seed: int, levels: dict, c: float = RANK_C,
                     lam: float = RANK_LAM) -> dict:
    """{uid: {year: annual 만원}} for every followed person-year 2017-2024. The within-band rank is
    sqrt(lam) * person + sqrt(1 - lam) * e, e an AR(1) with one-year correlation c overall; e restarts when the
    person re-enters the panel, the person component does not."""
    from statistics import NormalDist
    nd = NormalDist()
    by_uid = {p["uuid"]: p for p in people}
    years = sorted({y for h in income.values() for y in h})
    cuts = {y: national_cuts([by_uid[u] for u, h in income.items() if h.get(y)], levels[str(y)], y) for y in years}
    amt: dict = {}
    e: dict = {}
    for y in years:
        for u, h in income.items():
            q = h.get(y)
            if not q:
                e.pop(u, None)
                continue
            rng = _rng(seed, f"amt{y}", u)
            e[u] = _rank_e_step(e[u], rng, c, lam) if u in e else rng.standard_normal()
            p = by_uid[u]
            amt.setdefault(u, {})[y] = round(draw_amount(p["sex"], age_at(p, y), q, levels[str(y)], cuts[y],
                                                         nd.cdf(_rank_z(_perm(seed, u), e[u], lam))), 1)
    return amt


def amount_checks(people: list[dict], amt: dict, levels: dict, changes: dict, income: dict) -> dict:
    """Panel mean/median by sex x band against the published levels (2018, 2024); the panel's year-on-year change
    categories against the published 7-category shares (panel-weighted, 2024 and all years); mean growth 2018 -> 2024."""
    by_uid = {p["uuid"]: p for p in people}
    out: dict = {"levels": {}, "changes": {}, "growth": {}}
    for year in (2018, 2024):
        rows: dict = {}
        for u, d in amt.items():
            if year in d:
                p = by_uid[u]
                rows.setdefault((p["sex"], wage_band(age_at(p, year))), []).append(d[year] / 12)
        out["levels"][str(year)] = {f"{s} {b}": {"panel_mean": round(float(np.mean(v)), 1), "panel_median": round(float(np.median(v)), 1),
                                                 "official_mean": levels[str(year)][s][b]["mean"],
                                                 "official_median": levels[str(year)][s][b]["median"], "n": len(v)}
                                    for (s, b), v in sorted(rows.items())}
    for label, yrs in (("2024", [2024]), ("all", list(range(2018, 2025)))):
        panel = {c: 0 for c in CHANGE_CATS}
        official = {c: 0.0 for c in CHANGE_CATS}
        n = 0
        by_q = {str(q): {"panel": {c: 0 for c in CHANGE_CATS}, "official": {c: 0.0 for c in CHANGE_CATS}, "n": 0} for q in range(1, 6)}
        for y in yrs:
            for u, d in amt.items():
                if y in d and y - 1 in d:
                    p = by_uid[u]
                    cat = change_category(d[y] / d[y - 1])
                    q0 = str(income[u][y - 1])
                    shares = changes.get(str(y), {}).get(p["sex"], {}).get(age_group(age_at(p, y - 1)), {}).get(q0)
                    if not shares:
                        continue
                    n += 1
                    panel[cat] += 1
                    by_q[q0]["panel"][cat] += 1
                    by_q[q0]["n"] += 1
                    for c in CHANGE_CATS:
                        official[c] += shares.get(c, 0.0)
                        by_q[q0]["official"][c] += shares.get(c, 0.0)
        out["changes"][label] = {"n": n, "panel": {c: round(panel[c] / n, 4) for c in CHANGE_CATS},
                                 "official": {c: round(official[c] / n, 4) for c in CHANGE_CATS},
                                 "within_10pct": {"panel": round(sum(panel[c] for c in ("down_0_10", "same", "up_0_10")) / n, 4),
                                                  "official": round(sum(official[c] for c in ("down_0_10", "same", "up_0_10")) / n, 4)},
                                 "by_prior_quintile": {q: {"n": v["n"], "panel": {c: round(v["panel"][c] / max(1, v["n"]), 4) for c in CHANGE_CATS},
                                                           "official": {c: round(v["official"][c] / max(1, v["n"]), 4) for c in CHANGE_CATS}}
                                                       for q, v in by_q.items()}}
    both = [u for u, d in amt.items() if 2018 in d and 2024 in d]
    out["growth"] = {"n": len(both),
                     "panel_mean_2018_2024": round(float(np.mean([amt[u][2024] for u in both]) / np.mean([amt[u][2018] for u in both])), 4),
                     "panel_median_2018_2024": round(float(np.median([amt[u][2024] for u in both]) / np.median([amt[u][2018] for u in both])), 4)}
    return out


# ---- lines --------------------------------------------------------------------------------------------------------

def fmt_amount(annual: float) -> str:
    """Annual 만원 rounded to 10만원, e.g. 2,350만원."""
    return f"{int(round(annual / 10) * 10):,}만원"


def history_lines(h: dict) -> list[str]:
    """Only changes are stated: a staying state says nothing (it is already in the current-state lines)."""
    out = []
    sm = {int(k): v for k, v in (h.get("smoking") or {}).items()}
    if sm and not sm[BASE_YEAR] and any(sm.values()):
        last = max(y for y, v in sm.items() if v)
        out.append(f"- 흡연 이력: {last}년까지 담배를 피우다 끊음")
    q = {int(k): v for k, v in (h.get("income_q") or {}).items()}
    a = {int(k): v for k, v in (h.get("income_amt") or {}).items()}
    if 2023 in q and 2024 in q and q[2023] != q[2024]:
        if 2023 in a and 2024 in a:
            out.append(f"- 개인 근로·사업소득: 2023년 연 {fmt_amount(a[2023])}({q[2023]}분위) → 2024년 연 {fmt_amount(a[2024])}({q[2024]}분위)")
        else:
            out.append(f"- 개인 근로·사업소득 분위: 2023년 {q[2023]}분위 → 2024년 {q[2024]}분위")
    if all(q.get(y) == 1 for y in INCOME_YEARS):
        out.append("- 2017~2024년 매년 개인 근로·사업소득 하위 20%")
    res = {int(k): v for k, v in (h.get("residence") or {}).items()}
    moves = [(y, res[y - 1], res[y]) for y in sorted(res) if y - 1 in res and res[y] != res[y - 1]]
    if moves:
        y, a, b = moves[-1]
        out.append(f"- 이사: {y}년 {a}에서 {b}(으)로 옮김")
    mar = {int(k): v for k, v in (h.get("marital") or {}).items()}
    for y in sorted(mar):
        if y - 1 in mar and mar[y] != mar[y - 1] and mar[y] in (MARRIED, DIVORCED):
            out.append(f"- {'결혼' if mar[y] == MARRIED else '이혼'}: {y}년")
    emp = {int(k): v for k, v in (h.get("employed") or {}).items()}
    if emp.get(BASE_YEAR) is not None and emp.get(BASE_YEAR - 1) is not None and emp[BASE_YEAR] != emp[BASE_YEAR - 1]:
        out.append("- 일: 2025년에 " + ("일을 시작함" if emp[BASE_YEAR] else "일을 그만둠"))
    return out


# ---- state blocks for the service ("5년 뒤 보기")
# Rule from the 2019->2023 backtest (scripts/backtest_2019.py): income is given as a
# state ("2030년 연 3,370만원"), never as a change sentence — Jev reacts to a stated loss about twice as strongly as
# to a gain, so change lines push the whole panel the wrong way. Both the base-year and the future profile carry the
# same block so that the two arms differ only in the states, not in the format.
FUTURE_YEAR = config.FUTURE_YEAR
WORK_ADDON_PREFIXES = ("- 일하는 형태:", "- 맞벌이 부부", "- 출퇴근 수단:")


def now_state(person: dict, h: dict) -> dict:
    """The base-year (2025) state of a panel member from the life history, in the forecast's state format."""
    g = lambda key, year: (h.get(key) or {}).get(str(year))  # noqa: E731
    return {"alive": True, "age": int(person["age"]), "province": g("residence", BASE_YEAR) or person["province"],
            "marital": g("marital", BASE_YEAR), "working": g("employed", BASE_YEAR),
            "income_q": g("income_q", BASE_YEAR - 1), "income_amt": g("income_amt", BASE_YEAR - 1)}


def state_block(state: dict, year: int, amount_year: int | None = None) -> str:
    """Profile lines for a person's state in `year`: states only, no change sentences."""
    lines = [f"[{year}년 기준 생활 상태 — 공공통계의 연간 변화 확률로 굴린 시뮬레이션 가정이며 이 사람에 대한 사실이 아님]",
             f"- 지금은 {year}년이고, 이 사람은 {state['age']}세입니다.", f"- 사는 곳: {state['province']}"]
    if state.get("marital"):
        lines.append(f"- 혼인: {state['marital']}")
    if state.get("working") is not None:
        lines.append("- 일: " + ("일함" if state["working"] else "일하지 않음"))
    if state.get("income_amt") and state.get("working") is not False:
        lines.append(f"- 개인 근로·사업소득: {amount_year or year}년 연 {fmt_amount(state['income_amt'])}")
    return "\n".join(lines)


def future_profile(person: dict, then: dict, year: int = FUTURE_YEAR) -> str:
    """The persona text moved to `year`: header facts (age, marital, residence, job) follow the projected state and
    add-on work lines are dropped for someone who no longer works. The narrative is left as written."""
    text = re.sub(r"(성별·나이: [^,\n]+, )\d+세", lambda m: f"{m.group(1)}{then['age']}세", person["profile"])
    if then.get("marital"):
        text = re.sub(r"(혼인: )[^\n/]*?(?=\s*(?:/|\n|$))", lambda m: m.group(1) + then["marital"], text, count=1)
    if then.get("province") and then["province"] != person["province"]:
        text = re.sub(r"사는 곳: [^\n]+", f"사는 곳: {then['province']}", text, count=1)
    if then.get("working") is False:
        text = re.sub(r"(직업: [^\n]+)", lambda m: f"{m.group(1)} ({year}년 현재는 일하지 않음)", text, count=1)
        text = "\n".join(line for line in text.splitlines() if not line.startswith(WORK_ADDON_PREFIXES))
    return text + "\n\n" + state_block(then, year)


def state_changes(now: dict, then: dict) -> list[str]:
    """Which states differ between the two years (for the result screen's decomposition)."""
    return [k for k in ("working", "province", "marital", "income_q") if now.get(k) is not None and then.get(k) is not None
            and now[k] != then[k]]


# ---- "대상 규칙으로 나눠 보기": who a rule applies to, judged on a state
RULE_KEYS = ("income_max_manwon", "income_min_manwon", "working", "age_min", "age_max", "capital", "note")


def eligible(rule: dict, state: dict) -> bool | None:
    """Does `state` (now_state() / forecast format) satisfy `rule`? True / False / None (cannot judge).
    Any axis that is definitely violated wins (False); otherwise an undecidable axis gives None. The income axis is
    undecidable when the state block shows no income line (no amount, or not working) — we never judge on a figure
    Jev has not seen. The capital-region axis is derived from the state's province."""
    from pp import config

    undecided = False
    if rule.get("income_max_manwon") is not None or rule.get("income_min_manwon") is not None:
        amt = state.get("income_amt")
        if not amt or state.get("working") is False:
            undecided = True
        else:
            if rule.get("income_max_manwon") is not None and amt > rule["income_max_manwon"]:
                return False
            if rule.get("income_min_manwon") is not None and amt < rule["income_min_manwon"]:
                return False
    if rule.get("working") is not None:
        if state.get("working") is None:
            undecided = True
        elif bool(state["working"]) != bool(rule["working"]):
            return False
    age = state.get("age")
    if rule.get("age_min") is not None and age is not None and age < rule["age_min"]:
        return False
    if rule.get("age_max") is not None and age is not None and age > rule["age_max"]:
        return False
    if rule.get("capital") is not None:
        region = config.REGION_OF.get(state.get("province"))
        if region is None:
            undecided = True
        elif (region == "수도권") != bool(rule["capital"]):
            return False
    return None if undecided else True


def rule_text(rule: dict) -> str:
    """The rule as one Korean sentence, the single source for the screen and the copy text."""
    parts = []
    lo, hi = rule.get("income_min_manwon"), rule.get("income_max_manwon")
    if lo is not None and hi is not None:
        parts.append(f"개인 근로·사업소득 연 {lo:,}~{hi:,}만 원")
    elif hi is not None:
        parts.append(f"개인 근로·사업소득 연 {hi:,}만 원 이하")
    elif lo is not None:
        parts.append(f"개인 근로·사업소득 연 {lo:,}만 원 이상")
    if rule.get("working") is not None:
        parts.append("일함" if rule["working"] else "일하지 않음")
    a, b = rule.get("age_min"), rule.get("age_max")
    if a is not None and b is not None:
        parts.append(f"만 {a}~{b}세")
    elif b is not None:
        parts.append(f"만 {b}세 이하")
    elif a is not None:
        parts.append(f"만 {a}세 이상")
    if rule.get("capital") is not None:
        parts.append("수도권" if rule["capital"] else "비수도권")
    return " · ".join(parts)
