import Link from "next/link";
import HeaderCta from "./HeaderCta";
import Masthead from "./Masthead";
import NavLinks from "./NavLinks";

function LogoMark() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" aria-hidden="true">
      <rect x="2" y="4" width="28" height="20" rx="6" fill="#256ef4" />
      <path d="M9 23 L9 30 L16 23 Z" fill="#256ef4" />
      <circle cx="10" cy="14" r="2.2" fill="#fff" />
      <circle cx="16" cy="14" r="2.2" fill="#fff" />
      <circle cx="22" cy="14" r="2.2" fill="#fff" />
    </svg>
  );
}

export default function SiteHeader() {
  return (
    <>
      <Masthead />
      <header className="pp-header">
        <div className="pp-container pp-header-in">
          <Link href="/" className="pp-logo" aria-label="백번 미리 묻다 홈">
            <LogoMark />
            <span className="pp-logo-text">백번 미리 묻다</span>
          </Link>
          <NavLinks />
          <HeaderCta />
        </div>
      </header>
    </>
  );
}
