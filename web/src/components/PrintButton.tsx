"use client";

export default function PrintButton() {
  return (
    <button type="button" className="krds-btn medium secondary" onClick={() => window.print()}>
      인쇄하기
    </button>
  );
}
