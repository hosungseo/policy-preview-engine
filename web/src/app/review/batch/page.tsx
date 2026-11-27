import type { Metadata } from "next";
import AskSwitch from "@/components/review/AskSwitch";
import BatchNotices from "@/components/review/BatchNotices";
import "../review.css";

export const metadata: Metadata = { title: "물어볼 입법예고 고르기" };

export default function BatchPage() {
  return (
    <div className="pp-container pp-page rv-narrow">
      <h1 className="pp-h2">미리 묻기</h1>
      <AskSwitch current="notice" />
      <p className="pp-lead">국민참여입법센터에서 의견 접수 중인 입법예고를 둘러보고, 국민에게 묻고 싶은 것을 담아 건마다 문항을 정하세요. 맡긴 뒤에는 차례로 진행됩니다.</p>
      <BatchNotices />
    </div>
  );
}
