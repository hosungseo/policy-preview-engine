import type { Metadata } from "next";
import AiNotice from "@/components/AiNotice";
import ClarityTable, { NoticeChecklist } from "@/components/ClarityTable";
import JevReceipt from "@/components/JevReceipt";
import RunHeader from "@/components/RunHeader";
import SectionHead from "@/components/SectionHead";
import { getRun, runParams } from "@/lib/bundles";
import { MEAN_BINS } from "@/lib/colors";
import { pct, personaPlace, personaTitle } from "@/lib/format";
import { highlightPieces } from "@/lib/highlight";
import SegmentExplorer, { type SegmentView } from "./SegmentExplorer";
import "./text.css";

export const dynamicParams = false;
export function generateStaticParams() {
  return runParams();
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `정책문 쟁점 지도 · ${getRun(id).title}` };
}

export default async function TextPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const b = getRun(id);
  const person = new Map(b.personas.map((p) => [p.uuid, p]));
  const heat = new Map(b.analysis.segments_heat.map((h) => [h.segment_id, h]));
  const views: SegmentView[] = b.segments.map((s) => {
    const hits = b.reactions.filter((r) => r.segment_id === s.id && r.quote_span);
    const h = heat.get(s.id);
    return {
      id: s.id,
      label: s.label,
      pieces: highlightPieces(s.text, s.start, hits.map((r) => r.quote_span as [number, number])),
      mentions: h?.mentions ?? 0,
      mean: h?.mean ?? null,
      oppose: h?.oppose ?? 0,
      favor: h?.favor ?? 0,
      concerns: h?.top_concerns ?? [],
      voices: hits.map((r) => {
        const p = person.get(r.uuid)!;
        return { rid: r.rid, support: r.support, reason: r.reason, quote: r.trigger_quote, who: `${personaTitle(p)} · ${personaPlace(p)}` };
      }),
    };
  });

  return (
    <div>
      <AiNotice />
      <RunHeader bundle={b} active="text" />
      <div className="pp-container pp-section">
        <p className="pp-lead">
          인물마다 “반응을 일으킨 문구”를 원문에서 그대로 인용하게 했습니다. 원문과 글자가 일치한 인용만 칠했고, 진할수록 많은
          사람이 같은 곳을 짚었습니다. 항목 제목을 누르면 그 항목을 짚은 발언이 옆에 나옵니다.
        </p>
        <ul className="pp-legend pp-text-legend">
          <li><span className="pp-swatch pp-hl-1" />1명</li>
          <li><span className="pp-swatch pp-hl-2" />2~3명</li>
          <li><span className="pp-swatch pp-hl-3" />4명 이상</li>
          <li className="pp-legend-sep">왼쪽 띠 = 짚은 사람들의 평균 지지</li>
          {MEAN_BINS.map((m) => (
            <li key={m.label}><span className="pp-swatch" style={{ background: m.color, border: "1px solid #cdd1d5" }} />{m.label}</li>
          ))}
        </ul>
        <SegmentExplorer segments={views} />
        <p className="pp-sub" style={{ marginTop: 16 }}>원문과 글자가 맞지 않아 칠하지 않은 인용 {b.meta.counts.quote_mismatch ?? 0}건</p>
      </div>
      {b.clarity && (
        <div className="pp-container">
          <section className="pp-section" id="clarity">
            <SectionHead title="정책문 명료성 점검"
              desc="의견을 묻기 전에 정책문부터 고칠 곳을 찾습니다. 조항마다 읽는 사람이 겪을 문제 8가지를, 안내문 전체에는 들어가야 할 안내 6가지를 Jev가 확률로 판정했습니다." />
            <JevReceipt meta={b.meta} stage="clarity" note={`조항 ${b.clarity.clauses.length}개 + 문서 전체`} />
            <ClarityTable clarity={b.clarity} segments={b.segments.map((s) => ({ id: s.id, label: s.label }))} />
            <div className="pp-grid-2" style={{ marginTop: 16 }}>
              <div className="pp-card">
                <h3 className="pp-h3">먼저 고쳐 쓸 조항</h3>
                {(() => {
                  const names = new Map(b.clarity.indicators.map((i) => [i.key, i.label]));
                  const label = new Map(b.segments.map((s) => [s.id, s.label]));
                  const flagged = [...b.clarity.clauses].filter((c) => c.flags.length)
                    .sort((a, c) => c.flags.length - a.flags.length || Math.max(...Object.values(c.values)) - Math.max(...Object.values(a.values)));
                  return flagged.length === 0 ? <p className="pp-sub">문제 지표에 걸린 조항이 없습니다.</p> : (
                    <ol className="pp-fix-list">
                      {flagged.slice(0, 5).map((c) => (
                        <li key={c.segment_id}>
                          <b>{label.get(c.segment_id)}</b>
                          <span>{c.flags.map((k) => `${names.get(k)} ${pct(c.values[k])}`).join(" · ")}</span>
                        </li>
                      ))}
                    </ol>
                  );
                })()}
              </div>
              <NoticeChecklist clarity={b.clarity} />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
