import type { Metadata } from "next";
import AiNotice from "@/components/AiNotice";
import HearingReads, { MARK_LABEL } from "@/components/HearingReads";
import JevReceipt from "@/components/JevReceipt";
import RunHeader from "@/components/RunHeader";
import SectionHead from "@/components/SectionHead";
import SupportBadge from "@/components/SupportBadge";
import { getRun, indexBundle, runParams } from "@/lib/bundles";
import { SUPPORT_COLOR, SUPPORT_INK } from "@/lib/colors";
import { personaPlace, personaTitle, signed } from "@/lib/format";
import type { HearingRead, Persona, Reaction, Turn } from "@/lib/types";
import "./hearing.css";

export const dynamicParams = false;
export function generateStaticParams() {
  return runParams();
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `가상 공청회 · ${getRun(id).title}` };
}

const ROUNDS = [
  { n: 1, title: "1라운드 · 입장 발표" },
  { n: 2, title: "2라운드 · 서로 반론" },
  { n: 3, title: "3라운드 · 보완안" },
];

function Avatar({ label, reaction }: { label: string; reaction: Reaction }) {
  const key = String(reaction.support);
  return (
    <span className="pp-avatar" style={{ background: SUPPORT_COLOR[key], color: SUPPORT_INK[key] }} aria-hidden="true">
      {label}
    </span>
  );
}

function Speech({ turn, person, reaction, read, seat }: { turn: Turn; person?: Persona; reaction?: Reaction; read?: HearingRead; seat?: number }) {
  if (turn.speaker === "사회자" || !person || !reaction) {
    return <p className="pp-turn-mod"><b>사회자</b>{turn.text}</p>;
  }
  const seatLabel = seat ? `합성 참석자 ${seat}` : "합성 참석자";
  return (
    <div className="pp-turn">
      <Avatar label={seat ? String(seat) : "익"} reaction={reaction} />
      <div>
        <div className="pp-turn-who"><b>{seatLabel}</b>{person.age}세 · {person.occupation} · {person.province}</div>
        <p>{turn.text}</p>
        {read && (
          <p className="pp-turn-marks">
            Jev 읽기 · 태도 <b>{signed(read.stance)}</b>
            {Object.entries(read.marks).filter(([, v]) => v >= 0.5).map(([k]) => (
              <span key={k} className="pp-chip">{MARK_LABEL[k] ?? k}</span>
            ))}
          </p>
        )}
      </div>
    </div>
  );
}

export default async function HearingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const b = getRun(id);
  const ix = indexBundle(b);
  const h = b.hearing;
  const seatOf = new Map(h.participants.map((u, idx) => [u, idx + 1]));
  const readAt = new Map((h.reads ?? []).map((r) => [r.index, r]));
  const turnsFor = (n: number) => h.turns.map((t, index) => ({ t, index }))
    .filter(({ t }) => (n === 1 ? t.round === 0 || t.round === 1 : t.round === n));

  return (
    <div>
      <AiNotice extra="가상 공청회 회의록은 합성 인물(AI)이 만든 토론이며 실제 발언이 아닙니다." />
      <RunHeader bundle={b} active="hearing" />
      <div className="pp-container">
        <section className="pp-section">
          <SectionHead title="참석자"
            desc="쟁점별로 입장이 가장 뚜렷한 사람과, 찬성·반대·연령·권역이 고루 섞이도록 코드가 고른 6명입니다." />
          <div className="pp-grid-3">
            {h.participants.map((uuid, idx) => {
              const p = ix.person.get(uuid)!;
              const r = ix.reactionByUuid.get(uuid)!;
              return (
                <div key={uuid} className="pp-card pp-attendee">
                  <div className="pp-attendee-head">
                    <Avatar label={String(idx + 1)} reaction={r} />
                    <div><b>합성 참석자 {idx + 1}</b><div className="pp-person-sub">{personaTitle(p)} · {personaPlace(p)}</div></div>
                  </div>
                  <div><SupportBadge value={r.support} /></div>
                  <p className="pp-attendee-reason">처음 반응 “{r.reason}”</p>
                </div>
              );
            })}
          </div>
        </section>

        <section className="pp-section">
          <SectionHead title="안건" desc="쟁점 상위 3개를 안건으로 삼았습니다." />
          <ol className="pp-agenda">{h.agenda.map((a) => <li key={a}>{a}</li>)}</ol>
        </section>

        <section className="pp-section">
          <SectionHead title="회의록" tag="ai" desc="각 발언은 인물 설정과 화법 지침으로 AI가 만들었습니다. 라운드마다 앞선 발언을 읽고 답합니다." />
          {ROUNDS.map((round) => (
            <div key={round.n} className="pp-round">
              <h3 className="pp-round-title">{round.title}</h3>
              {turnsFor(round.n).map(({ t, index }) => (
                <Speech key={index} turn={t} person={ix.person.get(t.speaker)} reaction={ix.reactionByUuid.get(t.speaker)}
                  read={readAt.get(index)} seat={seatOf.get(t.speaker)} />
              ))}
            </div>
          ))}
        </section>

        {h.trajectories && (
          <section className="pp-section" id="reads">
            <SectionHead title="발언 읽기(Jev)"
              desc="AI가 쓴 회의록을 Jev가 발언 하나씩 읽었습니다. 그 발언이 드러내는 태도와, 반박·새 논점·입장 완화·구체적 제안인지를 확률로 판정해 참석자의 입장이 라운드마다 어떻게 움직였는지 봅니다." />
            <JevReceipt meta={b.meta} stage="debrief" note={`발언 ${h.reads?.length ?? 0}개`} />
            <HearingReads hearing={h} person={ix.person} />
          </section>
        )}

        <section className="pp-section pp-grid-3">
          {([["합의된 점", h.summary.agreements], ["의견이 갈린 점", h.summary.disagreements], ["추가로 들어야 할 사람", h.summary.missing]] as const).map(([title, items]) => (
            <div key={title} className="pp-card">
              <h3 className="pp-h3">{title}<span className="pp-tag-ai">AI 작성</span></h3>
              <ul className="pp-summary-list">{items.map((x) => <li key={x}>{x}</li>)}</ul>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
