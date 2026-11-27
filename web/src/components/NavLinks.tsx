"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Three menus, no topic names: what was asked (cases), who is asked (the roster), and how far to trust it.
// The logo goes home; asking is the one button on the right (HeaderCta).
const LINKS = [
  { href: "/explore/", label: "사례", match: (p: string) => /^\/(explore|runs)(\/|$)/.test(p) || (p.startsWith("/series/") && !p.startsWith("/series/housing/map")) },
  { href: "/series/housing/map/", label: "100만 명", match: (p: string) => p.startsWith("/series/housing/map") },
  { href: "/method/", label: "한계와 방법", match: (p: string) => p.startsWith("/method") },
];

export default function NavLinks() {
  const path = usePathname() || "/";
  return (
    <nav className="pp-nav" aria-label="주 메뉴">
      {LINKS.map((link) => {
        const active = link.match(path);
        return (
          <Link key={link.href} href={link.href} className={active ? "is-active" : undefined} aria-current={active ? "page" : undefined}>
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
