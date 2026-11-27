import { SUPPORT_COLOR } from "@/lib/colors";
import { SUPPORT_LABEL } from "@/lib/format";
import "./components.css";

export default function SupportBadge({ value }: { value: number }) {
  const key = String(value);
  return (
    <span className="pp-support" style={{ border: `1px solid ${SUPPORT_COLOR[key]}` }}>
      <span className="pp-support-dot" style={{ background: SUPPORT_COLOR[key] }} aria-hidden="true" />
      {SUPPORT_LABEL[key]}
    </span>
  );
}
