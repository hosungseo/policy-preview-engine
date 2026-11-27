import type { Metadata } from "next";
import type { ReactNode } from "react";
import SiteFooter from "@/components/SiteFooter";
import SiteHeader from "@/components/SiteHeader";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "백번 미리 묻다", template: "%s · 백번 미리 묻다" },
  description:
    "공개·가상 정책 문안으로 합성 인물에게 미리 묻고, 먼저 만날 사람과 만날 곳을 찾는 시제품(POC). 실제 사람 응답 0명이며 실제 여론조사가 아닙니다.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <head>
        <link rel="stylesheet" href="/krds/css/krds.min.css" />
      </head>
      <body>
        <SiteHeader />
        <main id="main">{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
