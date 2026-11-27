"""Stage orchestration. Every stage writes files in runs/<id>/ so an interrupted run resumes."""
from __future__ import annotations

import json
from copy import deepcopy
import random
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import (analyze_jev, analyze_llm, analyze_stats, budget, config, export, hearing, jev, jev_panel, llm, panel, personas,
               plan_doc, prompts, react, segment, semantic, selection)

STAGES = ("segment", "clarity", "panel", "react", "issues", "jev", "alternatives", "review", "analyze", "hearing",
          "debrief", "plan", "export")
OUTPUTS = {"segment": "segments.json", "clarity": "clarity.json", "panel": "panel.json", "react": "reactions.done",
           "issues": "issues.json", "jev": "jev.json", "alternatives": "alternatives.json", "review": "review.json",
           "analyze": "analysis.json", "hearing": "hearing.json", "debrief": "debrief.json", "plan": "plan.json",
           "export": None}
REVIEW_SAMPLE, REPEAT_SAMPLE, OCCUPATION_SAMPLE = 300, 100, 150
JEV_WORKERS = 24  # the shared rate limiter in jev.py keeps any number of workers under the API limit
QUANT_FIELDS = ("uuid", "sex", "age", "province", "occupation", "occupation_major", "education_level",
                "family_type", "housing_type")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Run:
    def __init__(self, policy_path: Path, *, n_rep: int = 300, n_aff: int = 100, n_jev: int = 5000, n_alt: int = 1500,
                 workers: int = 8, seed: int = 42, allow_mock: bool = False, run_dir: Path | None = None,
                 pool_uuids: list[str] | None = None, on_stage=None, data_meta: dict | None = None,
                 limits: budget.Limits | None = None):
        """`run_dir` replaces runs/<id>/. `pool_uuids` limits the representative and the quantitative panel to those
        people (the respondents of an earlier survey); the affected panel is still searched in the whole source.
        `on_stage(name)` is called as each stage starts."""
        self.policy = _read(Path(policy_path))
        for key in ("id", "title", "kind", "text"):
            if not self.policy.get(key):
                raise ValueError(f"policy file missing {key!r}")
        self.dir = Path(run_dir) if run_dir else config.runs_dir() / self.policy["id"]
        self.pool_uuids, self.on_stage = pool_uuids, on_stage
        self.n_rep, self.n_aff, self.workers, self.seed, self.allow_mock = n_rep, n_aff, workers, seed, allow_mock
        self.n_jev, self.n_alt, self.n_qa = n_jev, n_alt, 600
        from . import provenance
        limits = limits or budget.Limits()
        source = data_meta if data_meta is not None else provenance.engine_source()
        inputs = provenance.execution_inputs(self.policy, source,
            {"n_rep": n_rep, "n_aff": n_aff, "n_jev": n_jev, "n_alt": n_alt, "seed": seed,
             "pool_uuids": sorted(pool_uuids) if pool_uuids is not None else None}, asdict(limits))
        fingerprint = provenance.input_hash(inputs)
        meta_path = self.dir / "meta.json"
        self.meta = _read(meta_path) if meta_path.exists() else {
            "provider": llm.provider(),
            "models": {"react": llm.model_label(config.REACT_MODEL), "synth": llm.model_label(config.SYNTH_MODEL)},
            "created_at": _now(), "stages": [], "counts": {}, "fallbacks": [],
            "panel_request": {"n_rep": n_rep, "n_aff": n_aff, "seed": seed},
            **source,
        }
        if meta_path.exists() and self.meta.get("input_hash") != fingerprint:
            old = self.meta.get("execution_inputs", {})
            changed = [k for k in inputs if old.get(k) != inputs[k]]
            raise provenance.InputMismatch(f"run inputs changed ({', '.join(changed)}); use a new run directory; "
                                           "legacy runs without input_hash cannot resume")
        people_path = self.dir / "personas.json"
        if meta_path.exists() and people_path.exists() and self.meta.get("personas_hash") != provenance.input_hash(_read(people_path)):
            raise provenance.InputMismatch("stored persona profiles changed; use a new run directory")
        existing_outputs = [p for p in OUTPUTS.values() if p] + ["personas.json", "reactions.json", "bundle.json"]
        if not meta_path.exists() and self.dir.exists() and (any(self.dir.glob("*.jsonl")) or
                any((self.dir / p).exists() for p in existing_outputs)):
            raise provenance.InputMismatch("legacy results without input_hash; use a new run directory")
        self.meta.update(input_hash=fingerprint, execution_inputs=inputs)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.budget = budget.Budget(limits, self.dir / "budget.json")
        _write(self.dir / "policy.json", self.policy)
        self.save_meta()

    def path(self, name: str) -> Path:
        return self.dir / name

    def save_meta(self) -> None:
        _write(self.path("meta.json"), self.meta)

    def _strata(self, conn) -> dict:
        """Sampling strata: everyone in the source, or only the pool when one was given."""
        strata = personas.PersonaIndex.load(conn).strata()
        if self.pool_uuids is None:
            return strata
        keep = set(personas.ids_for_uuids(conn, list(self.pool_uuids), strict=True))
        return {key: kept for key, ids in strata.items() if (kept := [i for i in ids if i in keep])}

    def run(self, force: tuple[str, ...] = (), only: tuple[str, ...] = (), skip: tuple[str, ...] = ()) -> Path | None:
        with self.budget.scope():
            try:
                return self._run(force, only, skip)
            finally:
                self.meta["budget"] = self.budget.snapshot()
                self.save_meta()

    def _run(self, force, only, skip):
        dest = None
        for name in STAGES:
            if (only and name not in only) or name in skip:
                continue
            out = OUTPUTS[name]
            if out and self.path(out).exists() and name not in force:
                print(f"[{self.policy['id']}] {name}: skip (done)", flush=True)
                continue
            print(f"[{self.policy['id']}] {name}: start", flush=True)
            if self.on_stage:
                self.on_stage(name)
            started, t0 = _now(), time.time()
            result = getattr(self, f"stage_{name}")()
            self.meta["budget"] = self.budget.snapshot()
            seconds = round(time.time() - t0, 1)
            if name == "export":
                dest = result
            else:
                self.meta["stages"] = [s for s in self.meta["stages"] if s["name"] != name] + [
                    {"name": name, "started_at": started, "seconds": seconds}]
                self.save_meta()
            print(f"[{self.policy['id']}] {name}: done in {seconds}s", flush=True)
        return dest

    def _jev_usage(self, stage: str) -> None:
        """Record this stage's Jev calls, input tokens, summed call seconds and cost, then reset the tally."""
        used = {label: {"calls": u["calls"], "input_tokens": u["input_tokens"], "call_seconds": u["seconds"],
                        "cost_usd": jev.cost_usd(u["input_tokens"]), "cached": u.get("cached", 0)}
                for label, u in jev.usage().items()}
        jev.reset_usage()
        if used:
            self.meta.setdefault("jev_usage", {})[stage] = used
            self.save_meta()

    def _fresh(self, *names: str) -> None:
        """A forced rerun starts over instead of resuming from an earlier run's partial files."""
        for name in names:
            if self.path(name).exists():
                self.path(name).unlink()

    def _fallback(self, note: str) -> None:
        if note not in self.meta["fallbacks"]:
            self.meta["fallbacks"].append(note)
            self.save_meta()

    def stage_segment(self) -> None:
        _write(self.path("segments.json"), segment.split_segments(self.policy["text"]))

    def stage_clarity(self) -> None:
        """Plain-language check of every provision and of the notice as a whole (Jev, one call per provision)."""
        if not jev.available():
            _write(self.path("clarity.json"), {"available": False})
            return
        jev.reset_usage()
        out = jev_panel.check_clarity(self.policy["title"], self.policy["text"], _read(self.path("segments.json")))
        _write(self.path("clarity.json"), {"available": True, **out})
        self._jev_usage("clarity")

    def stage_panel(self) -> None:
        jev.reset_usage()
        conn = personas.connect()
        strata = self._strata(conn)
        rep_ids = panel.sample_representative(strata, self.n_rep, seed=self.seed)
        requested_spec = {}

        def validate_spec(raw):
            normalized = panel.normalize_spec(raw)
            requested_spec.clear()
            requested_spec.update(deepcopy(raw))
            return normalized

        spec = llm.complete_json("target", prompts.TARGET_SYSTEM,
                                 prompts.target_prompt(self.policy["text"], personas.occupation_names(conn)),
                                 model=config.SYNTH_MODEL, validate=validate_spec)
        semantic_ids: list[int] = []
        missing_semantic_uuids: list[str] = []
        semantic_note = ""
        if not semantic.available():
            self._fallback("의미 검색 경로 생략: 임베딩 파일 없음")
        elif spec["semantic_query"]:
            try:
                query = semantic.embed_query(spec["semantic_query"])
                hits = semantic.index().search(query, 1000)
                candidates = personas.fetch(conn, personas.ids_for_uuids(conn, [u for u, _ in hits],
                                                                        missing=missing_semantic_uuids))
                semantic_ids = [pid for pid, _ in semantic.rerank_without_names(candidates, query, 300)]
                semantic_note = (f"공개 임베딩으로 상위 {len(candidates)}명을 찾은 뒤, 이름 편향을 줄이려고 "
                                 f"이름을 지운 서술로 다시 임베딩해 {len(semantic_ids)}명을 골랐습니다.")
            except Exception as e:  # noqa: BLE001  model download / MPS errors fall back to two channels
                self._fallback(f"의미 검색 경로 생략: {type(e).__name__}: {str(e)[:120]}")
        affected_receipt = {}
        affected, channel_counts = panel.build_affected(conn, spec, set(rep_ids), k=self.n_aff,
                                                        semantic_ids=semantic_ids, seed=self.seed,
                                                        receipt=affected_receipt)
        found_by = {c["id"]: c["found_by"] for c in affected}
        rows = personas.fetch(conn, rep_ids + [c["id"] for c in affected])
        occupations = [r["occupation"] for r in rows]
        majors = jev_panel.map_occupations_jev(occupations) if jev.available() else analyze_llm.map_occupations(occupations)
        similar: dict[str, list[str]] = {}
        if semantic.available():
            try:
                similar = semantic.similar_by_text(rows, 3, key="uuid")
            except Exception as e:  # noqa: BLE001
                self._fallback(f"비슷한 인물 계산 생략: {type(e).__name__}: {str(e)[:120]}")
        people = [{**{k: v for k, v in r.items() if k != "id"},
                   "panel": "aff" if r["id"] in found_by else "rep",
                   "found_by": found_by.get(r["id"], []),
                   "occupation_major": majors[r["occupation"]],
                   "similar": similar.get(r["uuid"], [])} for r in rows]
        from . import provenance
        _write(self.path("selection.json"), selection.receipt(
            source=provenance.engine_source(), requested_spec=requested_spec, spec=spec,
            strata=strata, rep_ids=rep_ids, affected=affected, rows=rows,
            n_rep=self.n_rep, seed=self.seed, pool_uuids=self.pool_uuids,
            affected_receipt=affected_receipt, channel_counts=channel_counts,
            missing_semantic_uuids=missing_semantic_uuids, semantic_note=semantic_note))
        _write(self.path("personas.json"), people)
        self.meta["personas_hash"] = provenance.input_hash(people)
        _write(self.path("panel.json"), {
            "representative": {"n": len(rep_ids), "strata": ["province", "age_band", "sex"], "seed": self.seed},
            "affected": {"n": len(affected), "spec": spec, "channels": channel_counts, "semantic_note": semantic_note},
        })
        self._jev_usage("panel")
        self.save_meta()

    def stage_react(self) -> None:
        people = _read(self.path("personas.json"))
        reactions, failures = react.run_reactions(people, self.policy["text"], self.path("reactions.jsonl"),
                                                  workers=self.workers)
        for i, r in enumerate(reactions, start=1):
            r["rid"] = f"r{i}"
        mismatches = react.verify_quotes(reactions, self.policy["text"], _read(self.path("segments.json")))
        _write(self.path("reactions.json"), reactions)
        _write(self.path("failures.json"), failures)
        self.meta["counts"].update({"react_calls": len(people), "reactions": len(reactions),
                                    "failed": len(failures), "quote_mismatch": mismatches})
        self.save_meta()
        if failures:
            print(f"  {len(failures)} reactions failed; rerun with --force react to retry them", flush=True)
        self.path("reactions.done").write_text(_now(), encoding="utf-8")

    def stage_issues(self) -> None:
        """The LLM names the issues and groups the suggestions; Jev decides which reactions raise each issue
        and reads every reason to check it against the LLM's own support label."""
        jev.reset_usage()
        reactions = _read(self.path("reactions.json"))
        title = self.policy["title"]
        raw = analyze_llm.cluster_issues(reactions, title)
        out = {"issues": raw, "suggestions": analyze_llm.cluster_suggestions(reactions, title),
               "assignment": None, "consistency": None}
        people = {p["uuid"]: p for p in _read(self.path("personas.json"))}
        panel_of = {r["rid"]: people[r["uuid"]]["panel"] for r in reactions}
        for suggestion in out["suggestions"]:
            suggestion["n"] = sum(panel_of[rid] == "rep" for rid in suggestion["member_ids"])
            suggestion["n_aff"] = sum(panel_of[rid] == "aff" for rid in suggestion["member_ids"])
            suggestion["caution"] = "영향권: 전체 비율로 읽지 않음"
        if jev.available():
            out["issues"], out["assignment"] = jev_panel.assign_issues(raw, reactions, workers=16)
            out["consistency"] = jev_panel.check_consistency(reactions, title, workers=16)
            self.meta["counts"]["issue_assignment"] = out["assignment"]
        out["issues"] = [{**it, "k": k} for k, it in enumerate(out["issues"])]  # k = position in the Jev question set
        _write(self.path("issues.json"), out)
        self._jev_usage("issues")

    def stage_jev(self) -> None:
        """Calibrated quantitative check: a large stratified panel plus the LLM panel, one Jev call each,
        every judgment (stance, impact, provisions, issues, ways to take part) in the same call."""
        if not jev.available():
            self._fallback("Jev 정량 점검 생략: TYPESAFE_API_KEY 없음")
            _write(self.path("jev.json"), {"available": False})
            return
        if self.path("jev.json").exists():
            self._fresh("jev.json", "jev.jsonl", "jev_failures.json")
        jev.reset_usage()
        issues = _read(self.path("issues.json"))["issues"] if self.path("issues.json").exists() else []
        conn = personas.connect()
        llm_people = _read(self.path("personas.json"))
        llm_ids = {p["uuid"] for p in llm_people}
        rows = personas.fetch(conn, panel.sample_representative(self._strata(conn), self.n_jev, seed=self.seed + 1))
        quant = [{k: v for k, v in r.items() if k != "id"} for r in rows]
        majors = jev_panel.map_occupations_jev([p["occupation"] for p in quant])
        for p in quant:
            p["occupation_major"] = majors[p["occupation"]]
        everyone = quant + [p for p in llm_people if p["uuid"] not in {q["uuid"] for q in quant}]
        scored, failures = jev_panel.run_jev_panel(everyone, self.policy["title"], self.policy["text"],
                                                   _read(self.path("segments.json")), self.path("jev.jsonl"),
                                                   issues=issues,
                                                   workers=JEV_WORKERS)
        _write(self.path("jev_quant.json"), [{k: p.get(k) for k in QUANT_FIELDS} for p in quant])
        _write(self.path("jev_failures.json"), failures)
        self.meta["counts"].update({"jev_calls": len(everyone), "jev_scored": len(scored), "jev_failed": len(failures)})
        self.meta["models"]["jev"] = jev.model()
        self.save_meta()
        _write(self.path("jev.json"), {"available": True, "n_quant": len(quant), "n_llm_overlap": len(llm_ids),
                                       "n_issues": len(issues)})
        self._jev_usage("jev")

    def stage_alternatives(self) -> None:
        """Paired amendment test: AI-drafted amendments from the largest suggestion groups, each scored by Jev
        for the same subsample of the quantitative panel as the original text."""
        info = _read(self.path("jev.json")) if self.path("jev.json").exists() else {"available": False}
        suggestions = _read(self.path("issues.json"))["suggestions"] if self.path("issues.json").exists() else []
        if not info.get("available") or not suggestions:
            _write(self.path("alternatives.json"), {"available": False})
            return
        if self.path("alternatives.json").exists():
            self._fresh("alternatives.json", "alternatives.jsonl", "alternatives_drafts.json")
        jev.reset_usage()
        drafts_path = self.path("alternatives_drafts.json")
        if drafts_path.exists():  # resuming: keep the drafts the partial scores were made for
            drafts = _read(drafts_path)
        else:
            drafts = analyze_llm.draft_amendments(suggestions, self.policy["title"], self.policy["text"],
                                                  _read(self.path("segments.json")))
            _write(drafts_path, drafts)
        quant = _read(self.path("jev_quant.json"))
        sample = random.Random(self.seed + 2).sample(quant, min(self.n_alt, len(quant)))
        conn = personas.connect()
        full = {r["uuid"]: r for r in personas.fetch(conn, personas.ids_for_uuids(conn, [p["uuid"] for p in sample]))}
        people = [full[p["uuid"]] for p in sample if p["uuid"] in full]
        rows, failures = jev_panel.score_variants(people, self.policy["title"], self.policy["text"],
                                                  drafts + [jev_panel.PLACEBO], self.path("alternatives.jsonl"),
                                                  workers=JEV_WORKERS)
        _write(self.path("alternatives.json"), {"available": True, "n": len(people), "sample": [p["uuid"] for p in people],
                                                "drafts": drafts, "scored": len(rows), "failed": len(failures)})
        self._jev_usage("alternatives")

    def stage_review(self) -> None:
        """Quality checks on Jev's own judgments, and two additions: issue membership asked in both option
        orders (averaged), and lens tags on every reaction."""
        info = _read(self.path("jev.json")) if self.path("jev.json").exists() else {"available": False}
        if not info.get("available"):
            _write(self.path("review.json"), {"available": False})
            return
        jev.reset_usage()
        title, text = self.policy["title"], self.policy["text"]
        reactions = _read(self.path("reactions.json"))
        issues = _read(self.path("issues.json"))["issues"]
        segments = _read(self.path("segments.json"))
        issues_v2, order = jev_panel.assign_issues_both_orders(issues, reactions, workers=JEV_WORKERS)
        lenses = jev_panel.tag_reactions(reactions, title, workers=JEV_WORKERS)
        rows = {}
        for line in self.path("jev.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["uuid"]] = row
        quant = [p for p in _read(self.path("jev_quant.json")) if p["uuid"] in rows]
        sample = random.Random(self.seed + 4).sample(quant, min(REVIEW_SAMPLE, len(quant)))
        conn = personas.connect()
        full = {r["uuid"]: r for r in personas.fetch(conn, personas.ids_for_uuids(conn, [p["uuid"] for p in sample]))}
        people = [full[p["uuid"]] for p in sample if p["uuid"] in full]
        batching = jev_panel.check_batching(people, title, text, rows, workers=JEV_WORKERS)
        repeat = jev_panel.check_repeat(people[:REPEAT_SAMPLE], title, text, segments, issues, rows, workers=JEV_WORKERS)
        jev_map = {p["occupation"]: p["occupation_major"] for p in quant}
        picked = random.Random(self.seed + 5).sample(sorted(jev_map), min(OCCUPATION_SAMPLE, len(jev_map)))
        occupations = analyze_jev.occupation_agreement({o: jev_map[o] for o in picked}, analyze_llm.map_occupations(picked))
        _write(self.path("review.json"), {"available": True, "issues": issues_v2, "order": order, "lenses": lenses,
                                          "batching": batching, "repeat": repeat, "occupations": occupations})
        self._jev_usage("review")

    def _jev_analysis(self, reactions: list[dict], people: dict[str, dict], segments: list[dict],
                      issues: list[dict]) -> dict | None:
        info = _read(self.path("jev.json")) if self.path("jev.json").exists() else {"available": False}
        if not info.get("available"):
            return None
        rows = {}
        for line in self.path("jev.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["uuid"]] = row
        quant_people = {p["uuid"]: p for p in _read(self.path("jev_quant.json"))}
        quant_rows = [rows[u] for u in quant_people if u in rows]
        return {
            "n": len(quant_rows),
            "overall": analyze_jev.overall(quant_rows),
            "by_group": analyze_jev.by_group(quant_rows, quant_people),
            "clauses": analyze_jev.clause_matrix(quant_rows, quant_people, segments),
            "positions": analyze_jev.position_matrix(quant_rows, quant_people, segments),
            "issue_prevalence": analyze_jev.issue_prevalence(quant_rows, quant_people, issues),
            "methods": analyze_jev.methods_overall(quant_rows),
            "methods_by_group": analyze_jev.methods_matrix(quant_rows, quant_people),
            "explain": analyze_jev.explain_summary(quant_rows, quant_people, segments),
            "provinces": analyze_jev.provinces(quant_rows, quant_people),
            "channels": analyze_jev.channels(quant_rows),
            "outreach_candidates": analyze_jev.outreach_candidates(quant_rows, quant_people, people),
            "compare": analyze_jev.compare([r for r in reactions if people[r["uuid"]]["panel"] == "rep"], rows),
            "compare_aff": {**analyze_jev.compare([r for r in reactions if people[r["uuid"]]["panel"] == "aff"], rows),
                            "caution": "전체 비율로 읽지 않음"},
        }

    def _alternatives_analysis(self) -> dict | None:
        info = _read(self.path("alternatives.json")) if self.path("alternatives.json").exists() else {"available": False}
        if not info.get("available"):
            return None
        rows = [json.loads(line) for line in self.path("alternatives.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        sample = set(info["sample"])
        people = {p["uuid"]: p for p in _read(self.path("jev_quant.json")) if p["uuid"] in sample}
        return {"n": info["n"], "placebo_text": jev_panel.PLACEBO["text"],
                **analyze_jev.alternatives_summary(rows, people, info["drafts"], placebo_id=jev_panel.PLACEBO["id"])}

    def stage_analyze(self) -> None:
        people = {p["uuid"]: p for p in _read(self.path("personas.json"))}
        reactions = _read(self.path("reactions.json"))
        segments = _read(self.path("segments.json"))
        title = self.policy["title"]
        rep = [r for r in reactions if people[r["uuid"]]["panel"] == "rep"]
        aff = [r for r in reactions if people[r["uuid"]]["panel"] == "aff"]
        grouped = _read(self.path("issues.json"))
        review = _read(self.path("review.json")) if self.path("review.json").exists() else {"available": False}
        # membership asked in both option orders when the review ran; single-order membership otherwise
        issues = analyze_llm.enrich_issues(review["issues"] if review.get("available") else grouped["issues"],
                                           reactions, people)
        by_uuid = {r["uuid"]: r for r in reactions}
        by_rid = {r["rid"]: r for r in reactions}
        analysis = {
            "overall": analyze_stats.overall(rep),
            "overall_aff": {**analyze_stats.overall(aff), "caution": "전체 비율로 읽지 않음"},
            "by_group": analyze_stats.by_group(rep, people),
            "segments_heat": analyze_stats.segment_heat(rep, segments),
            "segments_heat_aff": [{**row, "caution": "전체 비율로 읽지 않음"} for row in analyze_stats.segment_heat(aff, segments)],
            "issues": issues,
            "unassigned": len(rep) - sum(it["n"] for it in issues),
            "unassigned_aff": len(aff) - sum(it["by_panel"]["aff"]["n"] for it in issues),
            "suggestions": [{**item, "n": sum(by_rid[rid] in rep for rid in item["member_ids"]),
                             "n_aff": sum(by_rid[rid] in aff for rid in item["member_ids"]),
                             "caution": "영향권: 전체 비율로 읽지 않음"} for item in grouped["suggestions"]],
            "consistency": grouped.get("consistency"),
        }
        jev_part = self._jev_analysis(reactions, people, segments, issues)
        if jev_part and jev_part.get("issue_prevalence"):
            prevalence = jev_part["issue_prevalence"]
            for it in issues:  # how widely the representative panel shares each issue
                it["jev_mean"] = prevalence["overall"][it["id"]]
                it["jev_leaders"] = prevalence["leaders"][it["id"]]
        candidates = ([{**c, "panel": "rep"} for c in jev_part.pop("outreach_candidates")] if jev_part else
                      [{**c, "panel": key, "caution": "전체 비율로 읽지 않음" if key == "aff" else "대표 패널"}
                       for key, rows in (("rep", rep), ("aff", aff))
                       for c in analyze_stats.outreach_candidates(rows, people)])
        analysis["outreach"] = analyze_llm.outreach_text(candidates, by_uuid, title)
        analysis["outreach_source"] = "jev" if jev_part else "llm"
        analysis["jev"] = jev_part
        analysis["alternatives"] = self._alternatives_analysis()
        if review.get("available"):
            analysis["quality"] = {k: review[k] for k in ("order", "batching", "repeat", "occupations")}
            analysis["lenses"] = analyze_jev.lens_summary(review["lenses"], rep,
                                                          {k: label for k, (label, _) in jev_panel.LENSES.items()})
            analysis["lenses_aff"] = {**analyze_jev.lens_summary(review["lenses"], aff,
                                      {k: label for k, (label, _) in jev_panel.LENSES.items()}),
                                      "caution": "전체 비율로 읽지 않음"}
        clarity = _read(self.path("clarity.json")) if self.path("clarity.json").exists() else {"available": False}
        if clarity.get("available"):
            names = {i["key"]: i["label"] for i in clarity["indicators"]}
            flagged = [c for c in clarity["clauses"] if c["flags"]]
            worst = max(flagged, key=lambda c: (len(c["flags"]), max(c["values"].values())), default=None)
            analysis["clarity"] = {
                "clauses": len(clarity["clauses"]), "flagged": len(flagged),
                "worst": {"segment_id": worst["segment_id"], "flags": [names[k] for k in worst["flags"][:3]]} if worst else None,
                "missing": [d["label"] for d in clarity["document"] if d["p"] < clarity.get("threshold", 0.5)],
            }
        analysis["insights"] = analyze_stats.insights(analysis, segments)
        _write(self.path("analysis.json"), analysis)

    def stage_hearing(self) -> None:
        people = {p["uuid"]: p for p in _read(self.path("personas.json"))}
        reactions = _read(self.path("reactions.json"))
        issues = _read(self.path("analysis.json"))["issues"]
        participants = hearing.select_participants(issues, reactions, people, k=6)
        result = hearing.run_hearing(self.policy["title"], self.policy["text"], participants, people,
                                     {r["uuid"]: r for r in reactions}, [it["title"] for it in issues[:3]],
                                     workers=self.workers)
        _write(self.path("hearing.json"), result)
        self.meta["hearing_context"] = {k: result[k] for k in prompts.hearing_policy_context(self.policy["text"])}
        self.save_meta()

    def stage_debrief(self) -> None:
        """Jev reads every speech in the virtual hearing: stance, rebuttal, new point, concession, proposal."""
        hearing_ = _read(self.path("hearing.json"))
        if not jev.available() or not hearing_.get("turns"):
            _write(self.path("debrief.json"), {"available": False})
            return
        jev.reset_usage()
        people = {p["uuid"]: p for p in _read(self.path("personas.json"))}
        reads = jev_panel.read_hearing(self.policy["title"], hearing_.get("agenda", []), hearing_["turns"], people)
        _write(self.path("debrief.json"), {"available": True, "reads": reads,
                                           **analyze_jev.hearing_trajectories(reads, hearing_["participants"])})
        self._jev_usage("debrief")

    def stage_plan(self) -> None:
        analysis = _read(self.path("analysis.json"))
        qa = analyze_llm.plan_qa(analysis["issues"], self.policy["title"])
        if qa and jev.available() and self.path("jev_quant.json").exists():
            # The LLM drafts the questions; a panel sample tells which ones people would actually ask first.
            jev.reset_usage()
            quant = _read(self.path("jev_quant.json"))
            sample = random.Random(self.seed + 3).sample(quant, min(self.n_qa, len(quant)))
            conn = personas.connect()
            full = {r["uuid"]: r for r in personas.fetch(conn, personas.ids_for_uuids(conn, [p["uuid"] for p in sample]))}
            rows = jev_panel.score_questions([full[p["uuid"]] for p in sample if p["uuid"] in full], self.policy["title"],
                                             self.policy["text"], qa, workers=JEV_WORKERS)
            priority = analyze_jev.question_priority(rows, {p["uuid"]: p for p in sample}, qa)
            qa = sorted(({**q, "jev_p": pr["p"], "jev_leaders": pr["leaders"], "jev_n": len(rows)}
                         for q, pr in zip(qa, priority)), key=lambda q: -q["jev_p"])
            self._jev_usage("plan")
        clarity = _read(self.path("clarity.json")) if self.path("clarity.json").exists() else {"available": False}
        plan = plan_doc.build_plan(self.policy, analysis, _read(self.path("segments.json")), qa, self.meta,
                                   clarity=clarity if clarity.get("available") else None)
        _write(self.path("plan.json"), plan)

    def stage_export(self) -> Path:
        bundle = export.assemble(self.dir)
        _write(self.path("bundle.json"), bundle)
        return export.write(bundle, allow_mock=self.allow_mock)
