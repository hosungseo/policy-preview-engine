import type { Metadata } from "next";
import Link from "next/link";
import AiNotice from "@/components/AiNotice";
import AmendmentCompare from "@/components/AmendmentCompare";
import CopyLink from "@/components/CopyLink";
import JevReceipt from "@/components/JevReceipt";
import LensBars from "@/components/LensBars";
import MeanRows from "@/components/MeanRows";
import MetricBar from "@/components/MetricBar";
import ProbDistribution from "@/components/ProbDistribution";
import RunHeader from "@/components/RunHeader";
import SectionHead from "@/components/SectionHead";
import SupportBadge from "@/components/SupportBadge";
import ShareBar from "@/components/ShareBar";
import StatTile from "@/components/StatTile";
import SupportDistribution from "@/components/SupportDistribution";
import { getRun, indexBundle, runParams } from "@/lib/bundles";
import { meanFill, meanInk } from "@/lib/colors";
import { duration, pct, personaPlace, personaTitle, signed } from "@/lib/format";
import VoicesExplorer from "./VoicesExplorer";
import "./result.css";

export const dynamicParams = false;
export function generateStaticParams() {
  return runParams();
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: getRun(id).title };
}

const GROUPS: [string, string][] = [
  ["age_band", "연령대"], ["region", "권역"], ["sex", "성별"], ["education_level", "학력"],
  ["housing_type", "주거 형태"], ["family", "가구"], ["occupation_major", "직업군"],
];
const STANCE_CLASS: Record<string, string> = {
  우려: "krds-badge outline-point", 기대: "krds-badge outline-primary", 혼재: "krds-badge outline-gray",
};

