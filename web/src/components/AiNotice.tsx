import "./components.css";

export default function AiNotice({ extra }: { extra?: string }) {
  return (
    <div className="pp-ai-notice" role="note">
      <div className="pp-container">
        <strong>실제 사람 응답 0명 · 합성 인물(AI)의 모의 반응입니다. 실제 여론이 아닙니다.</strong>
        <span>{extra ?? "현장에서 누구에게 무엇을 물을지 정하기 위한 참고 자료이며, 찬반 비율이나 여론으로 인용할 수 없습니다."}</span>
      </div>
    </div>
  );
}
