import { pct } from "@/lib/format";
import "./components.css";

export default function MetricBar({ label, value, estimated, wide }: {
  label: string; value: number; estimated?: boolean; wide?: boolean;
}) {
  return (
    <div className={`pp-metric${wide ? " is-wide" : ""}`}>
      <span>{label}{estimated && <span className="pp-tag-ai">AI 추정</span>}</span>
      <div className="pp-metric-track" aria-hidden="true">
        <div className="pp-metric-fill" style={{ width: `${value * 100}%` }} />
      </div>
      <span className="pp-metric-val">{pct(value)}</span>
    </div>
  );
}
