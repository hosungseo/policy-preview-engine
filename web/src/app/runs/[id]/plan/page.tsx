import type { Metadata } from "next";
import AiNotice from "@/components/AiNotice";
import PrintButton from "@/components/PrintButton";
import RunHeader from "@/components/RunHeader";
import { getRun, runParams } from "@/lib/bundles";
import { pct, signed } from "@/lib/format";
import "./plan.css";

export const dynamicParams = false;
export function generateStaticParams() {
  return runParams();
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `의견수렴 계획서 · ${getRun(id).title}` };
}

function pp(v: number): string {
  const x = Math.abs(v) < 0.0005 ? 0 : v;
  return `${x > 0 ? "+" : ""}${(x * 100).toFixed(1)}%p`;
}

export default async function PlanPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const b = getRun(id);
  const plan = b.plan;
  const issueTitle = new Map(b.analysis.issues.map((it) => [it.id, it.title]));
  return (
    <div>
      <AiNotice extra="계획서는 합성 인물(AI) 반응을 바탕으로 만든 초안입니다. 실제 의견수렴 결과가 아닙니다." />
      <RunHeader bundle={b} active="plan" />
      <div className="pp-container pp-section">
        <div className="pp-actions pp-no-print" style={{ justifyContent: "flex-end", marginBottom: 12 }}><PrintButton /></div>
        <article className="pp-doc">
          <header className="pp-doc-head">
            <p className="pp-doc-stamp">AI 초안</p>
            <h2 className="pp-doc-title">「{plan.overview.title}」<br />의견수렴 계획(안)</h2>
            <p className="pp-doc-date">{plan.overview.created_at} · 합성 패널 사전 점검 결과 기반</p>
          </header>

          <section>
            <h3>Ⅰ. 개요</h3>
            <ul className="pp-doc-sq">
              <li>대상: {plan.overview.title} ({plan.overview.kind})</li>
              {plan.overview.agency && <li>소관: {plan.overview.agency}</li>}
              <li>사전 점검: {plan.overview.panel}의 합성 인물 반응</li>
              {b.source.period && <li>의견제출 기간: {b.source.period}</li>}
            </ul>
          </section>

          <section>
            <h3>Ⅱ. 예상 쟁점</h3>
            {plan.issues.map((it) => (
              <div key={it.id} className="pp-doc-item">
                <p className="pp-doc-o">○ {it.title} <span>(대표 패널 반응의 {pct(it.share)}, {it.n}명, 평균 지지 {signed(it.mean)}
                  {it.jev_mean !== undefined && <>, 대표 패널 제기 확률 {pct(it.jev_mean)}</>})</span></p>
                {it.by_panel && <p className="pp-doc-dash">- 영향권 {it.by_panel.aff.n}명 · {pct(it.by_panel.aff.share)} (전체 비율로 읽지 않음)</p>}
                <p className="pp-doc-dash">- {it.summary}<span className="pp-tag-ai">AI 작성</span></p>
                {it.segments.length > 0 && <p className="pp-doc-dash">- 관련 조항: {it.segments.join(", ")}</p>}
                {it.groups.length > 0 && <p className="pp-doc-dash">- 두드러진 집단: {it.groups.join(", ")}</p>}
                {it.quote && <p className="pp-doc-quote">“{it.quote}”</p>}
              </div>
            ))}
          </section>

          <section>
            <h3>Ⅲ. 찾아가 들어야 할 집단</h3>
            <div className="pp-doc-table-wrap">
              <table className="pp-doc-table">
                <thead><tr><th>집단</th><th>규모·반응</th><th>방식</th><th>장소·경로</th><th>시기</th></tr></thead>
                <tbody>
                  {plan.outreach.map((o) => (
                    <tr key={(o.panel || "") + o.kind + o.group}>
                      <td><b>{o.group}</b><br /><small>{o.kind} · {o.panel === "aff" ? "영향권: 전체 비율로 읽지 않음" : "대표 패널"}</small></td>
                      <td>{o.n}명<br /><small>반대·유보 {pct(o.oppose)} · 스스로 안 나섬 {pct(o.silent)}</small></td>
                      <td>{o.suggestion.method}
                        {o.methods && o.methods.length > 0 && (
                          <><br /><small>참여 확률 높은 방식: {o.methods.map((m) => `${m.label} ${pct(m.p)}`).join(" · ")}</small></>
                        )}
                      </td>
                      <td>{o.suggestion.where}</td>
                      <td>{o.suggestion.when}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="pp-doc-note">방식·장소·시기는 AI 제안이고, ‘스스로 안 나섬’과 방식별 참여 확률은 Jev가 추정한 값입니다. 현장 확인이 필요합니다.</p>
          </section>

          <section>
            <h3>Ⅳ. 준비할 설명 자료(예상 질문)<span className="pp-tag-ai">AI 작성</span></h3>
            {plan.qa.some((q) => q.jev_p !== undefined) && (
              <p className="pp-doc-note" style={{ marginTop: 0 }}>질문과 답변은 AI가 쓰고, 순서는 정량 패널 표본에게 “이 질문의 답을 듣고 싶은가”를 물은 확률(Jev 추정)이 높은 순입니다.</p>
            )}
            {plan.explain && (
              <div className="pp-doc-item">
                <p className="pp-doc-o">○ 먼저 설명할 조항 <span>(Jev 추정)</span></p>
                {plan.explain.clauses.map((c, i) => (
                  <p key={c.segment_id} className="pp-doc-dash">- {i + 1}순위 {c.label} <small>(설명이 가장 필요하다고 고를 확률 {pct(c.p)})</small></p>
                ))}
                <p className="pp-doc-dash">- 원문만으로 자기에게 무엇이 바뀌는지 이해할 확률 {pct(plan.explain.understand)}
                  {plan.explain.hardest && <>, 가장 낮은 학력 집단은 {plan.explain.hardest.group}({pct(plan.explain.hardest.mean)})</>}</p>
              </div>
            )}
            {plan.qa.map((q) => (
              <div key={q.question} className="pp-doc-qa">
                <p><b>Q.</b> {q.question} <small>(쟁점: {issueTitle.get(q.issue_id)}
                  {q.jev_p !== undefined && <> · 패널 {q.jev_n?.toLocaleString()}명 중 물을 확률 {pct(q.jev_p)}
                    {q.jev_leaders && q.jev_leaders.length > 0 && <>, 특히 {q.jev_leaders.map((l) => `${l.group} ${pct(l.mean)}`).join(", ")}</>}</>})</small></p>
                <p><b>A.</b> {q.answer}</p>
              </div>
            ))}
          </section>

          {plan.suggestions.length > 0 && (
            <section>
              <h3>Ⅴ. 보완 검토 사항</h3>
              {plan.clarity && (plan.clarity.clauses.length > 0 || plan.clarity.missing.length > 0) && (
                <div className="pp-doc-item">
                  <p className="pp-doc-o">○ 정책문 보완 <span>(Jev 명료성 점검, 확률 50% 이상 지표)</span></p>
                  {[...plan.clarity.clauses].sort((a, c) => c.flags.length - a.flags.length).slice(0, 4).map((c) => (
                    <p key={c.segment_id} className="pp-doc-dash">- {c.label}: {c.flags.slice(0, 3).map((f) => `${f.label} ${pct(f.p)}`).join(", ")}
                      {c.flags.length > 3 && ` 외 ${c.flags.length - 3}개`}</p>
                  ))}
                  {plan.clarity.clauses.length > 4 && <p className="pp-doc-dash">- 그 밖에 조항 {plan.clarity.clauses.length - 4}개도 지표에 걸림(정책문 쟁점 지도 화면 참고)</p>}
                  {plan.clarity.missing.length > 0 && (
                    <p className="pp-doc-dash">- 본문에 없는 듯한 안내: {plan.clarity.missing.map((m) => m.label).join(", ")}</p>
                  )}
                </div>
              )}
              {plan.alternatives && plan.alternatives.length > 0 && (
                <>
                  <p className="pp-doc-o">○ 수정안 비교 <span>(같은 {plan.alternatives[0].n.toLocaleString()}명에게 원안과 비교
                    {plan.alternatives[0].net_reserve !== undefined && ", 내용 없는 대조 문장 효과를 뺀 값"}, Jev 추정)</span></p>
                  <div className="pp-doc-table-wrap">
                    <table className="pp-doc-table">
                      <colgroup><col style={{ width: "52%" }} /><col style={{ width: "14%" }} /><col style={{ width: "14%" }} /><col /></colgroup>
                      <thead><tr><th>수정안(AI 작성)</th><th>반대·유보</th><th>찬성 쪽</th><th>크게 움직인 집단</th></tr></thead>
                      <tbody>
                        {plan.alternatives.map((a) => (
                          <tr key={a.id}>
                            <td><b>{a.title}</b><br /><small>{a.text}</small></td>
                            <td>{pp(a.net_reserve ?? a.d_reserve)}</td>
                            <td>{pp(a.net_favor ?? a.d_favor)}</td>
                            <td><small>{a.movers.map((m) => `${m.group} ${signed(m.net_mean ?? m.d_mean)}`).join(", ") || "–"}</small></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
              {plan.suggestions.map((s) => (
                <p key={s.title} className="pp-doc-o">
                  ○ {s.title} <span>(대표 {s.n}명{s.n_aff !== undefined && ` · 영향권 ${s.n_aff}명: 전체 비율로 읽지 않음`})</span><br />
                  <span className="pp-doc-quote-inline">“{s.example}”</span>
                </p>
              ))}
            </section>
          )}

          <section>
            <h3>Ⅵ. 한계</h3>
            <ul className="pp-doc-sq">{plan.limits.map((l) => <li key={l}>{l}</li>)}</ul>
          </section>
        </article>
      </div>
    </div>
  );
}
