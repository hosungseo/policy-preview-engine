import { meanFill, meanInk } from "@/lib/colors";
import { pct, signed } from "@/lib/format";
import type { LensItem } from "@/lib/types";
import "./components.css";

// How many reactions carry each lens (Jev tag, probability >= threshold) and those reactions' mean support.
export default function LensBars({ items, total }: { items: LensItem[]; total: number }) {
  const max = Math.max(...items.map((i) => i.share), 0.01);
  return (
    <div className="pp-card">
      <div className="pp-lens-rows">
        {items.map((it) => (
          <div key={it.key} className="pp-lens-row">
            <span>{it.label}</span>
            <span className="pp-metric-track" aria-hidden="true"><span className="pp-metric-fill" style={{ width: `${(it.share / max) * 100}%`, display: "block" }} /></span>
            <b className="pp-num">{it.n}건</b>
            <span className="pp-lens-mean" style={{ background: meanFill(it.mean_support), color: meanInk(it.mean_support) }}>
              {it.mean_support === null ? "–" : signed(it.mean_support)}
            </span>
          </div>
        ))}
      </div>
      <p className="pp-sub" style={{ margin: "10px 0 0" }}>
        반응 {total}건에 관점 12가지를 따로따로 판정했습니다(한 반응에 여러 관점이 붙을 수 있음). 막대는 {pct(items[0]?.share ?? 0)}를 최대로 한 상대 길이이고,
        오른쪽 칸은 그 관점이 붙은 반응들의 평균 지지입니다.
      </p>
    </div>
  );
}
