import { SUPPORT_COLOR, SUPPORT_INK } from "@/lib/colors";
import { CHANNEL_LABEL, pct, personaAnonBadge, personaPlace, personaShort, personaTitle, signed } from "@/lib/format";
import type { Persona, Reaction } from "@/lib/types";
import SupportBadge from "./SupportBadge";
import "./components.css";

export default function PersonaCard({ person, reaction, segmentLabel, similar, opposeLabel, lensLabels }: {
  person: Persona; reaction: Reaction; segmentLabel?: string; similar?: Persona[]; opposeLabel?: string; lensLabels?: string[];
}) {
  const jev = person.jev;
  const key = String(reaction.support);
  return (
    <article className="pp-card pp-person">
      <div className="pp-person-head">
        <span className="pp-avatar" style={{ background: SUPPORT_COLOR[key], color: SUPPORT_INK[key] }} aria-hidden="true">
          {personaAnonBadge(person)}
        </span>
        <div>
          <div className="pp-person-title">{personaTitle(person)}</div>
          <div className="pp-person-sub">
            합성 인물 · {personaPlace(person)} · {person.education_level} · {person.family} · {person.housing_type}
          </div>
        </div>
        <SupportBadge value={reaction.support} />
      </div>
      <p className="pp-person-reason">“{reaction.reason}”</p>
      {reaction.flagged && reaction.jev_read !== undefined && (
        <p className="pp-flag">
          <b>Jev 판독과 어긋남</b> 이 이유 문장은 {signed(reaction.jev_read)} 쪽으로 읽히는데, 인물이 스스로 붙인 찬반은
          {" "}{signed(reaction.support, 0)}입니다.
        </p>
      )}
      {reaction.quote_verified && (
        <p className="pp-person-quote">
          반응한 문구 <mark>{reaction.trigger_quote}</mark>{segmentLabel && <> · {segmentLabel}</>}
        </p>
      )}
      <div className="pp-person-foot">
        <span className={`pp-chip ${person.panel === "aff" ? "is-point" : "is-primary"}`}>
          {person.panel === "aff" ? "영향권 패널" : "대표 패널"}
        </span>
        {person.panel === "aff" && person.found_by.map((c) => <span key={c} className="pp-chip">{CHANNEL_LABEL[c]}</span>)}
        <span className="pp-chip">영향 {reaction.impact}</span>
        {reaction.concerns.map((c) => <span key={c} className="pp-chip is-point">{c}</span>)}
      </div>
      {lensLabels && lensLabels.length > 0 && (
        <p className="pp-person-lens">관점(Jev) {lensLabels.map((l) => <span key={l} className="pp-chip">{l}</span>)}</p>
      )}
      {jev && (
        <p className="pp-jev-line">
          Jev 확률 — 찬성 쪽 <b>{pct(1 - jev.reserve)}</b> · 직접 영향 <b>{pct(jev.direct)}</b> ·
          스스로 의견 낼 확률 <b>{pct(jev.comment)}</b>
          {jev.understand !== undefined && <> · 원문만으로 이해 <b>{pct(jev.understand)}</b></>}
          {jev.best_method && <><br />가장 잘 맞는 참여 방식 <b>{jev.best_method.label}</b>({pct(jev.best_method.p)})</>}
          {opposeLabel && jev.oppose_most && <><br />반대 가능성이 가장 큰 조항 <b>{opposeLabel}</b>({pct(jev.oppose_most.p)})</>}
        </p>
      )}
      {similar && similar.length > 0 && (
        <p className="pp-person-sub" style={{ margin: 0 }}>비슷한 인물(임베딩): {similar.map(personaShort).join(", ")}</p>
      )}
    </article>
  );
}
