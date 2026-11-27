"use client";

import { useState, type FormEvent } from "react";
import { api, ApiError, accuracyFor, baselineFor, historicalFor, type FutureView, type Result, type Rule, type RuleView, type Run,
  type ServiceConfig } from "@/lib/reviewApi";
import { Findings } from "./QuestionEditor";
import VisitView from "./VisitView";

function TrustLine({ r, config }: { r: Result; config: ServiceConfig }) {
  const h = config.holdout;
  return (
    <ul className="rv-trust">
      <li title={h ? `통계청 2024 사회조사 중 결과를 보기 전에 고른 ${h.items}문항, ${h.measured_on} 실측 (${h.model})` : undefined}>
        실측 평균 오차 <b>{h ? `약 ${h.mae_pp}%p` : "미측정"}</b>
        {h && <span className="rv-muted"> (처음 보는 사회조사 {h.items}문항 · 이 판단 모델 · 이 문항의 오차 범위 아님)</span>}
      </li>
      <li title="정책 설명 끝에 내용 없는 문장 하나를 붙였을 때 움직인 크기">의미 없는 문장을 붙였을 때 변화 <b>{r.placebo_shift_pp}%p</b></li>
      <li title="찬반 선택지 순서만 거꾸로 했을 때 움직인 크기(‘잘 모르겠다’는 끝에 고정)" className={r.unstable ? "is-bad" : ""}>
        선택지 순서 흔들림 <b>{r.reversal_shift_pp}%p</b>
      </li>
    </ul>
  );
}

function signed(pp: number | null | undefined): string {
  return pp == null ? "-" : `${pp > 0 ? "+" : ""}${pp}%p`;
}

/** "5년 뒤 보기": the same people, asked again in their projected state. Only the top option is compared. */
function FutureBlock({ f, r }: { f: FutureView; r: Result }) {
  const top = r.options[r.top];
  const kinds = f.changed_kinds;
  const changedText = [kinds.working && `일 ${kinds.working}명`, kinds.province && `사는 곳 ${kinds.province}명`,
    kinds.marital && `혼인 ${kinds.marital}명`, kinds.income_q && `소득 분위 ${kinds.income_q}명`].filter(Boolean).join(", ");
  return (
    <section className="rv-future" aria-label="5년 뒤 보기">
      <h3 className="rv-future-title">5년 뒤 보기 <span className="rv-muted">같은 사람 {f.n.toLocaleString()}명을 {f.year}년의 상태로 굴려 다시 물음 · 예측 아님</span></h3>
      <p className="rv-future-line">
        ‘{top}’ 2025년 <b>{f.now_percent[r.top]}%</b> → {f.year}년 <b>{f.future_percent[r.top]}%</b>
        <span className={f.distinguishable ? "" : "rv-muted"}> ({signed(f.shift_pp)}, 구분 기준 {f.threshold_pp}%p → <b>{f.distinguishable ? "구분 가능" : "구분 불가"}</b>)</span>
      </p>
      <ul className="rv-method">
        <li>상태가 바뀐 사람 {f.changed_n.toLocaleString()}명{changedText && ` (${changedText})`}의 변화 {signed(f.shift_changed_pp)}, 바뀌지 않은 사람의 변화 {signed(f.shift_unchanged_pp)}. 나이만 다섯 살 더 먹어도 응답은 움직일 수 있습니다.</li>
        <li>상태 설명 글을 붙이는 것만으로 2025년 응답이 {f.format_shift_pp}%p 움직였습니다. 그보다 작은 차이는 구분하지 않습니다.</li>
        <li>나이·일·사는 곳·혼인·개인 근로·사업소득 금액을 공공통계의 연간 변화 확률로 2030년까지 굴린 가정입니다. 소득은 금액만 상태로 적고 개인의 변화는 적지 않았습니다. 그사이 성인이 되는 사람은 없고 사망 {f.dead.toLocaleString()}명은 뺐습니다. 가구 소득·주거 등 나머지 여건은 2025년 그대로입니다.</li>
      </ul>
      {f.age_groups.length > 0 && (
        <details className="rv-more">
          <summary>연령대별(2025년 기준) 보기</summary>
          <table className="rv-table">
            <thead><tr><th>2025년 연령대</th><th>응답자</th><th>2025년 ‘{top}’</th><th>{f.year}년 ‘{top}’</th><th>변화</th></tr></thead>
            <tbody>{f.age_groups.map((g) => (
              <tr key={g.group}><td>{g.group}</td><td>{g.n.toLocaleString()}명</td><td>{g.now_top}%</td><td>{g.future_top}%</td><td>{signed(g.shift_pp)}</td></tr>
            ))}</tbody>
          </table>
        </details>
      )}
    </section>
  );
}

