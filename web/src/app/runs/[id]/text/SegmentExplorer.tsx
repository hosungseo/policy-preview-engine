"use client";

import { useEffect, useState } from "react";
import SupportBadge from "@/components/SupportBadge";
import { meanFill, meanInk } from "@/lib/colors";
import { signed } from "@/lib/format";
import type { Piece } from "@/lib/highlight";

export interface SegmentView {
  id: string; label: string; pieces: Piece[]; mentions: number; mean: number | null; oppose: number; favor: number;
  concerns: string[];
  voices: { rid: string; support: number; reason: string; quote: string; who: string }[];
}

function level(count: number): number {
  return count >= 4 ? 3 : count >= 2 ? 2 : count >= 1 ? 1 : 0;
}

export default function SegmentExplorer({ segments }: { segments: SegmentView[] }) {
  const top = segments.reduce((best, s) => (s.mentions > best.mentions ? s : best), segments[0]);
  const [selected, setSelected] = useState(top?.id);
  useEffect(() => {
    const hash = window.location.hash.slice(1);
    if (hash && segments.some((s) => s.id === hash)) setSelected(hash);
  }, [segments]);
  const current = segments.find((s) => s.id === selected) ?? top;

  return (
    <div className="pp-textmap">
      <div className="pp-textmap-doc">
        {segments.map((s) => (
          <section key={s.id} id={s.id} className={`pp-seg${s.id === current?.id ? " is-selected" : ""}`}
            style={{ borderLeftColor: s.mentions ? meanFill(s.mean) : "#e6e8ea" }}>
            <button type="button" className="pp-seg-head" onClick={() => setSelected(s.id)} aria-pressed={s.id === current?.id}>
              <span className="pp-seg-name">{s.label}</span>
              <span className="pp-chip">{s.mentions}명</span>
              {s.mentions > 0 && (
                <span className="pp-seg-meanchip" style={{ background: meanFill(s.mean), color: meanInk(s.mean) }}>{signed(s.mean)}</span>
              )}
            </button>
            <p className="pp-seg-text">
              {s.pieces.map((piece, i) =>
                level(piece.count) ? (
                  <mark key={i} className={`pp-hl-${level(piece.count)}`} title={`${piece.count}명`}>{piece.text}</mark>
                ) : (
                  <span key={i}>{piece.text}</span>
                ),
              )}
            </p>
          </section>
        ))}
      </div>
      {current && (
        <aside className="pp-card pp-textmap-side" aria-live="polite">
          <p className="pp-side-kicker">선택한 항목</p>
          <h2 className="pp-h3">{current.label}</h2>
          <ul className="pp-meta">
            <li>짚은 사람 <b>{current.mentions}명</b></li>
            <li>평균 지지 <b>{signed(current.mean)}</b></li>
            <li>반대 <b>{current.oppose}</b> · 찬성 <b>{current.favor}</b></li>
          </ul>
          {current.concerns.length > 0 && (
            <div className="pp-chips" style={{ margin: "10px 0" }}>
              {current.concerns.map((c) => <span key={c} className="pp-chip is-point">{c}</span>)}
            </div>
          )}
          <div className="pp-side-voices">
            {current.voices.length === 0 && <p className="pp-sub">이 항목을 짚은 인용이 없습니다.</p>}
            {current.voices.map((v) => (
              <div key={v.rid} className="pp-side-voice">
                <div className="pp-side-who"><SupportBadge value={v.support} /><span>{v.who}</span></div>
                <p>“{v.reason}”</p>
                <p className="pp-person-quote">짚은 문구 <mark>{v.quote}</mark></p>
              </div>
            ))}
          </div>
        </aside>
      )}
    </div>
  );
}
