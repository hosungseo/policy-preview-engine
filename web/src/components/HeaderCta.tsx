"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useService } from "@/lib/useService";

/** Right side of the header: a quiet link to the questions already asked, and the one button that starts a new one.
 *  Where the asking service is not connected (static public hosting) the button leads to the worked example instead. */
export default function HeaderCta() {
  const path = usePathname() || "/";
  const service = useService();
  const mine = path === "/review" || path === "/review/" || path.startsWith("/review/view");
  if (!service) {
    return (
      <div className="pp-header-actions">
        <Link href="/#example" className="krds-btn medium primary pp-header-cta">결과 먼저 보기</Link>
      </div>
    );
  }
  return (
    <div className="pp-header-actions">
      <Link href="/review/" className={`pp-header-mine${mine ? " is-active" : ""}`} aria-current={mine ? "page" : undefined}>내 질문</Link>
      <Link href="/review/new/" className="krds-btn medium primary pp-header-cta">미리 묻기</Link>
    </div>
  );
}
