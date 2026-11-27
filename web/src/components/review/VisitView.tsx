"use client";

import { useEffect, useState } from "react";
import { api, type Result, type Run, type Visit, type VisitCard } from "@/lib/reviewApi";

const KIND: Record<VisitCard["kind"], string> = { differ: "다수와 다르게 답함", unsure: "‘모름’이 많음", split: "의견이 갈림" };

/** Where the group lives. Base-attribute groups are counted in the 1,000,000-person roster, the rest in the run's own list. */
export function Where({ card }: { card: VisitCard }) {
  const w = card.where;
  const big = w?.source === "1m";
  const districts = w?.districts.map((p) => (p.times ? `${p.name}(${p.times}배)` : p.name)).join(", ");
  const dense = w?.dense.map((p) => `${p.name}(${p.times}배)`).join(", ");
  return (
    <div className="rv-visit-row">
      <h4>어디서 만나나</h4>
      <ul className="rv-visit-chips">{card.venues.map((v) => <li key={v}>{v}</li>)}</ul>
      {big && w?.people != null && w.of ? (
        <p>합성 인물 100만 명 명단에서는 {w.people.toLocaleString()}명({Math.round((100 * w.people) / w.of)}%)입니다.</p>
      ) : null}
      {districts && <p>{big ? "유난히 많이 사는 시군구" : "시군구 예(인원이 적어 참고용)"}: {districts}</p>}
      {big && !districts && <p>어느 시군구에나 고르게 삽니다. 지역보다 만나는 방식을 먼저 정하십시오.</p>}
      {!big && dense && <p>유난히 많은 시도: {dense}</p>}
      {w && w.most.length > 0 && <p className="rv-muted">많이 사는 시도: {w.most.map((p) => `${p.name} ${p.pct}%`).join(", ")}</p>}
      {districts && <p className="rv-muted">괄호 안은 전국 평균과 견준 비율입니다.</p>}
    </div>
  );
}

function Card({ card, options }: { card: VisitCard; options: string[] }) {
  const s = card.stat;
  const focusNote = card.kind === "unsure"
    ? "내용이 충분히 닿지 않았거나 판단할 정보가 부족해 현장에서 먼저 설명·확인이 필요한 집단입니다."
    : card.kind === "split"
    ? "같은 집단 안에서도 생각이 갈려 조건별 입장을 직접 들어 볼 필요가 있는 집단입니다."
    : "전체 흐름과 다른 반응이 뚜렷해 현장에서 배경과 사정을 먼저 들어 볼 집단입니다.";
  return (
    <li className={`rv-visit-card is-${card.kind}`}>
      <p className="rv-visit-kind">{KIND[card.kind]}</p>
      <h3 className="rv-visit-who">{card.group} <span className="rv-muted">합성 인물 {card.n.toLocaleString()}명</span></h3>
      <div className="rv-visit-row">
        <h4>왜 먼저 만나 볼까</h4>
        <p>{focusNote}</p>
        {card.quiet && (
          <p>이 사람들 가운데 지난 1년 동안 서명·민원·온라인 의견을 낸 적이 없는 비중이 높아 공식 의견란만으로는 닿기 어렵습니다.</p>
        )}
      </div>
      <Where card={card} />
      <div className="rv-visit-row">
        <h4>무엇을 물을까</h4>
        <ol className="rv-visit-ask">{card.questions.map((q) => <li key={q}>{q}</li>)}</ol>
      </div>
      <details className="rv-more">
        <summary>참고용 내부 지표 · 왜 이 사람들인가</summary>
        <p className="rv-muted">{card.say}.{card.also && <> {card.also}.</>}</p>
        <p className="rv-muted">
          {options.map((o, i) => `${o} ${card.percent[i]}%`).join(", ")}
        </p>
        <p className="rv-muted">
          ‘{s.option}’: 이 집단 {s.group_pct}% − 나머지 {s.rest_pct}% = {s.diff_pp > 0 ? "+" : ""}{s.diff_pp}%p. 믿을 수 있는 최소 차이는 {s.threshold_pp}%p입니다
          (표본 폭 {s.parts.sampling}, 대조 문장 차이 {s.parts.placebo}, 순서 흔들림 차이 {s.parts.reversal}, 최소 3 가운데 가장 큰 값). 나눈 기준: {card.basis}.
        </p>
      </details>
    </li>
  );
}

/** 「찾아갈 곳」: the first thing a finished run shows. */
export default function VisitView({ run }: { run: Run }) {
  const r = run.result as Result;
  const [visit, setVisit] = useState<Visit | null>(null);
  const [failed, setFailed] = useState(false);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let alive = true;
    api<{ visit: Visit }>(`/api/runs/${run.id}/visit`).then((d) => { if (alive) setVisit(d.visit); }).catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [run.id]);
  async function copy() {
    if (!visit) return;
    const lines = visit.cards.map((c) => `${c.group}: 만날 곳(${c.venues.join(", ")}) / 먼저 물을 질문(${c.questions[0] ?? ""})`);
    const text = lines.length
      ? `※ 실제 사람 응답 0명(합성 인물 기준 현장 면담 대상·질문 초안, 여론조사 아님) — ${lines.join(" / ")}`
      : `※ 실제 사람 응답 0명(합성 인물 기준, 여론조사 아님) — ${visit.small ?? "따로 추려진 집단이 없습니다."}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard may be blocked */ }
  }
  if (failed) return <p className="rv-muted">찾아갈 곳을 계산하지 못했습니다. 새로 고쳐 주세요.</p>;
  if (!visit) return <p className="rv-muted" role="status">찾아갈 곳을 계산하는 중…</p>;
  return (
    <section className="rv-visit" aria-label="찾아갈 곳">
      <h3 className="rv-visit-title">찾아갈 곳 <span className="rv-muted">실제 사람 응답 0명 · 먼저 만나서 들어야 할 사람과 만날 곳(합성 인물 기준)</span></h3>
      {visit.small && <p className="rv-caution">{visit.small}</p>}
      {visit.cards.length > 0 && <ul className="rv-visit-cards">{visit.cards.map((c) => <Card key={c.kind + c.group} card={c} options={r.options} />)}</ul>}
      {visit.region_note && visit.cards.length > 0 && <p className="rv-visit-note">{visit.region_note}</p>}
      <div className="rv-visit-missing">
        <h4>이 명단에 없는 사람 <span className="rv-muted">AI에게 물을 수 없습니다. 직접 만나야 합니다</span></h4>
        <ul>{visit.missing.map((m) => <li key={m.who} className={m.party ? "is-party" : ""}><b>{m.who}</b><span>{m.route}</span></li>)}</ul>
      </div>
      {visit.quiet_all_pct != null && (
        <p className="rv-visit-note">
          합성 명단의 {visit.quiet_all_pct}%는 지난 1년 동안 서명·민원·온라인 의견을 낸 적이 없습니다. 의견란을 열어 두는 것만으로는 닿지 않는 사람들입니다.
        </p>
      )}
      {visit.cards.length > 0 && (
        <div className="rv-copy">
          <button type="button" className="krds-btn small secondary" onClick={copy}>{copied ? "복사했습니다" : "찾아갈 곳 복사"}</button>
        </div>
      )}
      <details className="rv-more">
        <summary>찾아갈 곳을 고른 방법</summary>
        <ul className="rv-method">{visit.method.map((m) => <li key={m}>{m}</li>)}</ul>
      </details>
    </section>
  );
}
