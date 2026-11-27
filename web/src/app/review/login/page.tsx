import type { Metadata } from "next";
import LoginForm from "@/components/review/LoginForm";
import "../review.css";

export const metadata: Metadata = { title: "로그인" };

export default function LoginPage() {
  return (
    <div className="pp-container pp-page rv-narrow">
      <h1 className="pp-h2">백번 미리 묻다 로그인</h1>
      <p className="pp-lead">시범 서비스는 운영자가 발급한 접속 코드로 로그인합니다.</p>
      <LoginForm />
    </div>
  );
}
