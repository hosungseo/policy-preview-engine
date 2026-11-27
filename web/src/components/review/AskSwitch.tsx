import Link from "next/link";

/** The two ways to start asking, shown on both start pages. */
export default function AskSwitch({ current }: { current: "write" | "notice" }) {
  return (
    <nav className="rv-switch" aria-label="묻는 방법">
      <Link href="/review/new/" className={current === "write" ? "is-active" : undefined} aria-current={current === "write" ? "page" : undefined}>
        <b>직접 쓰기</b><span>정책 문안과 문항 하나</span>
      </Link>
      <Link href="/review/batch/" className={current === "notice" ? "is-active" : undefined} aria-current={current === "notice" ? "page" : undefined}>
        <b>입법예고에서 고르기</b><span>의견 접수 중인 예고 여러 건</span>
      </Link>
    </nav>
  );
}
