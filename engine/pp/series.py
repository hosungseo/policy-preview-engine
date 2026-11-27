"""Jev-only policy series: a fixed stratified panel answers every measure twice — the measure alone, and with the
earlier measures' one-line summaries — plus a one-off tenure estimate. No LLM. Every step appends to files under
runs/series-<id>[-tag]/ and resumes where it stopped."""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import random

from . import config, housing_context, jev, panel, personas, prompts, regulated, series_analyze, series_questions

CONDITIONS = ("alone", "context")
PANEL_FIELDS = ("uuid", "sex", "age", "province", "district", "occupation", "education_level", "family_type",
                "housing_type")
MAX_FAILURE_RATE = 0.01
WORKERS = 24


class SeriesError(RuntimeError):
    pass


def _read(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def people_ko(n: int) -> str:
    """20000 -> "2만 명", 2500 -> "2,500명"."""
    return f"{n // 10000}만 명" if n >= 10000 and n % 10000 == 0 else f"{n:,}명"


def load_series(path: Path) -> dict:
    s = _read(path)
    for key in ("id", "title", "panel", "measures", "regulated", "official_tenure"):
        if not s.get(key):
            raise ValueError(f"series file missing {key!r}")
    dates = [m["date"] for m in s["measures"]]
    if dates != sorted(dates):
        raise ValueError("measures must be listed in date order")
    for m in s["measures"]:
        for key in ("id", "date", "short", "title", "agency", "text", "summary"):
            if not m.get(key):
                raise ValueError(f"measure {m.get('id')!r} missing {key!r}")
        if not (m.get("source") or {}).get("url"):
            raise ValueError(f"measure {m['id']} has no source url")
        series_questions.measure_segments(m["text"], m.get("provisions"))  # raises when the excerpt has too many provisions
    return s


def earlier_summaries(measures: list[dict], index: int) -> list[str]:
    return [f"{m['date']} {m['short']} {m['title']}: {m['summary']}" for m in measures[:index]]


def measure_state(measure: dict, person: dict, earlier: list[str]) -> dict:
    """Without earlier measures the state is the measure alone, so the first measure's two conditions are one request."""
    state = {"policy": {"title": measure["title"], "date": measure["date"], "text": measure["text"]},
             "person": prompts.persona_profile(person)}
    if earlier:
        state["earlier_measures"] = earlier
    return state


def subsample(people: list[dict], n: int, seed: int) -> list[dict]:
    """n people from a panel, keeping its province × age band × sex strata in proportion (seeded)."""
    strata: dict[tuple, list[dict]] = {}
    for p in sorted(people, key=lambda x: x["uuid"]):
        strata.setdefault((p["province"], config.age_band(int(p["age"])), p["sex"]), []).append(p)
    seats = panel.allocate({k: len(v) for k, v in strata.items()}, n)
    rng = random.Random(seed)
    return [p for key in sorted(strata, key=str) for p in rng.sample(strata[key], seats[key])]


def read_rows(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["uuid"]] = row
    return rows


def ask_all(people: list[dict], out_path: Path, make_state: Callable[[dict], dict], questions: dict,
            summarize: Callable[[dict], dict], *, label: str, workers: int = WORKERS) -> tuple[list[dict], list[dict]]:
    """One Jev call per person, appended to out_path as each finishes; people already in the file are skipped."""
    done = read_rows(out_path)
    todo = [p for p in people if p["uuid"] not in done]
    lock = threading.Lock()
    failures: list[dict] = []

    def one(person: dict) -> dict:
        return {"uuid": person["uuid"], **summarize(jev.evaluate(make_state(person), questions, label=label))}

    with ThreadPoolExecutor(max_workers=workers) as pool, open(out_path, "a", encoding="utf-8") as sink:
        futures = {pool.submit(one, p): p for p in todo}
        for future in as_completed(futures):
            person = futures[future]
            try:
                row = future.result()
            except (jev.JevError, KeyError, ValueError) as e:
                failures.append({"uuid": person["uuid"], "error": str(e)[:300]})
                continue
            with lock:
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
                done[row["uuid"]] = row
    return [done[p["uuid"]] for p in people if p["uuid"] in done], failures


def validate_bundle(b: dict, *, n_measures: int) -> list[str]:
    errors: list[str] = []
    if len(b["measures"]) != n_measures:
        errors.append(f"{len(b['measures'])} measures in the bundle, {n_measures} in the series")
    for m in b["measures"]:
        for cond in CONDITIONS:
            st = m["conditions"].get(cond)
            if not st:
                errors.append(f"{m['id']}: no {cond} results")
                continue
            for kind in ("province", "region", "age_band", "sex", *(k for k in ("price_band",) if k in st["groups"])):
                total = sum(g["n"] for g in st["groups"][kind])
                if total != st["n"]:
                    errors.append(f"{m['id']} {cond} {kind}: groups add up to {total}, not {st['n']}")
    if '"uuid"' in json.dumps(b, ensure_ascii=False):
        errors.append("per-person rows leaked into the bundle")
    for p in b["regulated"]["periods"]:
        if not p.get("source"):
            errors.append(f"regulated period {p['from']} has no source")
    official = b["tenure"]["official"]
    if not official.get("year") or not official.get("source"):
        errors.append("official tenure figures need a year and a source")
    return errors


class SeriesRun:
    """`housing=True` gives every person a tenure drawn from official statistics (instead of asking Jev) and adds
    the local housing-market block to every measure question; `panel_from` takes the panel as a stratified
    subsample of another run's panel, so answers pair up with that run's; `export_id` names the bundle."""

    def __init__(self, series_path: Path, *, n: int | None = None, tag: str = "", workers: int = WORKERS,
                 housing: bool = False, panel_from: str | None = None, export_id: str | None = None):
        self.path = Path(series_path)
        self.series = load_series(self.path)
        self.n = n or int(self.series["panel"]["n"])
        self.seed = int(self.series["panel"]["seed"])
        self.workers = workers
        self.dir = config.runs_dir() / (f"series-{self.series['id']}" + (f"-{tag}" if tag else ""))
        (self.dir / "answers").mkdir(parents=True, exist_ok=True)
        meta_path = self.dir / "meta.json"
        self.meta = _read(meta_path) if meta_path.exists() else {
            "created_at": _now(), "provider": jev.provider(), "stages": [], "jev_usage": {}, "failures": {}}
        if self.meta["provider"] != jev.provider():
            raise SeriesError(f"{self.dir.name} used Jev provider {self.meta['provider']}, now {jev.provider()}")
        jev.reset_usage()  # usage counters are per process; count only this run's calls
        self._people: list[dict] | None = None
        self.housing = housing
        self.panel_from = panel_from
        self.export_id = export_id or self.series["id"]
        self._assigned: dict[str, dict] | None = None

    def _save_meta(self) -> None:
        _write(self.dir / "meta.json", self.meta)

    def _stage(self, name: str, seconds: float) -> None:
        """Add this sitting's time and Jev usage to the stage totals (a stage can run over several sittings)."""
        prev_seconds = next((s["seconds"] for s in self.meta["stages"] if s["name"] == name), 0.0)
        self.meta["stages"] = [s for s in self.meta["stages"] if s["name"] != name] + [
            {"name": name, "seconds": round(prev_seconds + seconds, 1), "finished_at": _now()}]
        usage = self.meta["jev_usage"].setdefault(name, {})
        for label, u in jev.usage().items():
            acc = usage.setdefault(label, {"calls": 0, "input_tokens": 0, "call_seconds": 0.0, "cost_usd": 0.0, "cached": 0})
            acc["calls"] += u["calls"]
            acc["input_tokens"] += u["input_tokens"]
            acc["cached"] += u.get("cached", 0)
            acc["call_seconds"] = round(acc["call_seconds"] + u["seconds"], 3)
            acc["cost_usd"] = jev.cost_usd(acc["input_tokens"])
        jev.reset_usage()
        self._save_meta()

    def _check(self, failures: list[dict], n: int, key: str) -> None:
        self.meta["failures"][key] = len(failures)
        if failures:
            _write(self.dir / f"failures-{key}.json", failures)
        if n and len(failures) / n > MAX_FAILURE_RATE:
            self._save_meta()
            raise SeriesError(f"{key}: {len(failures)} of {n} calls failed; rerun to resume")

    def people(self) -> list[dict]:
        """Panel members with the full persona text the Jev state needs (read from the DB once per process)."""
        if self._people is None:
            conn = personas.connect()
            path = self.dir / "panel.json"
            if path.exists():
                saved = _read(path)
                if saved["n"] != self.n:
                    raise SeriesError(f"{self.dir.name} holds a {saved['n']}-person panel; use another --tag for {self.n}")
                uuids = [p["uuid"] for p in saved["people"]]
                self._people = personas.fetch(conn, personas.ids_for_uuids(conn, uuids))
            elif self.panel_from:
                source = _read(config.runs_dir() / self.panel_from / "panel.json")["people"]
                if len(source) < self.n:
                    raise SeriesError(f"{self.panel_from} has only {len(source)} people")
                uuids = [p["uuid"] for p in subsample(source, self.n, self.seed)]
                self._people = personas.fetch(conn, personas.ids_for_uuids(conn, uuids))
                _write(path, {"n": len(self._people), "seed": self.seed, "strata": ["province", "age_band", "sex"],
                              "from": self.panel_from,
                              "people": [{k: r[k] for k in PANEL_FIELDS} for r in self._people]})
            else:
                started = time.time()
                index = personas.PersonaIndex.load(conn)
                self._people = personas.fetch(conn, panel.sample_representative(index.strata(), self.n, seed=self.seed))
                _write(path, {"n": len(self._people), "seed": self.seed, "strata": ["province", "age_band", "sex"],
                              "people": [{k: r[k] for k in PANEL_FIELDS} for r in self._people]})
                self._stage("panel", time.time() - started)
        return self._people

    def assigned(self) -> dict[str, dict]:
        """uuid -> {"tenure", "multi_home"} for a housing run (from tenure.jsonl)."""
        if self._assigned is None:
            self._assigned = {u: {"tenure": r["assigned"], "multi_home": r.get("multi_home")}
                              for u, r in read_rows(self.dir / "tenure.jsonl").items()}
        return self._assigned

    def stage_tenure(self) -> None:
        people = self.people()
        started = time.time()
        if self.housing:
            path = self.dir / "tenure.jsonl"
            done = read_rows(path)
            with open(path, "a", encoding="utf-8") as sink:
                for p in people:
                    if p["uuid"] in done:
                        continue
                    a = housing_context.assign(p)
                    onehot = {k: 0.0 for k in series_questions.TENURE}
                    onehot["other" if a["tenure"] == "free" else a["tenure"]] = 1.0
                    sink.write(json.dumps({"uuid": p["uuid"], "tenure": onehot, "assigned": a["tenure"],
                                           "probs": a["probs"], "multi_home": a["multi_home"]}, ensure_ascii=False) + "\n")
            self._assigned = None
            self._stage("tenure", time.time() - started)
            print(f"[series] tenure assigned from official statistics: {len(self.assigned())}/{len(people)}", flush=True)
            return
        rows, failures = ask_all(people, self.dir / "tenure.jsonl", lambda p: {"person": prompts.persona_profile(p)},
                                 series_questions.tenure_question(), series_questions.summarize_tenure,
                                 label="tenure", workers=self.workers)
        self._check(failures, len(people), "tenure")
        self._stage("tenure", time.time() - started)
        print(f"[series] tenure: {len(rows)}/{len(people)}", flush=True)

    def stage_measures(self, only: tuple[str, ...] = ()) -> None:
        people = self.people()
        measures = self.series["measures"]
        for i, m in enumerate(measures):
            if only and m["id"] not in only:
                continue
            segs = series_questions.measure_segments(m["text"], m.get("provisions"))
            qs = series_questions.measure_questions(segs)
            for cond in CONDITIONS:
                earlier = earlier_summaries(measures, i) if cond == "context" else []
                started = time.time()
                rows, failures = ask_all(
                    people, self.dir / "answers" / f"{m['id']}__{cond}.jsonl",
                    lambda p, m=m, e=earlier: self.state(m, p, e), qs,
                    lambda a, s=segs: series_questions.summarize_measure(a, s), label=cond, workers=self.workers)
                self._check(failures, len(people), f"{m['id']}__{cond}")
                self._stage("measures", time.time() - started)
                print(f"[series] {m['short']} {cond}: {len(rows)}/{len(people)} in {time.time() - started:.0f}s",
                      flush=True)

    def state(self, measure: dict, person: dict, earlier: list[str]) -> dict:
        st = measure_state(measure, person, earlier)
        if self.housing:
            st["housing"] = housing_context.housing_block(person, self.assigned()[person["uuid"]], measure["id"],
                                                          housing_context.load_market())
        return st

    def export(self) -> Path:
        base = self.path.parent
        periods = regulated.load(base / self.series["regulated"])
        official = _read(base / self.series["official_tenure"])
        light = {p["uuid"]: p for p in _read(self.dir / "panel.json")["people"]}
        tenure = read_rows(self.dir / "tenure.jsonl")
        people = {u: {**p, "tenure": tenure[u]["tenure"]} for u, p in light.items() if u in tenure}
        market = housing_context.load_market() if self.housing else {}
        if self.housing:
            for p in people.values():
                p["price_band"] = housing_context.price_band(p["district"], market)
        # Groups for the before/after comparison: the assigned tenure's label and the price band.
        labels = {key: label for key, (label, _) in series_questions.TENURE.items()}
        compare = {u: {"price_band": p.get("price_band"), "tenure": labels[max(p["tenure"], key=p["tenure"].get)]}
                   for u, p in people.items()}
        measures = []
        for m in self.series["measures"]:
            segs = series_questions.measure_segments(m["text"], m.get("provisions"))
            reg = {u: regulated.status(p["district"], m["date"], periods) for u, p in people.items()}
            rows = {}
            for cond in CONDITIONS:
                got = [r for u, r in read_rows(self.dir / "answers" / f"{m['id']}__{cond}.jsonl").items() if u in people]
                if len(got) < (1 - MAX_FAILURE_RATE) * len(people):
                    raise SeriesError(f"{m['id']} {cond}: only {len(got)} of {len(people)} answers")
                rows[cond] = got
            stats = {cond: series_analyze.condition_stats(rows[cond], people, segs, reg) for cond in CONDITIONS}
            measures.append({
                **{k: m[k] for k in ("id", "date", "short", "title", "agency", "summary", "text")},
                "source": {k: m["source"][k] for k in ("url", "file", "note", "title", "provider", "license", "text_kind")
                           if k in m["source"]},
                "segments": [{"id": s["id"], "label": s["label"]} for s in segs],
                "conditions": stats,
                "effect": series_analyze.paired_effect(rows["alone"], rows["context"], people, reg),
                "top_reserve": series_analyze.top_reserve(stats["alone"]),
                **({"housing_examples": housing_context.examples(m["id"], market)} if self.housing else {}),
                **({"before_after": series_analyze.before_after(
                    read_rows(config.runs_dir() / self.panel_from / "answers" / f"{m['id']}__alone.jsonl"),
                    rows["alone"], compare, ("price_band", "tenure"))} if self.housing and self.panel_from else {}),
            })
        bundle = {
            "id": self.export_id, "title": self.series["title"],
            "subtitle": self.series.get("subtitle", "").replace("{n}", people_ko(len(people))),
            "created_at": self.meta["created_at"], "provider": self.meta["provider"],
            "panel": {"n": len(people), "seed": self.seed, "strata": ["province", "age_band", "sex"]},
            "order": series_analyze.ORDER,
            "kind_label": {**series_analyze.KIND_LABEL, **({"tenure": "점유 형태(배정)"} if self.housing else {})},
            "housing_labels": {k: label for k, (label, _) in series_questions.HOUSING.items()},
            "measures": measures,
            "tenure": {"labels": {k: label for k, (label, _) in series_questions.TENURE.items()},
                       "overall": series_analyze.tenure_overall(people),
                       "provinces": series_analyze.tenure_by_province(people, official),
                       "official": {k: official[k] for k in ("year", "survey", "unit", "publisher", "source", "note", "national")
                                    if k in official}},
            "regulated": {"periods": periods},
            **({"housing_context": {
                "tenure": "assigned",
                "tenure_note": "2020 인구주택총조사 시군구별 점유형태(주택 종류·가구주 연령·1인가구)를 합쳐 2024 주거실태조사 "
                               "시도 비율로 맞춘 뒤 사람마다 뽑음. 무상은 '기타'로 셈",
                "market_note": "대책 발표 달 직전 3개월 국토교통부 실거래가(매매·전월세), 2024 주택소유통계(다주택·공시가격 12억 원 초과)",
                "price_band_note": f"사는 시군구의 {housing_context.period_ko(market['level']['months'])} 아파트 매매 "
                                   f"중위가격(국토교통부 실거래가, 해제 거래 뺌). 거래 {market['min_n']}건 미만이면 "
                                   f"'{housing_context.NO_PRICE}'" if market.get("level") else None,
                "panel_from": self.panel_from,
                **({"tenure_before": self._tenure_before(people)} if self.panel_from else {})}} if self.housing else {}),
            "meta": {"jev_usage": self.meta["jev_usage"], "stages": self.meta["stages"], "jev_model": jev.model(),
                     "failures": self.meta["failures"]},
        }
        errors = validate_bundle(bundle, n_measures=len(self.series["measures"]))
        if errors:
            raise SeriesError("; ".join(errors[:10]))
        target = config.web_dev_series_dir() if bundle["provider"] == "mock" else config.web_series_dir()
        target.mkdir(parents=True, exist_ok=True)
        dest = target / f"{bundle['id']}.json"
        dest.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        return dest

    def _tenure_before(self, people: dict) -> dict:
        """The source run's tenure for the same people (Jev's estimate there), to show what the assignment replaced."""
        src = read_rows(config.runs_dir() / self.panel_from / "tenure.jsonl")
        return series_analyze.tenure_overall({u: {"tenure": src[u]["tenure"]} for u in people if u in src})

    def run(self, only: tuple[str, ...] = (), export: bool = True) -> Path | None:
        self.stage_tenure()
        self.stage_measures(tuple(only))
        return self.export() if export else None
