"use client";

import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, type Finding, kst, type Run, type ServiceConfig, type Survey } from "@/lib/reviewApi";
import QuestionEditor, { type QuestionValues } from "./QuestionEditor";
import DeepView from "./DeepView";
import ResultView from "./ResultView";
import ServiceGate from "./ServiceGate";

function Progress({ run }: { run: Run }) {
  const pct = run.total ? Math.floor((100 * run.done) / run.total) : 0;
  return (
    <div className="rv-job is-running" role="status" aria-live="polite">
      <span className="rv-spinner" aria-hidden="true" />
      <div className="rv-progress-body">
        <b>{run.status === "queued" ? "차례를 기다리는 중" : `응답 받는 중 · ${pct}%`}</b>
        <span className="rv-progressbar"><span style={{ width: `${pct}%` }} /></span>
        <p className="rv-muted">창을 닫아도 서버에서 계속됩니다. 다시 열면 이어서 볼 수 있습니다.</p>
      </div>
    </div>
  );
}

function Rerun({ survey, config, last, onStarted }: { survey: Survey; config: ServiceConfig; last: Run | null; onStarted: (r: Run) => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState<QuestionValues>({ question: last?.spec.question ?? "", options: last?.spec.options ?? ["찬성", "반대", "잘 모르겠다"],
    future: !!last?.spec.future });
  const [findings, setFindings] = useState<Finding[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (findings.some((f) => f.level === "block")) { setError("‘실행 불가’ 항목을 먼저 고쳐 주세요."); return; }
    setBusy(true);
    try {
      const { run } = await api<{ run: Run }>(`/api/surveys/${survey.id}/runs`, { method: "POST",
        body: { question: q.question, options: q.options.filter((o) => o.trim()), future: !!q.future } });
      onStarted(run);
      setOpen(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "요청하지 못했습니다.");
    }
    setBusy(false);
  }
  if (!open) return <button type="button" className="krds-btn medium secondary" onClick={() => setOpen(true)}>고쳐서 다시 묻기</button>;
  return (
    <form className="pp-card rv-form" onSubmit={submit}>
      <QuestionEditor policyText={survey.policy_text} values={q} onChange={setQ} config={config} onFindings={setFindings} />
      {error && <p className="rv-error" role="alert">{error}</p>}
      <div className="rv-actions">
        <button type="submit" className="krds-btn medium primary" disabled={busy}>{busy ? "접수하는 중…" : "다시 돌리기"}</button>
        <button type="button" className="krds-btn medium secondary" onClick={() => setOpen(false)}>취소</button>
      </div>
    </form>
  );
}

function Earlier({ runs, config }: { runs: Run[]; config: ServiceConfig }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!runs.length) return null;
  return (
    <section className="rv-earlier">
      <h3 className="pp-h3">이전에 돌린 문항 <span className="rv-count">{runs.length}</span></h3>
      <ul>
        {runs.map((r) => (
          <li key={r.id}>
            <button type="button" className="rv-earlier-row" onClick={() => setOpen(open === r.id ? null : r.id)} aria-expanded={open === r.id}>
              <span>“{r.spec.question}”</span>
              <span className="rv-muted">
                {r.result ? (r.result.unstable ? "문항 재검토 필요 ⚠" : "탐색 완료") : r.status_label} · {kst(r.created_at)}
              </span>
            </button>
            {open === r.id && r.result && <ResultView run={r} config={config} visit={false} />}
          </li>
        ))}
      </ul>
    </section>
  );
}

function View({ id, config }: { id: string; config: ServiceConfig }) {
  const [survey, setSurvey] = useState<Survey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      setSurvey(await api<Survey>(`/api/surveys/${id}`));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "미리보기를 찾을 수 없습니다. 삭제되었거나 다른 사용자의 기록입니다." : "불러오지 못했습니다. 새로 고쳐 주세요.");
    }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const current = survey?.runs[0] ?? null;
  const active = current && (current.status === "queued" || current.status === "running");
  useEffect(() => {
    if (!active || !current) return;
    const t = setInterval(async () => {
      try {
        const { run } = await api<{ run: Run }>(`/api/runs/${current.id}`);
        if (run.status === "queued" || run.status === "running") setSurvey((s) => (s ? { ...s, runs: [run, ...s.runs.slice(1)] } : s));
        else load();
      } catch { /* keep polling */ }
    }, 2000);
    return () => clearInterval(t);
  }, [active, current, load]);

  async function retry() {
    if (!current || busy) return;
    setBusy(true);
    try {
      const { run } = await api<{ run: Run }>(`/api/runs/${current.id}/retry`, { method: "POST" });
      setSurvey((s) => (s ? { ...s, runs: [run, ...s.runs] } : s));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "다시 시도하지 못했습니다.");
    }
    setBusy(false);
  }
  async function remove() {
    if (!window.confirm("이 미리보기와 결과를 모두 지웁니다. 되돌릴 수 없습니다. 지울까요?")) return;
    await api(`/api/surveys/${id}`, { method: "DELETE" });
    location.assign("/review/");
  }

  if (error && !survey) return <div className="pp-card rv-empty"><p className="rv-error" role="alert">{error}</p><Link href="/review/">목록으로</Link></div>;
  if (!survey) return <p className="rv-muted" role="status">불러오는 중…</p>;
  return (
    <div className="rv-view">
      <p className="rv-crumb"><Link href="/review/">‹ 목록</Link></p>
      <h1 className="pp-h2">{survey.title}</h1>
      <details className="rv-policy"><summary>응답자가 읽은 정책 설명</summary><p>{survey.policy_text}</p></details>
      {error && <p className="rv-error" role="alert">{error}</p>}
      {current && active && <Progress run={current} />}
      {current?.status === "failed" && (
        <div className="rv-job is-failed" role="alert">
          <div><b>결과를 만들지 못했습니다</b><p>{current.error_message ?? "처리 중 오류가 발생했습니다."}</p>
            <p className="rv-muted">받은 응답은 저장되어 있어, 다시 시도하면 남은 사람에게만 묻습니다.</p></div>
          <button type="button" className="krds-btn medium primary" onClick={retry} disabled={busy}>다시 시도</button>
        </div>
      )}
      {current?.status === "succeeded" && current.result && <ResultView run={current} config={config} />}
      {current?.status === "succeeded" && current.result && <DeepView key={current.id} run={current} />}
      <div id="rerun" />
      {!active && <Rerun survey={survey} config={config} last={current} onStarted={(r) => setSurvey((s) => (s ? { ...s, runs: [r, ...s.runs] } : s))} />}
      <Earlier runs={survey.runs.slice(1).filter((r) => r.status === "succeeded")} config={config} />
      <p className="rv-foot"><button type="button" className="rv-link" onClick={remove}>이 기록 삭제</button></p>
    </div>
  );
}

export default function SurveyView() {
  const [id, setId] = useState<string | null>(null);
  useEffect(() => { setId(new URLSearchParams(location.search).get("id")); }, []);
  return (
    <ServiceGate>
      {(_, config) => (id ? <View id={id} config={config} /> : <p className="rv-muted">번호가 없습니다. <Link href="/review/">목록으로</Link></p>)}
    </ServiceGate>
  );
}
