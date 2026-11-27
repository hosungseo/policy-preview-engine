"use client";

import { useState } from "react";
import type { VisitCard } from "@/lib/reviewApi";

const KIND: Record<VisitCard["kind"], string> = { differ: "다수와 다르게 답한 사람", unsure: "‘모름’이 많은 사람", split: "의견이 갈린 사람" };

export default function VisitCards({ cards, colours }: { cards: VisitCard[]; colours: Record<string, string> }) {
  const [selected, setSelected] = useState(0);
  const current = cards[selected];
  return (
    <>
      <ul className="pp-visit-cards">
        {cards.map((card, index) => {
          const s = card.stat;
          const places = card.where?.source === "1m" && card.where.districts.length
            ? card.where.districts.slice(0, 3).map((d) => d.name).join(", ") : null;
          return (
            <li key={card.kind + card.group}>
              <article className={`pp-visit-card is-${card.kind}${selected === index ? " is-selected" : ""}`}>
                <p className="pp-visit-kind">{KIND[card.kind]}</p>
                <h3 className="pp-h3">{colours[card.group] && <span className="pp-key-dot" style={{ background: colours[card.group] }} aria-hidden="true" />}{card.group}</h3>
                <p className="pp-visit-gap">
                  <b>{s.diff_pp > 0 ? "+" : ""}{s.diff_pp}<small>%p</small></b>
                  <span>‘{s.option}’ {s.group_pct}%, 나머지 사람들은 {s.rest_pct}%</span>
                </p>
                <dl className="pp-visit-facts">
                  <div><dt>만날 곳</dt><dd>{card.venues.join(", ")}</dd></div>
                  {places && <div><dt>많이 사는 곳</dt><dd>{places}</dd></div>}
                </dl>
                <button type="button" className="pp-visit-open" aria-expanded={selected === index} aria-controls="pp-visit-follow" onClick={() => setSelected(index)}>
                  이어서 물을 질문 <span aria-hidden="true">{selected === index ? "↑" : "→"}</span>
                </button>
              </article>
            </li>
          );
        })}
      </ul>
      {current && (
        <div className="pp-visit-follow" id="pp-visit-follow" aria-live="polite">
          <div>
            <p>실제 실행 결과에 저장된 후속 질문</p>
            <h3>{current.group}에게 더 묻습니다</h3>
          </div>
          <ol>
            {current.questions.slice(1).map((question, i) => <li key={question}><span>{i + 1}</span>{question}</li>)}
          </ol>
        </div>
      )}
    </>
  );
}
