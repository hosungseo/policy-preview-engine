"use client";

import { type FormEvent, useState } from "react";
import { api, ApiError, NoService } from "@/lib/reviewApi";

export default function LoginForm() {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!email.trim() || !code.trim()) {
      setError("이메일과 접속 코드를 모두 입력해 주세요.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api("/api/login", { method: "POST", body: { email, code } });
      const next = new URLSearchParams(location.search).get("next");
      location.assign(next && next.startsWith("/review/") ? next : "/review/");
    } catch (e) {
      if (e instanceof NoService) setError("이 주소에서는 서비스가 연결되어 있지 않습니다.");
      else if (e instanceof ApiError) setError(e.message);
      else setError("로그인하지 못했습니다.");
      setBusy(false);
    }
  }

  return (
    <form className="pp-card rv-form" onSubmit={submit} noValidate>
      <div className="form-group">
        <div className="form-tit"><label htmlFor="rv-email">이메일</label></div>
        <div className="form-conts">
          <input id="rv-email" className="krds-input" type="email" autoComplete="username" value={email}
            onChange={(e) => setEmail(e.target.value)} />
        </div>
      </div>
      <div className="form-group">
        <div className="form-tit"><label htmlFor="rv-code">접속 코드</label></div>
        <div className="form-conts">
          <input id="rv-code" className="krds-input" type="password" autoComplete="current-password" value={code}
            onChange={(e) => setCode(e.target.value)} />
        </div>
        <p className="form-hint">접속 코드가 없거나 잊었다면 운영자에게 새 코드를 요청하세요.</p>
      </div>
      {error && <p className="rv-error" role="alert">{error}</p>}
      <div className="pp-actions">
        <button type="submit" className="krds-btn large primary" disabled={busy}>{busy ? "확인 중…" : "로그인"}</button>
      </div>
    </form>
  );
}