export default async function ResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const b = getRun(id);
  const ix = indexBundle(b);
  const heat = new Map(b.analysis.segments_heat.map((h) => [h.segment_id, h]));
  const maxMentions = Math.max(1, ...b.analysis.segments_heat.map((h) => h.mentions));
  const seconds = b.meta.stages.reduce((sum, s) => sum + s.seconds, 0);

  return (
    <div>
      <AiNotice />
      <RunHeader bundle={b} active="summary" />
      <div className="pp-container">
        <section className="pp-section">
          <SectionHead title="한눈에 보기" tag="code" desc="계산된 숫자로만 만든 자동 요약입니다." />
          <ul className="pp-insights">{b.analysis.insights.map((line) => <li key={line}>{line}</li>)}</ul>
        </section>

        {b.analysis.jev && (
          <section className="pp-section" id="jev">
            <SectionHead title={`${b.analysis.jev.n.toLocaleString()}명 정량 점검 (참고용 내부 지표)`}
              desc="같은 방식으로 뽑은 더 큰 패널에게 판단 모델 Jev가 보정된 확률로 답했습니다. 집단 선별과 흔들림 점검을 위한 내부 지표이며 실제 여론 비율이 아닙니다."
              right={<Link href={`/runs/${b.id}/jev/`} className="krds-btn medium secondary">정량 점검 전체 보기</Link>} />
            <details className="pp-card">
              <summary style={{ cursor: "pointer", fontWeight: 700 }}>참고용 내부 지표 · 모의 확률 분포 열기 (외부 보고·인용 금지)</summary>
              <div style={{ marginTop: 12 }}>
                <ProbDistribution rows={[
                  { label: "Jev 정량 패널", sub: `${b.analysis.jev.n.toLocaleString()}명 · 확률`, shares: b.analysis.jev.overall.mass },
                  ...(b.analysis.jev.compare.llm_dist ? [{
                    label: "LLM 패널", sub: `${b.analysis.jev.compare.n}명 · 한 번씩 답함`,
                    shares: ["-2", "-1", "0", "1", "2"].map((k) => (b.analysis.jev?.compare.llm_dist?.[k] ?? 0) / (b.analysis.jev?.compare.n || 1)),
                  }] : []),
                ]} />
                <p className="pp-sub" style={{ margin: "12px 0 0" }}>
                  ※ 실제 사람 응답 0명. 같은 {b.analysis.jev.compare.n.toLocaleString()}명 중 LLM은{" "}
                  {((b.analysis.jev.compare.llm_dist?.["1"] ?? 0) + (b.analysis.jev.compare.llm_dist?.["2"] ?? 0)).toLocaleString()}명이
                  찬성으로 답했고, Jev는 이 {b.analysis.jev.compare.n.toLocaleString()}명의 찬성 쪽 확률을 평균 {pct(b.analysis.jev.compare.jev_favor ?? 0)}로 봤습니다. 조항별 영향 지도와
                  집단별 결과는 정량 점검 화면에 있습니다.
                </p>
              </div>
            </details>
          </section>
        )}

        <section className="pp-section" id="issues">
          <SectionHead title="예상 쟁점 Top 5"
            desc={b.meta.counts.issue_assignment
              ? `쟁점의 이름과 요약은 LLM이 짓고, 각 반응이 어느 쟁점에 속하는지는 Jev가 판정했습니다(확률 ${pct(b.meta.counts.issue_assignment.threshold)} 이상만 인정). 비중·집단·조항은 코드가 계산했고, 발언은 원문 그대로입니다.`
              : "반응 이유를 AI가 주제별로 묶었습니다. 비중·집단·조항은 코드가 계산했고, 발언은 원문 그대로입니다."} />
          <ol className="pp-issues">
            {b.analysis.issues.slice(0, 5).map((it, i) => (
              <li key={it.id} className="pp-card pp-issue">
                <div className="pp-issue-head">
                  <span className="pp-issue-rank">{i + 1}</span>
                  <div className="pp-issue-titles">
                    <h3 className="pp-h3">{it.title} <span className={STANCE_CLASS[it.stance]}>{it.stance}</span></h3>
                    <ShareBar share={it.share} label={`대표 ${it.n}명`} />
                    {it.by_panel && <small>영향권 {it.by_panel.aff.n}명 · {pct(it.by_panel.aff.share)} (전체 비율로 읽지 않음)</small>}
                  </div>
                  <div className="pp-issue-mean">
                    <span>평균 지지</span>
                    <b style={{ background: meanFill(it.mean), color: meanInk(it.mean) }}>{signed(it.mean)}</b>
                  </div>
                </div>
                <p className="pp-issue-summary">{it.summary}<span className="pp-tag-ai">AI 작성</span></p>
                {it.jev_mean !== undefined && (
                  <p className="pp-issue-jev">
                    <span>대표 {b.analysis.jev?.n.toLocaleString()}명 중 이 쟁점을 제기할 확률 <b>{pct(it.jev_mean)}</b><span className="pp-tag-ai">AI 추정</span></span>
                    {(it.jev_leaders ?? []).slice(0, 3).map((l) => (
                      <span key={l.kind + l.group} className="pp-chip is-primary">{l.group} {pct(l.mean)}</span>
                    ))}
                  </p>
                )}
                <div className="pp-issue-quotes">
                  {it.quotes.slice(0, 2).map((q) => {
                    const p = ix.person.get(q.uuid)!;
                    return (
                      <blockquote key={q.rid} className="pp-quote">
                        “{q.text}”<cite>{personaTitle(p)} · {personaPlace(p)}</cite>
                      </blockquote>
                    );
                  })}
                </div>
                <div className="pp-issue-foot">
                  {it.groups.length > 0 && <span className="pp-issue-label">두드러진 집단</span>}
                  {it.groups.map((g) => (
                    <span key={g.kind + g.group} className="pp-chip is-primary">{g.group} ×{g.lift.toFixed(1)}</span>
                  ))}
                  {it.segments.length > 0 && <span className="pp-issue-label">관련 조항</span>}
                  {it.segments.map((sid) => (
                    <Link key={sid} href={`/runs/${b.id}/text/#${sid}`} className="pp-chip">{ix.segment.get(sid)?.label ?? sid}</Link>
                  ))}
                </div>
              </li>
            ))}
          </ol>
          {b.analysis.unassigned > 0 && (
            <p className="pp-sub" style={{ marginTop: 12 }}>어느 쟁점에도 속하지 않은 반응 {b.analysis.unassigned}건은 아래 개별 응답에서 볼 수 있습니다.</p>
          )}
        </section>

        <section className="pp-section" id="outreach">
          <SectionHead title="찾아가 들어야 할 집단"
            desc={b.analysis.outreach_source === "jev"
              ? `직접 영향 확률이 높고, 반대·유보가 많고, 공식 의견수렴에 스스로 나서지 않을 것 같은 집단을 Jev 정량 패널(${b.analysis.jev?.n.toLocaleString() ?? ""}명)의 확률로 골랐습니다. 발언은 같은 집단에 속한 LLM 패널 인물의 말입니다.`
              : "직접 영향을 받고, 반대·유보가 많고, 공식 의견수렴에 스스로 나서지 않을 것 같은 집단을 코드가 골랐습니다. 대표·영향권 패널을 함께 씁니다(비율 추정이 아니라 접촉 대상을 고르는 용도)."} />
          {b.analysis.outreach.length === 0 ? (
            <p className="pp-sub">조건을 만족하는 집단이 없습니다.</p>
          ) : (
            <div className="pp-grid-2">
              {b.analysis.outreach.map((o) => (
                <article key={(o.panel || "") + o.kind + o.group} className="pp-card pp-outreach">
                  <div className="pp-outreach-head">
                    <span className="pp-chip">{o.kind}</span>
                    <h3 className="pp-h3">{o.group}</h3>
                    <span className="pp-outreach-n">{o.panel === "aff" ? "영향권" : "대표"} {o.n}명</span>
                  </div>
                  {o.panel === "aff" && <small>전체 비율로 읽지 않음</small>}
                  <MetricBar label="직접 영향" value={o.direct} />
                  <MetricBar label="반대·유보" value={o.oppose} />
                  <MetricBar label="스스로 안 나섬" value={o.silent} estimated />
                  {o.channels.length > 0 && (
                    <p className="pp-outreach-ch">주로 소식을 접하는 곳 {o.channels.map((c) => <span key={c} className="pp-chip">{c}</span>)}</p>
                  )}
                  {o.methods && o.methods.length > 0 && (
                    <div className="pp-outreach-methods">
                      <p className="pp-outreach-ai">방식별 참여 확률 상위 3<span className="pp-tag-ai">AI 추정</span></p>
                      {o.methods.map((m) => <MetricBar key={m.key} label={m.label} value={m.p} />)}
                    </div>
                  )}
                  <p className="pp-outreach-ai">접촉 방법<span className="pp-tag-ai">AI 제안</span></p>
                  <dl className="pp-outreach-plan">
                    <dt>방식</dt><dd>{o.suggestion.method}</dd>
                    <dt>장소·경로</dt><dd>{o.suggestion.where}</dd>
                    <dt>시기</dt><dd>{o.suggestion.when}</dd>
                    <dt>근거</dt><dd>{o.suggestion.why}</dd>
                  </dl>
                  {o.sample_quotes[0] && (() => {
                    const uuid = o.sample_uuids?.[0];
                    const p = uuid ? ix.person.get(uuid) : undefined;
                    const r = uuid ? ix.reactionByUuid.get(uuid) : undefined;
                    return (
                      <blockquote className="pp-quote">
                        “{o.sample_quotes[0]}”
                        {p && <cite>{personaTitle(p)} · {personaPlace(p)}{r && <> · <SupportBadge value={r.support} /></>}</cite>}
                      </blockquote>
                    );
                  })()}
                </article>
              ))}
            </div>
          )}
        </section>

        {b.analysis.alternatives && b.analysis.alternatives.items.length > 0 && (
          <section className="pp-section" id="amendments">
            <SectionHead title="수정안을 넣으면"
              desc="보완 제안 큰 묶음을 AI가 수정 문장으로 바꾸고, 같은 사람들에게 원안과 비교해 물었습니다(Jev 추정). 반대·유보를 많이 줄이는 순서입니다."
              right={<Link href={`/runs/${b.id}/jev/#amendments`} className="krds-btn medium secondary">연령대별 변화 보기</Link>} />
            <AmendmentCompare alternatives={b.analysis.alternatives} compact
              segmentLabel={(id) => ix.segment.get(id)?.label} />
          </section>
        )}

        <section className="pp-section" id="segments">
          <SectionHead title="조항별 반응"
            desc="인물이 반응한 문구를 원문에서 찾아 조항별로 셌습니다(대표+영향권, 원문과 글자가 일치한 인용만)."
            right={<Link href={`/runs/${b.id}/text/`} className="krds-btn medium secondary">정책문 쟁점 지도</Link>} />
          <div className="pp-card">
            {b.segments.map((s) => {
              const h = heat.get(s.id);
              const mentions = h?.mentions ?? 0;
              return (
                <div key={s.id} className="pp-seg-row">
                  <Link href={`/runs/${b.id}/text/#${s.id}`} className="pp-seg-label">{s.label}</Link>
                  <div className="pp-seg-track" aria-hidden="true">
                    <div className="pp-seg-fill" style={{ width: `${(mentions / maxMentions) * 100}%` }} />
                  </div>
                  <span className="pp-seg-n">{mentions}건</span>
                  <span className="pp-seg-mean" style={{ background: meanFill(h?.mean), color: meanInk(h?.mean) }}>
                    {mentions ? signed(h?.mean) : "–"}
                  </span>
                </div>
              );
            })}
            <p className="pp-sub" style={{ margin: "12px 0 0" }}>
              막대는 언급 수, 오른쪽 칸은 언급한 사람들의 평균 지지입니다. 원문과 맞지 않은 인용 {b.meta.counts.quote_mismatch ?? 0}건은 세지 않았습니다.
            </p>
          </div>
        </section>

        <section className="pp-section">
          <SectionHead title="참고용 내부 지표 (모의 찬반 분포)" desc="※ 실제 사람 응답 0명. AI 반응은 합의를 부풀리고 중도로 몰리는 경향이 있어 기본 화면에서 접어 두었습니다. 외부 보고·인용에 쓰지 마세요." />
          <details className="pp-card">
            <summary style={{ cursor: "pointer", fontWeight: 700 }}>참고용 내부 지표 · 모의 찬반 분포 열기</summary>
            <div style={{ marginTop: 12 }}>
              <SupportDistribution rows={[
                { label: "대표 패널", sub: `${b.analysis.overall.n}명 · 인구 비례`, overall: b.analysis.overall },
                { label: "영향권 패널", sub: `${b.analysis.overall_aff.n}명 · 전체 비율로 읽지 않음`, overall: b.analysis.overall_aff },
              ]} />
            </div>
          </details>
        </section>

        <section className="pp-section">
          <SectionHead title="집단별 평균 지지 (대표 패널)"
            desc="0을 기준으로 왼쪽은 반대, 오른쪽은 찬성 쪽 평균입니다. 10명 미만 집단은 회색으로 두고 해석하지 않습니다." />
          <div className="pp-grid-2">
            {GROUPS.map(([key, title]) => <MeanRows key={key} title={title} rows={b.analysis.by_group[key] ?? []} />)}
          </div>
        </section>

        {b.analysis.suggestions.length > 0 && (
          <section className="pp-section">
            <SectionHead title="보완 제안" tag="ai" desc="인물들이 남긴 보완 제안을 AI가 묶었습니다. 예시 문장은 원문 그대로입니다." />
            <div className="pp-grid-2">
              {b.analysis.suggestions.slice(0, 6).map((s) => (
                <div key={s.title} className="pp-card pp-suggest">
                  <h3 className="pp-h3">{s.title} <span className="pp-chip">대표 {s.n}명</span></h3>
                  {s.n_aff !== undefined && <small>영향권 {s.n_aff}명 · 전체 비율로 읽지 않음</small>}
                  <blockquote className="pp-quote">“{s.example}”</blockquote>
                </div>
              ))}
            </div>
          </section>
        )}

        {b.analysis.lenses && (
          <section className="pp-section" id="lenses">
            <SectionHead title="관점별 반응"
              desc="쟁점 묶음과 따로, 반응마다 ‘생계·비용 부담’, ‘형평성’, ‘정보 부족’ 같은 관점 12가지를 Jev가 붙였습니다. 아래 개별 응답에서 관점으로 거를 수 있습니다." />
            <JevReceipt meta={b.meta} stage="review" tasks={["lenses"]} note={`반응 ${b.reactions.length}건 × 관점 12개`} />
            <LensBars items={b.analysis.lenses.items} total={b.reactions.length} />
          </section>
        )}

        <section className="pp-section" id="voices">
          <SectionHead title={`개별 응답 (${b.reactions.length}명)`} desc="필터로 좁혀 볼 수 있습니다. 발언은 합성 인물(AI)의 응답을 그대로 옮겼습니다." />
          <VoicesExplorer personas={b.personas} reactions={b.reactions}
            segments={b.segments.map((s) => ({ id: s.id, label: s.label }))}
            issues={b.analysis.issues.map((it) => ({ id: it.id, title: it.title, member_ids: it.member_ids }))}
            lenses={(b.analysis.lenses?.items ?? []).filter((l) => l.n > 0).map((l) => ({ key: l.key, label: l.label, n: l.n }))} />
        </section>

        <section className="pp-section">
          <SectionHead title="실행 정보" />
          <div className="pp-grid-4">
            <StatTile label="대표 패널" value={`${b.analysis.overall.n}명`} note="시도×연령대×성별 층화" />
            <StatTile label="영향권 패널" value={`${b.analysis.overall_aff.n}명`} note="속성·키워드·의미 검색" />
            <StatTile label="반응 호출" value={`${b.meta.counts.react_calls ?? b.reactions.length}회`}
              note={`실패 ${b.meta.counts.failed ?? 0}건 · 인용 불일치 ${b.meta.counts.quote_mismatch ?? 0}건`} />
            <StatTile label="생성 시간" value={duration(seconds)} note={`모델 ${b.meta.models.react} · ${b.meta.models.synth}`} />
          </div>
          {b.meta.fallbacks.length > 0 && <ul className="pp-fallbacks">{b.meta.fallbacks.map((f) => <li key={f}>{f}</li>)}</ul>}
          <p className="pp-sub" style={{ marginTop: 12 }}>
            데이터 NVIDIA Nemotron-Personas-Korea(CC BY 4.0) · 인물 검색 korean-people-persona(SQLite·FTS5) · 의미 검색 Qwen3-Embedding-0.6B
          </p>
          <div className="pp-actions pp-no-print">
            <CopyLink />
            <Link href="/review/new/" className="krds-btn medium primary">미리 묻기</Link>
          </div>
        </section>
      </div>
    </div>
  );
}
