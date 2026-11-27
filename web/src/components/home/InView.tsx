"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";

/** Adds `is-in` once the block scrolls into view; entrance styles apply only after the script has armed it. */
export default function InView({ children, className = "" }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"" | "is-armed" | "is-armed is-in">("");
  useEffect(() => {
    const el = ref.current;
    if (!el || matchMedia("(prefers-reduced-motion: reduce)").matches || !("IntersectionObserver" in window)) return;
    setState("is-armed");
    const io = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      setState("is-armed is-in");
      io.disconnect();
    }, { threshold: 0.25 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return <div ref={ref} className={`${className} ${state}`.trim()}>{children}</div>;
}
