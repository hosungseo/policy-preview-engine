import type { Metadata } from "next";
import AskSwitch from "@/components/review/AskSwitch";
import NewSurvey from "@/components/review/NewSurvey";
import "../review.css";

export const metadata: Metadata = { title: "미리 묻기" };

export default function NewSurveyPage() {
  return (
    <div className="pp-container pp-page rv-narrow">
      <h1 className="pp-h2">미리 묻기</h1>
      <AskSwitch current="write" />
      <p className="pp-lead">발표하기 전에 정책 문안과 문항 하나를 합성 국민에게 먼저 물어봅니다. 입법예고를 가져오거나 직접 쓰세요.</p>
      <NewSurvey />
    </div>
  );
}
