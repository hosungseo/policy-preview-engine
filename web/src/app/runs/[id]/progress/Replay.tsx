"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { STAGES, duration } from "@/lib/format";

interface Props {
  id: string;
  stages: { name: string; seconds: number }[];
  counts: { personas: number; reactions: number; issues: number; turns: number };
}

const TOTAL_MS = 8000;

export default function Replay({ id, stages, counts }: Props) {
  const [elapsed, setElapsed] = useState(0);
  const [run, setRun] = useState(0);
  const plan = useMemo(() => {
    const seconds = STAGES.map((s) => stages.find((x) => x.name === s.key)?.seconds ?? 0);
    const weights = seconds.map((s) => Math.sqrt(Math.max(s, 1)));
    const total = weights.reduce((a, b) => a + b, 0);
    let start = 0;
    return STAGES.map((stage, i) => {
      const span = (weights[i] / total) * TOTAL_MS;
      const item = { ...stage, seconds: seconds[i], start, end: start + span };
      start += span;
      return item;
    });
  }, [stages]);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setElapsed(TOTAL_MS);
      return;
    }
    const began = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(TOTAL_MS, now - began);
      setElapsed(t);
      if (t < TOTAL_MS) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [run]);

  const done = elapsed >= TOTAL_MS;
  const detail = (key: string, p: number) => {
    if (key === "panel") return `${Math.round(p * counts.personas)}명 선정`;
    if (key === "react") return `${Math.round(p * counts.reactions)} / ${counts.reactions}명 응답`;
    if (key === "analyze") return `쟁점 ${Math.round(p * counts.issues)}개`;
    if (key === "hearing") return `발언 ${Math.round(p * counts.turns)}개`;
    return "";
  };

  return (
    <div className="pp-replay">
      {plan.map((stage, i) => {
        const p = Math.max(0, Math.min(1, (elapsed - stage.start) / (stage.end - stage.start)));
        const state = p >= 1 ? "is-done" : p > 0 ? "is-active" : "";
        return (
          <div key={stage.key} className={`pp-card pp-replay-step ${state}`}>
            <span className="pp-replay-dot">{p >= 1 ? "✓" : i + 1}</span>
            <div>
              <div className="pp-replay-title">{stage.title}</div>
              <div className="pp-replay-desc">{stage.desc}</div>
              <div className="pp-replay-track" aria-hidden="true"><div className="pp-replay-fill" style={{ width: `${p * 100}%` }} /></div>
            </div>
            <div className="pp-replay-side">
              <b>{detail(stage.key, p)}</b>
              실제 {duration(stage.seconds)}
            </div>
          </div>
        );
      })}
      <div className="pp-actions pp-replay-actions">
        <Link href={`/runs/${id}/`} className={`krds-btn large ${done ? "primary" : "secondary"}`}>결과 보기</Link>
        <button type="button" className="krds-btn large tertiary" onClick={() => { setElapsed(0); setRun((n) => n + 1); }}>
          다시 재생
        </button>
      </div>
    </div>
  );
}
