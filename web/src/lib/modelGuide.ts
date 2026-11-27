// One sentence on what may be entered and where it goes, per model setup. The badge and the input form both use it,
// so the two never disagree. Every public setup is strictly for public or synthetic drafts only.
import type { ModelProfile } from "./reviewApi";

export function inputGuide(profile?: ModelProfile | null): string {
  const names = profile ? `${profile.sentence.name}·${profile.decision.name}` : "";
  switch (profile?.kind) {
    case "local":
      return "공개된 자료나 가상 정책 문안만 넣으세요. 발표 전 비공개 문안과 개인정보는 넣지 마세요(기관 내부 서버에서만 처리되며, 별도 활용은 기관 자체 보안심사가 필요합니다).";
    case "korean":
      return `공개된 자료나 가상 정책 문안만 넣으세요. 발표 전 비공개 문안과 개인정보는 넣지 마세요. 문안은 국내 리전이 확인된 API(${names})로 전송됩니다.`;
    case "mock":
      return "모의 실행입니다. 공개·가상 문안만 넣으세요. 문안을 어디에도 보내지 않으며 결과는 실제 AI 추론이 아닙니다.";
    case "global":
      return `공개된 자료나 가상 정책 문안만 넣으세요. 발표 전 비공개 문안과 개인정보는 넣지 마세요. 문안은 해외 API(${names})로 전송됩니다.`;
    default:
      return "공개된 자료나 가상 정책 문안만 넣으세요. 발표 전 비공개 문안과 개인정보는 넣지 마세요. 연결된 모델 API로 전송됩니다(일부 해외 전송 포함 가능).";
  }
}

export function shortGuide(profile?: ModelProfile | null): string {
  switch (profile?.kind) {
    case "local": return "공개·가상 문안만 · 기관 내부 처리";
    case "korean": return "공개·가상 문안만 · 국내 리전 API";
    case "global": return "공개·가상 문안만 · 해외 API";
    case "mock": return "모의 실행 · 전송 없음";
    default: return "공개·가상 문안만 · 혼합 구성";
  }
}
