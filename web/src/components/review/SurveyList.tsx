"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, kst, STATUS_LABEL, type SurveySummary } from "@/lib/reviewApi";
import ServiceGate from "./ServiceGate";

function List() {
  const [rows, setRows] = useState<SurveySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () => api<{ surveys: SurveySummary[] }>("/api/surveys").then((r) => {
      setRows(r.surveys);
      // Keep the list fresh while runs are waiting or answering (batch submissions finish one by one).
      if (r.surveys.some((s) => s.last_status === "queued" || s.last_status === "running")) timer = setTimeout(load, 10000);
    }).catch(() => setError("목록을 불러오지 못했습니다. 새로 고쳐 주세요."));
    load();
    return () => clearTimeout(timer);
  }, []);
  if (error) return <p className="rv-error" role="alert">{error}</p>;
  if (!rows) return <p className="rv-muted" role="status">불러오는 중…</p>;
  if (!rows.length) {
    return (
      <div className="pp-card rv-empty">
        <h2 className="pp-h3">아직 물어본 정책이 없습니다</h2>
        <p>정책 문안과 문항 하나를 넣으면, 합성 국민이 어떻게 답할지 몇 분 안에 미리 봅니다.</p>
        <Link href="/review/new/" className="krds-btn medium primary">새로 묻기</Link>
      </div>
    );
  }
  return (
    <ul className="rv-list">
      {rows.map((s) => (
        <li key={s.id} className="pp-card rv-list-item">
          <Link href={`/review/view/?id=${s.id}`} className="rv-list-title">{s.title}</Link>
          {s.last_status === "succeeded"
            ? (s.headline?.unstable
              ? <span className="pp-chip rv-headline is-unstable" title="선택지 순서에 따라 크게 흔들린 결과">문항 재검토 필요 ⚠</span>
              : <span className="pp-chip rv-status-succeeded">탐색 완료</span>)
            : <span className={`pp-chip rv-status-${s.last_status ?? "none"}`}>{s.last_status ? STATUS_LABEL[s.last_status] : "실행 전"}</span>}
          <span className="rv-muted">{s.n_runs}회 실행 · {kst(s.updated_at)}</span>
        </li>
      ))}
    </ul>
  );
}

export default function SurveyList() {
  async function logout() {
    await api("/api/logout", { method: "POST" }).catch(() => null);
    location.assign("/review/login/");
  }
  return (
    <ServiceGate>
      {(email, config) => (
        <>
          <div className="rv-head">
            <div>
              <h1 className="pp-h2">내 질문</h1>
              <p className="rv-muted">{email} · <button type="button" className="rv-link" onClick={logout}>로그아웃</button></p>
            </div>
            <div className="rv-head-actions">
              <Link href="/review/batch/" className="krds-btn medium secondary">입법예고 골라 묻기</Link>
            </div>
          </div>
          <p className="rv-pilot">공개·가상 정책 문안으로 먼저 만날 사람과 질문을 설계하는 시범 서비스입니다. 실제 사람 응답 0명(AI 추정, 실제 여론조사 아님)이며 발표 전 비공개 문안은 넣지 마세요. 기록은 {config.retention_days}일 뒤 자동으로 지워집니다.</p>
          <List />
        </>
      )}
    </ServiceGate>
  );
}