type RuleForm = { income_max: string; income_min: string; working: "" | "yes" | "no"; age_min: string; age_max: string; capital: "" | "yes" | "no"; note: string };
const EMPTY_RULE: RuleForm = { income_max: "", income_min: "", working: "", age_min: "", age_max: "", capital: "", note: "" };

function ruleBody(f: RuleForm): Rule {
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  const tri = (s: "" | "yes" | "no") => (s === "" ? null : s === "yes");
  return { income_max_manwon: num(f.income_max), income_min_manwon: num(f.income_min), working: tri(f.working),
    age_min: num(f.age_min), age_max: num(f.age_max), capital: tri(f.capital), note: f.note.trim() };
}

/** "대상 규칙으로 나눠 보기": split a finished "5년 뒤 보기" run by who a rule fits. Computed on request, nothing is stored. */
function RuleBlock({ runId, result }: { runId: string; result: Result }) {
  const top = result.options[result.top];
  const [form, setForm] = useState<RuleForm>(EMPTY_RULE);
  const [view, setView] = useState<RuleView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const set = (k: keyof RuleForm) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { rule_view } = await api<{ rule_view: RuleView }>(`/api/runs/${runId}/rule`, { method: "POST", body: ruleBody(form) });
      setView(rule_view);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "요청하지 못했습니다.");
    }
    setBusy(false);
  }
  async function copy() {
    if (!view) return;
    try {
      await navigator.clipboard.writeText(view.copy_text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard may be blocked; the text is visible */ }
  }
  const shift = (g: RuleView["future_split"]["in"], small: string | null, label: string) => g
    ? <>{label} {g.n.toLocaleString()}명 <span className={g.distinguishable ? "" : "rv-dim"}>{g.now_top}% → {g.future_top}%({signed(g.shift_pp)})</span></>
    : <>{label} {small}</>;
  return (
    <section className="rv-future rv-rule" aria-label="대상 규칙으로 나눠 보기">
      <h3 className="rv-future-title">대상 규칙으로 나눠 보기 <span className="rv-muted">이 실행의 답을 규칙에 맞는 사람과 맞지 않는 사람으로 나눠 봅니다 · 실제 대상 인원·정책 효과 아님</span></h3>
      <details className="rv-more" open={!view}>
        <summary>규칙 적기</summary>
        <form className="rv-rule-form" onSubmit={submit}>
          <label>개인 근로·사업소득 연 상한(만 원)<input className="krds-input" inputMode="numeric" value={form.income_max} onChange={set("income_max")} /></label>
          <label>연 하한(만 원)<input className="krds-input" inputMode="numeric" value={form.income_min} onChange={set("income_min")} /></label>
          <label>일함 여부<select className="krds-input" value={form.working} onChange={set("working")}>
            <option value="">상관없음</option><option value="yes">일함</option><option value="no">일하지 않음</option></select></label>
          <label>만 나이 하한<input className="krds-input" inputMode="numeric" value={form.age_min} onChange={set("age_min")} /></label>
          <label>만 나이 상한<input className="krds-input" inputMode="numeric" value={form.age_max} onChange={set("age_max")} /></label>
          <label>지역<select className="krds-input" value={form.capital} onChange={set("capital")}>
            <option value="">상관없음</option><option value="yes">수도권</option><option value="no">비수도권</option></select></label>
          <label className="is-wide">규칙에 넣지 못한 기준(메모, 200자)
            <input className="krds-input" maxLength={200} value={form.note} onChange={set("note")}
              placeholder="패널에 없는 기준(가구소득·재산·자녀 수·주택·시도 등)은 여기에 적으세요. 판정에 쓰지 않고 결과에 그대로 보입니다." /></label>
          <div className="is-wide rv-actions"><button type="submit" className="krds-btn small primary" disabled={busy}>{busy ? "계산 중…" : "나눠 보기"}</button></div>
        </form>
        {error && <p className="rv-error" role="alert">{error}</p>}
      </details>
      {view && (
        <>
          <p className="rv-rule-line">
            이 규칙에 맞는 합성 인물(실제 대상 인원 아님): 2025년 상태로 <b>{view.y2025.n.toLocaleString()}명</b>({view.y2025.pct}%) · 2030년 상태로 <b>{view.y2030.n.toLocaleString()}명</b>({view.y2030.pct}%)
            <span className="rv-muted"> · 자료가 없어 판정하지 못한 수 2025년 {view.y2025.undetermined.toLocaleString()}명 · 2030년 {view.y2030.undetermined.toLocaleString()}명</span>
          </p>
          <p className="rv-rule-line">
            {shift(view.future_split.in, view.future_split.in_small, `2030년 상태가 규칙에 맞는`)} ‘{top}’(상태 블록을 붙인 답)
            {" · "}{shift(view.future_split.out, view.future_split.out_small, "맞지 않는")}
            {(view.future_split.in ?? view.future_split.out) && <span className="rv-muted"> · 이동의 믿을 수 있는 최소 차이 {(view.future_split.in ?? view.future_split.out)!.threshold_pp}%p</span>}
          </p>
          <p className="rv-rule-line">
            {view.main_split
              ? <>2025년 상태로 나눈 두 집단의 ‘{top}’ 차이(본 문항 답): 맞는 {view.main_split.in.n.toLocaleString()}명 {view.main_split.in.top}% − 맞지 않는 {view.main_split.out.n.toLocaleString()}명 {view.main_split.out.top}% = <b>{signed(view.main_split.diff_pp)}</b>
                <span className="rv-muted"> · 두 집단 차이의 믿을 수 있는 최소 차이 {view.main_split.threshold_pp}%p → <b>{view.main_split.distinguishable ? "최소 차이보다 큼" : "최소 차이보다 작음"}</b></span></>
              : <>2025년 상태로 나눈 두 집단 비교: {view.main_small}</>}
          </p>
          <details className="rv-more">
            <summary>규칙·메모·2030년 연령대 구성</summary>
            <ul className="rv-method">
              <li>규칙: {view.rule_text}{view.rule.note && <> · 규칙에 넣지 못한 기준: {view.rule.note}</>}</li>
              <li>2030년 상태가 규칙에 맞는 사람의 연령대(2030년 나이): {view.age_bands_2030.length ? view.age_bands_2030.map((g) => `${g.group} ${g.n.toLocaleString()}명`).join(", ") : "없음"}</li>
              <li>둘째 줄의 "지금"은 상태 블록을 붙인 답(2030년 상태로 나눈 집단), 셋째 줄은 본 문항 답(2025년 상태로 나눈 집단)이라 같은 사람이라도 값이 다릅니다.</li>
            </ul>
          </details>
          <div className="rv-copy">
            <button type="button" className="krds-btn small secondary" onClick={copy}>{copied ? "복사했습니다" : "이 결과 문장 복사"}</button>
          </div>
        </>
      )}
    </section>
  );
}

