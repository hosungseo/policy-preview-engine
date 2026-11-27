import type { ReactNode } from "react";
import "./components.css";

export default function SectionHead({ title, desc, tag, right, id }: {
  title: string; desc?: ReactNode; tag?: "ai" | "code"; right?: ReactNode; id?: string;
}) {
  return (
    <div className="pp-sec-head" id={id}>
      <div>
        <h2 className="pp-h2">
          {title}
          {tag === "ai" && <span className="pp-tag-ai">AI 작성</span>}
          {tag === "code" && <span className="pp-tag-code">코드 자동 요약</span>}
        </h2>
        {desc && <p>{desc}</p>}
      </div>
      {right}
    </div>
  );
}
