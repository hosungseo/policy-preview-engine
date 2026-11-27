"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";
import { ASK_KEY } from "@/components/home/AskBox";
import { inputGuide } from "@/lib/modelGuide";
import { api, ApiError, type Finding, type Notice, type NoticeText, type ServiceConfig } from "@/lib/reviewApi";
import QuestionEditor, { type QuestionValues } from "./QuestionEditor";
import ServiceGate from "./ServiceGate";

// Pull the reason and main contents of a central-government legislative notice into the form.
function NoticePicker({ onPick }: { onPick: (n: NoticeText) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ items: Notice[]; total: number | null; capped: boolean; source: "api" | "web" } | null>(null);
  const [picked, setPicked] = useState<NoticeText | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(task: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "가져오지 못했습니다. 다시 시도해 주세요.");
    }
    setBusy(false);
  }
  const search = () => run(async () => {
    setResults(await api<{ items: Notice[]; total: number | null; capped: boolean; source: "api" | "web" }>(`/api/lawmaking?q=${encodeURIComponent(query.trim())}`));
  });
  const pick = (notice: Notice) => run(async () => {
    const params = new URLSearchParams();
    if (notice.mapping_lbic_id && notice.announce_type) {
      params.set("mapping_lbic_id", notice.mapping_lbic_id);
      params.set("announce_type", notice.announce_type);
    }
    const suffix = params.size ? `?${params.toString()}` : "";
    const found = await api<NoticeText>(`/api/lawmaking/${notice.seq}${suffix}`);
    setPicked(found);
    onPick(found);
  });

  return (
    <details className="rv-notice">
      <summary>국민참여입법센터 입법예고에서 가져오기</summary>
      <div className="rv-notice-search">
        <input className="krds-input" aria-label="입법예고 이름 검색" value={query} maxLength={50} placeholder="법령 이름 일부 (예: 정보공개, 행정기본법)"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); search(); } }} />
        <button type="button" className="krds-btn medium secondary" disabled={busy || query.trim().length < 2} onClick={search}>
          {busy ? "찾는 중…" : "입법예고 검색"}</button>
      </div>
      {error && <p className="rv-error" role="alert">{error}</p>}
      {picked && <p className="form-hint">
        <a href={picked.url} target="_blank" rel="noreferrer">{picked.title}</a>의 내용을 {picked.source === "api" ? "국민참여입법센터 API" : "국민참여입법센터 공개 페이지"}에서 가져왔습니다.
        {picked.clipped && ` 전체 ${picked.full_length.toLocaleString()}자 가운데 앞부분만 들어갔으니 다듬어 주세요.`}</p>}
      {results && (results.items.length === 0
        ? <p className="form-hint">찾은 입법예고가 없습니다. 중앙부처 법령안만 검색됩니다.</p>
        : <><p className="form-hint">{results.total === null
            ? `국민참여입법센터 공개 목록에서 ${results.items.length.toLocaleString()}건을 표시합니다.`
            : `총 ${results.total.toLocaleString()}건${results.capped ? ` 중 ${results.items.length.toLocaleString()}건만 표시합니다.` : ""}`}</p>
          <ul className="rv-notice-list">{results.items.map((n) => (
            <li key={n.seq}><button type="button" disabled={busy} onClick={() => pick(n)}>
              <strong>{n.title}</strong>
              <span className="rv-muted">{[n.agency, n.kind, n.period].filter(Boolean).join(" · ")}</span>
            </button></li>))}</ul></>)}
    </details>
  );
}


function Form({ config }: { config: ServiceConfig }) {
  const [title, setTitle] = useState("");
  const [policy, setPolicy] = useState("");
  const [q, setQ] = useState<QuestionValues>({ question: "", options: ["찬성", "반대", "잘 모르겠다"] });
  const [findings, setFindings] = useState<Finding[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  // Start with the question typed into the landing-page box, once.
  useEffect(() => {
    try {
      const asked = sessionStorage.getItem(ASK_KEY);
      if (!asked) return;
      sessionStorage.removeItem(ASK_KEY);
      setQ((v) => ({ ...v, question: asked }));
    } catch { /* storage may be blocked */ }
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const found: string[] = [];
    if (!title.trim()) found.push("정책 이름을 입력해 주세요.");
    if (policy.trim().length < 30) found.push("정책 설명을 30자 이상 써 주세요. 응답자가 읽을 내용입니다.");
    if (!q.question.trim()) found.push("문항을 입력해 주세요.");
    if (q.options.filter((o) => o.trim()).length < 2) found.push("선택지를 2개 이상 넣어 주세요.");
    if (findings.some((f) => f.level === "block")) found.push("‘실행 불가’ 항목을 먼저 고쳐 주세요.");
    setProblems(found);
    if (found.length) return;
    setBusy(true);
    try {
      const { id } = await api<{ id: string }>("/api/surveys", { method: "POST", body: { title, policy_text: policy } });
      await api(`/api/surveys/${id}/runs`, { method: "POST",
        body: { question: q.question, options: q.options.filter((o) => o.trim()), future: !!q.future } });
      location.assign(`/review/view/?id=${id}`);
    } catch (e) {
      setProblems([e instanceof ApiError ? e.message : "저장하지 못했습니다. 다시 시도해 주세요."]);
      setBusy(false);
    }
  }

  return (
    <form className="pp-card rv-form" onSubmit={submit} noValidate>
      <NoticePicker onPick={(n) => { setTitle(n.title.replace(/\s*입법예고$/, "").slice(0, 100)); setPolicy(n.text); }} />
      <div className="form-group">
        <div className="form-tit"><label htmlFor="rv-title">정책 이름</label></div>
        <div className="form-conts"><input id="rv-title" className="krds-input" maxLength={100} value={title}
          onChange={(e) => setTitle(e.target.value)} placeholder="예: 고령층 시내버스 요금 지원" /></div>
      </div>
      <div className="form-group">
        <div className="form-tit"><label htmlFor="rv-policy">정책 설명 <span className="rv-muted">응답자가 읽는 내용</span></label></div>
        <div className="form-conts">
          <textarea id="rv-policy" className="krds-input rv-textarea" maxLength={config.max_policy} value={policy}
            onChange={(e) => setPolicy(e.target.value)} placeholder="누구에게, 무엇을, 언제부터 하는지 실제 안내문처럼 쉽게 쓰세요." />
        </div>
        <p className="form-hint">{policy.trim().length.toLocaleString()} / {config.max_policy.toLocaleString()}자 · {inputGuide(config.model_profile)}</p>
      </div>
      <QuestionEditor policyText={policy} values={q} onChange={setQ} config={config} onFindings={setFindings} />
      {problems.length > 0 && <div className="rv-error" role="alert"><ul>{problems.map((p) => <li key={p}>{p}</li>)}</ul></div>}
      <div className="pp-actions">
        <Link href="/review/" className="krds-btn large secondary">취소</Link>
        <button type="submit" className="krds-btn large primary" disabled={busy}>{busy ? "접수하는 중…" : "합성 국민에게 묻기"}</button>
      </div>
      <p className="rv-muted">합성 국민 {config.n.toLocaleString()}명에게 세 가지 방식으로 묻습니다(본 문항·대조 문장·찬반 순서 뒤집기). 보통 10분 안팎 걸리고, 창을 닫아도 계속됩니다. 하루 {config.daily_runs}번까지 돌릴 수 있습니다.</p>
    </form>
  );
}

export default function NewSurvey() {
  return <ServiceGate>{(_, config) => <Form config={config} />}</ServiceGate>;
}