export default function ResultView({ run, config, visit = true }: { run: Run; config: ServiceConfig; visit?: boolean }) {
  const r = run.result as Result;
  const accuracy = accuracyFor(r);
  const addons = r.addons ?? [];
  const stateText = addons.length
    ? `생활 여건 애드온(${addons.map((a) => a.title).join(", ")})은 공표된 정부 조사·행정 통계에서 같은 지역·나이·성별·가구 특성으로 뽑은 가정입니다. 개인의 실제 정보가 아니며, 실제 여론을 뜻하지 않습니다.`
    : accuracy.state === "applied"
    ? "주거 점유 형태는 공공통계로 배정한 가정입니다. 개인의 실제 정보가 아니며, 실제 여론을 뜻하지 않습니다."
    : accuracy.state === "legacy" ? "과거 5개 진단 문항, 비교 정의 제한 있음. 이 실행의 보완 여부·모델판은 확인되지 않았습니다."
    : accuracy.state === "unverified" ? "공공통계 속성 보완 여부와 검증 상태를 확인할 수 없습니다."
    : "공공통계 속성 보완은 적용하지 않았습니다.";
  const historical = baselineFor(r) ? null : historicalFor(r);
  const baseline = baselineFor(r) ?? historical;
  const enrichment = addons.length ? `생활 여건 애드온 ${addons.length}종` : accuracy.state === "applied" ? "적용" : accuracy.state === "not_applied" ? "미적용" : "확인 전";
  const statusText = `실측 비교: ${historical ? "검증됨(과거 진단 5문항, 2024 사회조사) · 현재 모델판 동일성 미확인" : baseline?.mae_pp != null ? "검증됨" : "검증 전"} · 속성 보완: ${enrichment}`;
  const reasonLabels: Record<string, string> = {
    baseline_unavailable: "이 판의 실측 비교 결과가 아직 없습니다.",
    model_unverified: "응답 모델 판이 고정·확인되지 않았습니다.",
    model_unpinnable: "응답 모델 판을 고정할 수 없습니다.",
    enrichment_not_applied: "공공통계 속성 보완은 적용하지 않았습니다.",
    legacy_unversioned: "과거 실행의 자료판과 검증 이력을 확인할 수 없습니다.",
    fixture_unverified: "시험 자료의 검증 근거가 없습니다.",
    sex_adult_cross_table_missing: "성별·성인 교차 통계가 없어 성별 비교를 산출하지 못했습니다.",
    source_unverified: "공식 자료의 출처 검증이 완료되지 않았습니다.",
    fixed_weights_missing: "사전에 고정한 연령 가중치가 없습니다.",
    model_revision_unavailable: "실행 모델판을 확인할 수 없습니다.",
    reference_not_verified: "공공통계 참조 자료가 검증되지 않았습니다.",
    historical_development_only: "과거 개발 진단 5문항이며 독립 검증이나 새로운 정책 문항의 성능 검증이 아닙니다.",
    model_identity_unproven: "진단의 반환 모델 이름은 기록했지만 현재 실행과 불변 모델판의 동일성은 증명되지 않았습니다.",
    population_standard_caveat: "2024년 12월 주민등록인구를 공통 연령 표준으로 사용했습니다. 사회조사의 표본가구 범위·조사월과 다르며 공표 전국값 자체가 아닙니다.",
    historical_model_mismatch: "현재 실행의 모델 이름이 과거 진단 모델과 다르거나 확인되지 않았습니다.",
  };
  // Translate only known codes; unknown API diagnostics must never reach the UI.
  const reasons = [...accuracy.reasons, ...(accuracy.baseline?.excluded_reasons ?? []), ...(historical?.excluded_reasons ?? [])]
    .filter((reason) => !(addons.length && reason === "enrichment_not_applied"))
    .map((reason) => reasonLabels[reason] ?? "비교 검증에 필요한 조건이 아직 확인되지 않았습니다.");
  if (accuracy.baseline && !baseline) reasons.push(
    accuracy.baseline.inputs.model.model_revision !== accuracy.model_revision
      ? "기준선과 실행의 모델판이 달라 비교 수치를 표시하지 않습니다."
      : "이 실행에 적용할 수 있는 검증된 기준선이 없습니다.");
  const reasonText = [...new Set(reasons)].map((reason) => reason.replace(/\.$/, "")).join("; ");
  const comparison = baseline?.mae_pp != null
    ? `비교 문항 평균 절대 차이 ${baseline.mae_pp}%p. 이 문항의 오차 범위가 아닙니다.`
    : "이 모델·보완판의 실측 비교 검증 전. 비교 문항 평균 절대 차이는 미산출이며 이 문항의 오차 범위가 아닙니다.";
  const copyComparison = config.holdout
    ? `처음 보는 사회조사 ${config.holdout.items}문항에서 잰 이 판단 모델의 평균 오차는 약 ${config.holdout.mae_pp}%p이며, 이 문항의 오차 범위는 아닙니다.`
    : baseline?.mae_pp != null
    ? `${historical ? "과거 진단 5문항(2024 사회조사)의 " : ""}비교 문항 평균 절대 차이 ${baseline.mae_pp}%p이며, 이 문항의 오차 범위는 아닙니다.${historical ? " 현재 실행과 진단 모델판의 동일성은 미확인입니다." : ""}`
    : "실측 비교 검증 전이며 실제 조사로 확인이 필요합니다.";
  const caution = r.unstable ? `[주의: 선택지 순서만 바꿔도 ${r.reversal_shift_pp}%p 움직여 문항 재검토가 필요합니다] ` : "";
  const targetNote = r.splits.length
    ? `먼저 만나 확인할 집단: ${r.splits[0].high}·${r.splits[0].low}(${r.splits[0].axis}).`
    : "집단 간 뚜렷한 차이가 가려지지 않아 실제 현장 확인이 필요합니다.";
  const summaryText = `${caution}※ 실제 사람 응답 0명(합성 인물 ${r.n.toLocaleString()}명 기반 현장 질문·대상 탐색, 실제 여론조사 아님). ${targetNote} ${copyComparison}`;
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(summaryText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard may be blocked; the text is visible below */ }
  }
  return (
    <section className="rv-result" aria-label="결과">
      <p className="rv-label">실제 사람 응답 0명 · 합성 인물 {r.n.toLocaleString()}명 모의 탐색 · AI 추정 · 실제 여론조사 아님</p>
      <p className="rv-question">“{run.spec.question}”</p>
      {r.unstable && <p className="rv-alert">선택지 순서만 바꿔도 결과가 {r.reversal_shift_pp}%p 움직였습니다. 문항과 선택지를 다듬어 다시 확인해 주세요.</p>}
      {run.lint.filter((f) => f.level !== "info").length > 0 && (
        <div className="rv-result-lint"><Findings findings={run.lint.filter((f) => f.level !== "info")} /></div>
      )}
      {visit && <VisitView run={run} />}
      {/* With the visit cards on screen, the cards are the next step; only a question that needs fixing is still called out. */}
      {(!visit || r.next_action.kind === "fix_question") && (
        <p className={`rv-next is-${r.next_action.kind}`}><b>다음 할 일</b> {r.next_action.text}
          {r.next_action.kind === "fix_question" && <> <a href="#rerun" className="rv-next-link">고쳐서 다시 묻기 ↓</a></>}</p>
      )}
      <div className="rv-copy">
        <button type="button" className="krds-btn small secondary" onClick={copy}>{copied ? "복사했습니다" : "요약 문장 복사"}</button>
        <span className="rv-muted">{summaryText}</span>
      </div>
      <details className="rv-more rv-internal-metrics">
        <summary>참고용 내부 지표 (모의 선택지 분포 · 외부 보고·인용 금지)</summary>
        <p className="rv-muted">※ 실제 사람 응답 0명. 아래 분포는 집단 선별과 흔들림 점검을 위한 참고용 내부 지표이며, 찬반 비율이나 여론으로 인용할 수 없습니다.</p>
        <ol className={`rv-bars${r.unstable ? " is-unstable" : ""}`}>
          {r.options.map((o, i) => (
            <li key={o} className={i === r.top ? "is-top" : ""}>
              <span className="rv-bar-label">{o}</span>
              <span className="rv-bar"><span style={{ width: `${r.percent[i]}%` }} /></span>
              <span className="rv-bar-num">{r.percent[i]}%</span>
            </li>
          ))}
        </ol>
      </details>
      <details className="rv-more rv-evidence">
        <summary>응답 흔들림·검증 근거 (참고용 내부 지표)</summary>
        <TrustLine r={r} config={config} />
        <p className="rv-split">
          {r.splits.length
            ? <>모의 응답에서의 차이가 가장 큰 집단: <b>{r.splits[0].high}</b> · <b>{r.splits[0].low}</b> ({r.splits[0].axis})</>
            : <>집단(연령대·성별·수도권 여부) 간 차이는 구분할 수 있을 만큼 크지 않습니다.</>}
        </p>
        {r.future && <FutureBlock f={r.future} r={r} />}
        {r.future && config.future_available && <RuleBlock runId={run.id} result={r} />}
      </details>
      <details className="rv-more">
        <summary>참고용 내부 지표 · 집단별 세부 보기</summary>
        {r.axes.map((a) => (
          <div key={a.axis} className="rv-axis">
            <h4>{a.axis} <span className="rv-muted">‘{r.options[r.top]}’ 비율</span></h4>
            <table className="rv-table">
              <thead><tr><th>집단</th><th>응답자</th>{r.options.map((o) => <th key={o}>{o}</th>)}</tr></thead>
              <tbody>{a.groups.map((g) => (
                <tr key={g.group}><td>{g.group}</td><td>{g.n.toLocaleString()}명</td>
                  {(g.percent ?? []).map((p, i) => <td key={i} className={i === r.top ? "is-top" : ""}>{p}%</td>)}</tr>
              ))}</tbody>
            </table>
            {a.diff_pp !== undefined && (
              <p className="rv-muted">
                최고·최저 차이 {a.diff_pp}%p, 구분 기준 {a.threshold_pp}%p
                (실제 조사였다면의 표집 폭 {a.parts?.sampling} · 대조 문장 차이 {a.parts?.placebo} · 순서 흔들림 차이 {a.parts?.reversal}, 최소 3) →{" "}
                <b>{a.distinguishable ? "구분 가능" : "구분 불가"}</b>
              </p>
            )}
          </div>
        ))}
      </details>
      <details className="rv-more">
        <summary>방법과 한계</summary>
        <ul className="rv-method">
          {!config.holdout && <li>{statusText}</li>}
          {(r.accuracy ? r.cautions ?? [] : []).filter((c) => !(addons.length && c.startsWith("생활 여건 애드온"))).map((c) => <li key={c}>{c}</li>)}
          <li>{stateText}{accuracy.state === "applied" && <> 배정 적용 비율 {accuracy.applied_rate == null ? "확인 전" : `${Math.round(accuracy.applied_rate * 100)}%`}.</>}</li>
          <li>{config.holdout ? `실측 평균 오차는 통계청 2024 사회조사에서 결과를 보기 전에 고른 ${config.holdout.items}문항으로 ${config.holdout.measured_on}에 잰 값입니다(판단 모델 ${config.holdout.model}). 이 문항의 오차 범위가 아닙니다.` : comparison}</li>
          {historical && <li>과거 진단 모델: {historical.inputs.model.model_revision} · 정순 평균 차이 {historical.mae_pp}%p · 역순 {historical.reverse_mae_pp}%p. 결혼·재혼의 6개 선택지는 현재 서비스 입력 범위 밖의 진단입니다.</li>}
          {!config.holdout && reasonText && <li>{reasonText}.</li>}
          <li>응답자는 실제 사람이 아닙니다. NVIDIA Nemotron-Personas-Korea(합성 인물 100만 명, CC BY 4.0)에서 시도·연령대·성별 비율대로 뽑은 2만 명 패널 중 {r.n.toLocaleString()}명이고, 판정 모델 {run.jev_model ?? "확인 전"}가 사람마다 선택지 확률을 냈습니다. 비율은 그 확률의 평균입니다.</li>
          <li>공공통계는 인물의 조건을 보완할 뿐 실제 사람의 의견을 관측하지 않습니다. 원본 속성과 배정 가정은 다릅니다. 개인 단위와 가구 단위 통계는 서로 바꿔 쓸 수 없습니다.</li>
          {!config.holdout && <li>검증 범위: {accuracy.scope ? `${accuracy.scope.year}년 · ${accuracy.scope.population} · 개인 단위` : "확인 전"}. 미상·조건 완화 비율, 검증 분야·미검증 분야 및 자료·평가판은 확인 전입니다.</li>}
          {!config.holdout && <li>모델판: {accuracy.model_revision ?? "확인 전"} · 자료판: {accuracy.manifest_hash ?? "확인 전"}</li>}
          <li>모의 응답에서의 차이와 구분 기준은 실제 모집단의 통계적 유의성을 뜻하지 않습니다.</li>
          <li>정책 설명 끝에 내용 없는 문장을 붙인 판(대조)과 찬반 선택지 순서를 뒤집은 판(‘잘 모르겠다’는 끝에 고정)을 같은 사람들에게 함께 물었습니다. 그 움직임보다 작은 차이는 구분하지 않습니다.</li>
          <li>표본오차·신뢰수준은 실제 확률 표본에만 쓰는 표현이라 적지 않습니다. 결과를 ‘여론조사’나 ‘국민 ○%’로 인용하지 마세요.</li>
          <li>패널 판 {run.panel_version ?? "-"} · 실행 {run.id}</li>
        </ul>
      </details>
    </section>
  );
}
