import { pct } from "@/lib/format";
import "./components.css";

export default function ShareBar({ share, label }: { share: number | null; label: string }) {
  return (
    <div className="pp-share">
      <div className="pp-share-track" aria-hidden="true">
        <div className="pp-share-fill" style={{ width: share === null ? "0%" : `${Math.max(1, share * 100)}%` }} />
      </div>
      <span className="pp-share-val">{label} · {pct(share)}</span>
    </div>
  );
}
