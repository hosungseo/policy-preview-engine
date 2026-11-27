"use client";

import { useMemo, useState } from "react";
import PersonaCard from "@/components/PersonaCard";
import type { Persona, Reaction } from "@/lib/types";

interface Props {
  personas: Persona[];
  reactions: Reaction[];
  segments: { id: string; label: string }[];
  issues: { id: string; title: string; member_ids: string[] }[];
  lenses?: { key: string; label: string; n: number }[];
}

const PANELS = [["all", "전체"], ["rep", "대표 패널"], ["aff", "영향권 패널"]] as const;
const STANCES = [["all", "전체"], ["neg", "반대"], ["zero", "중립"], ["pos", "찬성"]] as const;
const FIRST = 12;

// Interleave support levels so the first screen shows the spread of opinion, not one province.
function diverse(list: Reaction[]): Reaction[] {
  const order = [-2, 2, -1, 1, 0];
  const buckets = new Map(order.map((k) => [k, list.filter((r) => r.support === k)]));
  const out: Reaction[] = [];
  while (out.length < list.length) {
    for (const k of order) {
      const next = buckets.get(k)!.shift();
      if (next) out.push(next);
    }
  }
  return out;
}

function FilterGroup({ label, options, value, onChange }: {
  label: string; options: readonly (readonly [string, string])[]; value: string; onChange: (v: string) => void;
}) {
  return (
    <div className="pp-filter">
      <span>{label}</span>
      {options.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}
          className={`pp-filter-btn${value === v ? " is-on" : ""}`}>
          {text}
        </button>
      ))}
    </div>
  );
}

export default function VoicesExplorer({ personas, reactions, segments, issues, lenses = [] }: Props) {
  const [panel, setPanel] = useState("all");
  const [stance, setStance] = useState("all");
  const [issue, setIssue] = useState("all");
  const [lens, setLens] = useState("all");
  const lensLabel = useMemo(() => new Map(lenses.map((l) => [l.key, l.label])), [lenses]);
  const [shown, setShown] = useState(FIRST);
  const person = useMemo(() => new Map(personas.map((p) => [p.uuid, p])), [personas]);
  const segmentLabel = useMemo(() => new Map(segments.map((s) => [s.id, s.label])), [segments]);
  const issueOf = useMemo(() => {
    const map = new Map<string, string>();
    for (const it of issues) for (const rid of it.member_ids) map.set(rid, it.id);
    return map;
  }, [issues]);

  const list = diverse(reactions.filter((r) => {
    const p = person.get(r.uuid);
    if (!p) return false;
    if (panel !== "all" && p.panel !== panel) return false;
    if (stance === "neg" && r.support >= 0) return false;
    if (stance === "zero" && r.support !== 0) return false;
    if (stance === "pos" && r.support <= 0) return false;
    if (issue !== "all" && issueOf.get(r.rid) !== issue) return false;
    if (lens !== "all" && !(r.lenses ?? []).includes(lens)) return false;
    return true;
  }));
  const change = (set: (v: string) => void) => (v: string) => { set(v); setShown(FIRST); };

  return (
    <div>
      <div className="pp-filters" role="group" aria-label="응답 필터">
        <FilterGroup label="패널" options={PANELS} value={panel} onChange={change(setPanel)} />
        <FilterGroup label="지지" options={STANCES} value={stance} onChange={change(setStance)} />
        <label className="pp-filter-select">
          쟁점
          <select className="krds-form-select" value={issue} onChange={(e) => change(setIssue)(e.target.value)}>
            <option value="all">전체</option>
            {issues.map((it) => <option key={it.id} value={it.id}>{it.title}</option>)}
          </select>
        </label>
        {lenses.length > 0 && (
          <label className="pp-filter-select">
            관점
            <select className="krds-form-select" value={lens} onChange={(e) => change(setLens)(e.target.value)}>
              <option value="all">전체</option>
              {lenses.map((l) => <option key={l.key} value={l.key}>{l.label} ({l.n})</option>)}
            </select>
          </label>
        )}
        <span className="pp-filter-count">{list.length}명</span>
      </div>
      <div className="pp-grid-3 pp-voices">
        {list.slice(0, shown).map((r) => {
          const p = person.get(r.uuid)!;
          const similar = p.similar.map((u) => person.get(u)).filter((x): x is Persona => Boolean(x));
          return (
            <PersonaCard key={r.rid} person={p} reaction={r} similar={similar}
              segmentLabel={r.segment_id ? segmentLabel.get(r.segment_id) : undefined}
              opposeLabel={p.jev?.oppose_most && p.jev.oppose_most.p >= 0.2 ? segmentLabel.get(p.jev.oppose_most.segment_id) : undefined}
              lensLabels={(r.lenses ?? []).slice(0, 3).map((k) => lensLabel.get(k) ?? k)} />
          );
        })}
      </div>
      {shown < list.length && (
        <div className="pp-actions" style={{ justifyContent: "center", marginTop: 16 }}>
          <button type="button" className="krds-btn medium secondary" onClick={() => setShown((n) => n + FIRST * 2)}>
            더 보기 (남은 {list.length - shown}명)
          </button>
        </div>
      )}
    </div>
  );
}
