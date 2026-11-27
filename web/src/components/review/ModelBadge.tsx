"use client";

import { inputGuide, shortGuide } from "@/lib/modelGuide";
import type { ModelProfile } from "@/lib/reviewApi";

const WHERE: Record<string, string> = { global: "해외 API", korean: "국내 API", local: "기관 내부", mock: "외부 전송 없음" };

/** Which models this server runs with. The setup is chosen by the operator when the server starts (scripts/serve-profile.sh). */
export default function ModelBadge({ profile }: { profile: ModelProfile }) {
  return (
    <details className={`rv-model rv-model-${profile.kind}`}>
      <summary>
        <span className="rv-model-kind">{profile.label}</span>
        <span className="rv-model-names">{shortGuide(profile)} <span className="rv-muted">· 자세히</span></span>
      </summary>
      <div className="rv-model-body">
        <p>{inputGuide(profile)}</p>
        <table>
          <tbody>
            <tr><th>문장(이유·쟁점·공청회)</th><td>{profile.sentence.name}</td><td>{WHERE[profile.sentence.where] ?? profile.sentence.where}</td></tr>
            <tr><th>판단(집단 탐색)</th><td>{profile.decision.name}</td><td>{WHERE[profile.decision.where] ?? profile.decision.where}</td></tr>
          </tbody>
        </table>
        <p className="rv-muted">공개·가상 문안만 입력하는 것이 기본 원칙입니다. 발표 전 비공개 문안과 개인정보는 입력하지 마세요.</p>
        <ul>
          {profile.choices.map((c) => (
            <li key={c.kind} className={c.kind === profile.kind ? "is-current" : undefined}>
              <b>{c.label}</b> — {c.use}{c.kind === profile.kind && " (지금)"}
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}
