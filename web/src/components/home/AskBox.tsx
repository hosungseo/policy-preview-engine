"use client";

import { type FormEvent, useState } from "react";

/** Key the new-question form reads to start with the question typed on the landing page. */
export const ASK_KEY = "pp:ask";

export default function AskBox({ examples }: { examples: { label: string; question: string }[] }) {
  const [q, setQ] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    try { if (q.trim()) sessionStorage.setItem(ASK_KEY, q.trim()); } catch { /* storage may be blocked */ }
    location.assign("/review/new/");
  }
  return (
    <form className="pp-ask" onSubmit={submit} role="search">
      <div className="pp-ask-box">
        <span className="pp-ask-prefix">묻는 대상 <strong>합성 국민 100만 명</strong></span>
        <input type="text" value={q} onChange={(e) => setQ(e.target.value)} aria-label="국민에게 물을 질문"
          placeholder="어떤 정책을 미리 물어볼까요?" maxLength={200} />
        <button type="submit" className="krds-btn medium primary">미리 묻기</button>
      </div>
      <p className="pp-ask-examples">
        <span>예시</span>
        {examples.map((e) => (
          <button key={e.label} type="button" onClick={() => setQ(e.question)}>{e.label}</button>
        ))}
        <a href="/explore/">사례 먼저 보기</a>
      </p>
    </form>
  );
}
