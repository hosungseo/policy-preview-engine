"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Deep, type DeepResult, type DeepWho, type Run } from "@/lib/reviewApi";

function who(p: DeepWho): string {
  return `${p.age}세 ${p.sex} · ${p.province} · ${p.occupation}`;
}

/** 을/를 by the last syllable's final consonant (anything else gets 을(를)). */
function obj(word: string): string {
  const c = word.trim().slice(-1).charCodeAt(0);
  if (c < 0xac00 || c > 0xd7a3) return "을(를)";
  return (c - 0xac00) % 28 ? "을" : "를";
}

function Points({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <li><b>{title}</b>{items.map((t) => <p key={t}>{t}</p>)}</li>
  );
}

function Voices({ r }: { r: DeepResult }) {
  return (
    <div className="rv-deep-options">
      {r.by_option.map((o) => o.voices.length === 0 ? (
        <p key={o.option} className="rv-muted rv-deep-none">‘{o.option}’{obj(o.option)} 고른 사람은 이유를 쓴 {r.counts.matched}명 가운데 없었습니다.</p>
      ) : (
        <details key={o.option} className="rv-more">
          <summary>‘{o.option}’{obj(o.option)} 고른 가상 인물의 이유 <span className="rv-muted">{o.n}명{o.voices.length < o.n && ` 중 ${o.voices.length}명 발췌`}</span></summary>
          <ul className="rv-deep-voices">
            {o.voices.map((v) => (
              <li key={v.rid}>
                <p>{v.reason}</p>
                <span className="rv-muted">합성 인물 · {who(v)}</span>
              </li>
            ))}
          </ul>
        </details>
      ))}
    </div>
  );
}

function Done({ r }: { r: DeepResult }) {
  const first = [...r.issues].sort((a, b) => b.n - a.n)[0];
  return (
    <>
      {r.mock && <p className="rv-alert">언어 모델이 연결되지 않아 자리 채움 글로 만든 결과입니다. 내용을 읽을 수 없습니다.</p>}
      <p className="rv-deep-lead">
        조사 응답자 <b>{r.counts.matched.toLocaleString()}명</b>과 정책이 직접 닿는 <b>{r.counts.affected.toLocaleString()}명</b>, 모두 {r.counts.heard.toLocaleString()}명의 처지에서 AI가 이유를 썼습니다.
        {first && <> 대표 패널에서 가장 많이 나온 쟁점은 <b>{first.title}</b>입니다.</>}
        <span> 영향권 수치는 전체 비율로 읽지 않음.</span>
      </p>
      <Voices r={r} />
      {r.issues.length > 0 && (
        <details className="rv-more">
          <summary>예상 쟁점 {r.issues.length}가지</summary>
          <ul className="rv-deep-list">
            {r.issues.map((it) => (
              <li key={it.id}>
                <b>{it.title}</b> <span className="rv-muted">대표 패널 {it.n}명</span>
                {it.by_panel && <span className="rv-muted"> · 영향권 {it.by_panel.aff.n}명 (전체 비율로 읽지 않음)</span>}
                <p>{it.summary}</p>
                {it.quotes.map((q, i) => (
                  <blockquote key={i}>{q.text}<span className="rv-muted"> 합성 인물 · {who(q)}</span></blockquote>
                ))}
              </li>
            ))}
          </ul>
        </details>
      )}
      {r.outreach.length > 0 && (
        <details className="rv-more">
          <summary>실제로 찾아가 들어야 할 집단</summary>
          <ul className="rv-deep-list">
            {r.outreach.map((o) => (
              <li key={(o.panel || "") + o.kind + o.group}>
                <b>{o.group}</b>
                <span className="rv-muted"> {o.panel === "aff" ? "영향권: 전체 비율로 읽지 않음" : "대표 패널"} {o.n}명</span>
                {o.suggestion?.method && <p>{[o.suggestion.method, o.suggestion.where, o.suggestion.when].filter(Boolean).join(" · ")}</p>}
                {o.suggestion?.why && <p className="rv-muted">{o.suggestion.why}</p>}
              </li>
            ))}
          </ul>
        </details>
      )}
      {r.alternatives.length > 0 && (
        <details className="rv-more">
          <summary>합성 인물이 낸 수정안 {r.alternatives.length}가지</summary>
          <ul className="rv-deep-list">
            {r.alternatives.map((a) => (
              <li key={a.title}><b>{a.title}</b><p>{a.text}</p></li>
            ))}
          </ul>
        </details>
      )}
      <details className="rv-more">
        <summary>가상 공청회와 의견수렴 계획서 초안</summary>
        <p className="rv-muted">합성 인물 {r.hearing.participants}명이 사회자와 주고받은 발언 {r.hearing.turns}건을 읽은 요약입니다.</p>
        <ul className="rv-deep-list">
          <Points title="의견이 모인 점" items={r.hearing.summary?.agreements} />
          <Points title="의견이 갈린 점" items={r.hearing.summary?.disagreements} />
          <Points title="공청회에 없던 당사자(직접 들어 볼 사람)" items={r.hearing.summary?.missing} />
          {r.qa.length > 0 && <li className="rv-deep-subhead"><b>예상 질문과 답변 준비</b></li>}
          {r.qa.map((q) => (
            <li key={q.question}><b>{q.question}</b><p>{q.answer}</p></li>
          ))}
        </ul>
      </details>
      <details className="rv-more">
      <summary>방법과 한계</summary>
      <ul className="rv-method">
        <li>이유와 수정안은 모두 언어 모델이 합성 인물의 처지에서 쓴 글입니다. 실제 사람의 말이 아니며, 여론을 예측하지 않습니다.</li>
        <li>들은 사람은 위 조사에 답한 응답자 가운데서 인구 구성에 맞춰 뽑았고, 정책이 직접 닿는 사람 {r.counts.affected}명을 따로 더했습니다.</li>
        {(r.coverage ?? []).map((c) => (
          <li key={c.step} className={c.status === "완료" ? undefined : "rv-coverage-short"}>
            {c.step}: 계획 {c.planned.toLocaleString()}건 중 {c.done.toLocaleString()}건 응답 ({c.status})
            {c.status !== "완료" && " — 응답하지 못한 사람은 결과에 들어가지 않았습니다. 의견이 없었다는 뜻이 아닙니다."}
          </li>
        ))}
        {r.limits.slice(0, 3).map((l) => <li key={l}>{l}</li>)}
      </ul>
      </details>
    </>
  );
}

