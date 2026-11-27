"use client";

import { usePathname } from "next/navigation";

export default function Masthead() {
  const path = usePathname() || "/";
  const service = path.startsWith("/review");
  return (
    <div className="pp-masthead">
      <div className="pp-container pp-masthead-in">
        <span className="pp-masthead-badge">{service ? "시범" : "시제품"}</span>
        <span>
          {service
            ? "이 누리집은 공식 전자정부 누리집이 아닙니다. 「백번 미리 묻다」는 합성 국민의 반응을 AI로 추정하는 시범 서비스이며 실제 여론조사가 아닙니다."
            : "이 누리집은 공식 전자정부 누리집이 아닙니다. 합성 인물 데이터로 만든 「백번 미리 묻다」 시제품(POC)입니다."}
        </span>
      </div>
    </div>
  );
}
