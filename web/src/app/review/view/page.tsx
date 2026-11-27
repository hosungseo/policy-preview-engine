import type { Metadata } from "next";
import SurveyView from "@/components/review/SurveyView";
import "../review.css";

export const metadata: Metadata = { title: "결과" };

export default function SurveyViewPage() {
  return (
    <div className="pp-container pp-page rv-narrow">
      <SurveyView />
    </div>
  );
}
