"use client";

import Link from "next/link";
import { type ReactNode, useEffect, useState } from "react";
import { api, ApiError, NoService, type ServiceConfig } from "@/lib/reviewApi";
import ModelBadge from "./ModelBadge";

type Gate =
  | { state: "loading" }
  | { state: "noservice" }
  | { state: "error"; status: number; code: string; message: string }
  | { state: "login" }
  | { state: "ok"; email: string; config: ServiceConfig };

/** Detects the service server, requires login, then renders children with the user and config. */
export default function ServiceGate({ children }: { children: (email: string, config: ServiceConfig) => ReactNode }) {
  const [gate, setGate] = useState<Gate>({ state: "loading" });

  useEffect(() => {
    (async () => {
      try {
        const config = await api<ServiceConfig>("/api/config");
        const me = await api<{ email: string }>("/api/me");
        setGate({ state: "ok", email: me.email, config });
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) setGate({ state: "login" });
        else if (e instanceof ApiError) setGate({ state: "error", status: e.status, code: e.code, message: e.message });
        else setGate({ state: "noservice" });
      }
    })();
  }, []);

  useEffect(() => {
    if (gate.state === "login") {
      const next = encodeURIComponent(location.pathname + location.search);
      location.replace(`/review/login/?next=${next}`);
    }
  }, [gate.state]);

  if (gate.state === "loading" || gate.state === "login") return <p className="rv-muted" role="status">불러오는 중…</p>;
  if (gate.state === "error") {
    const title = gate.code === "panel_missing" || gate.code === "config_error" || gate.status === 503
      ? "서버 초기 준비가 끝나지 않았습니다"
      : "서버 요청 처리 중 오류가 발생했습니다";
    return (
      <div className="pp-card rv-empty" role="alert">
        <h2 className="pp-h3">{title}</h2>
        <p>{gate.message}</p>
        <p className="rv-muted">오류 코드: {gate.code} (HTTP {gate.status}) · 조치 후 서버를 다시 시작하고 새로 고쳐 주세요.</p>
      </div>
    );
  }
  if (gate.state === "noservice") {
    return (
      <div className="pp-card rv-empty">
        <h2 className="pp-h3">이 주소에서는 서비스가 연결되어 있지 않습니다</h2>
        <p>‘미리 묻기’는 운영 서버에서만 동작합니다. 이 주소에서는 미리 만들어 둔 사례만 볼 수 있습니다.</p>
        <p><Link href="/series/housing/">부동산 대책 흐름(합성 인물 1만 명) 사례 보기 →</Link></p>
      </div>
    );
  }
  return (
    <>
      {gate.config.setup_warnings?.map((w) => (
        <p key={w} className="rv-caution" role="note"><b>설정 안내</b> {w}</p>
      ))}
      {gate.config.demo_login && <p className="rv-demo" role="note"><b>시연 모드</b> 로그인 없이 시연 계정({gate.email})으로 들어와 있습니다. 이 주소를 연 사람은 모두 같은 계정을 씁니다.</p>}
      {gate.config.model_profile && <ModelBadge profile={gate.config.model_profile} />}
      {children(gate.email, gate.config)}
    </>
  );
}
