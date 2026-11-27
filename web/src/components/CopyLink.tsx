"use client";

import { useState } from "react";

export default function CopyLink() {
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setDone(true);
      setTimeout(() => setDone(false), 2000);
    } catch {
      setDone(false);
    }
  }
  return (
    <button type="button" className="krds-btn medium secondary" onClick={copy}>
      {done ? "링크를 복사했습니다" : "링크 복사"}
    </button>
  );
}