/** 심층 분석: continues from a finished survey run and hears the same respondents one by one. */
export default function DeepView({ run }: { run: Run }) {
  const [deep, setDeep] = useState<Deep | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const path = `/api/runs/${run.id}/deep`;
  const load = useCallback(async () => {
    try {
      setDeep((await api<{ deep: Deep | null }>(path)).deep);
    } catch {
      setDeep((d) => d ?? null);  // an older server has no deep analysis; show nothing more than the button
    }
  }, [path]);
  const active = deep?.status === "queued" || deep?.status === "running";

  useEffect(() => {
    const first = setTimeout(load, 0);
    if (!active) return () => clearTimeout(first);
    const timer = setInterval(load, 3000);
    return () => { clearTimeout(first); clearInterval(timer); };
  }, [load, active]);

  const start = async () => {
    setBusy(true);
    setError("");
    try {
      setDeep((await api<{ deep: Deep }>(path, { method: "POST" })).deep);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "심층 분석을 시작하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  if (deep === undefined) return null;
  return (
    <section className="rv-deep" aria-label="심층 분석">
      <h3 className="rv-future-title">왜 그렇게 답했나 <span className="rv-muted">같은 응답자의 처지에서 AI가 쓴 이유와 쟁점 · 실제 사람의 말 아님</span></h3>
      {!deep && (
        <div className="rv-copy">
          <button type="button" className="krds-btn medium secondary" onClick={start} disabled={busy}>심층 분석 시작</button>
          <span className="rv-muted">수백 명의 이유를 듣고 쟁점·수정안·의견수렴 계획서 초안까지 만듭니다. 몇십 분 걸릴 수 있습니다.</span>
        </div>
      )}
      {active && deep && (
        <div className="rv-job is-running" role="status" aria-live="polite">
          <span className="rv-spinner" aria-hidden="true" />
          <div className="rv-progress-body">
            <b>{deep.status === "queued" || !deep.stage ? "차례를 기다리는 중" : `${deep.stage_label} · ${deep.stage_index}/${deep.stage_total}`}</b>
            <span className="rv-progressbar"><span style={{ width: `${Math.round((100 * deep.stage_index) / deep.stage_total)}%` }} /></span>
            <p className="rv-muted">창을 닫아도 서버에서 계속됩니다.</p>
          </div>
        </div>
      )}
      {deep?.status === "failed" && (
        <div className="rv-job is-failed" role="alert">
          <div><b>심층 분석을 마치지 못했습니다</b><p>{deep.error_message ?? "처리 중 오류가 발생했습니다."}</p></div>
          <button type="button" className="krds-btn medium primary" onClick={start} disabled={busy}>다시 시도</button>
        </div>
      )}
      {error && <p className="rv-error" role="alert">{error}</p>}
      {deep?.status === "succeeded" && deep.result && <Done r={deep.result} />}
    </section>
  );
}
