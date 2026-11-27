import type { Metadata } from "next";
import SurveyList from "@/components/review/SurveyList";
import "./review.css";

export const metadata: Metadata = { title: "내 질문" };

export default function ReviewHome() {
  return (
    <div className="pp-container pp-page rv-narrow">
      <SurveyList />
    </div>
  );
}
