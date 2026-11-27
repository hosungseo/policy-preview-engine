import { MUTED, NEGATIVE, POSITIVE } from "@/lib/colors";
import { signed } from "@/lib/format";
import type { GroupRow } from "@/lib/types";
import "./components.css";

export default function MeanRows({ title, rows, smallNote = "회색은 10명 미만이라 해석하지 않습니다." }: {
  title: string; rows: GroupRow[]; smallNote?: string;
}) {
  return (
    <div className="pp-card">
      <h3 className="pp-h3">{title}</h3>
      <div className="pp-means">
        <div className="pp-mean-axis" aria-hidden="true">
          <span />
          <span className="pp-mean-ticks"><i>−2<span className="pp-tick-word"> 반대</span></i><i>0</i><i><span className="pp-tick-word">찬성 </span>+2</i></span>
          <span />
          <span style={{ textAlign: "right" }}>명</span>
        </div>
        {rows.map((r) => {
          const width = (Math.min(2, Math.abs(r.mean)) / 4) * 100;
          const left = r.mean < 0 ? 50 - width : 50;
          const color = r.small ? MUTED : r.mean < 0 ? NEGATIVE : POSITIVE;
          return (
            <div key={r.group} className={`pp-mean-row${r.small ? " is-small" : ""}`}>
              <span className="pp-mean-label">{r.group}</span>
              <span className="pp-mean-track" role="img" aria-label={`${r.group} 평균 ${signed(r.mean)}, ${r.n}명`}>
                <span className={`pp-mean-bar ${r.mean < 0 ? "is-neg" : "is-pos"}`}
                  style={{ left: `${left}%`, width: `${width}%`, background: color }} />
              </span>
              <span className="pp-mean-val">{signed(r.mean)}</span>
              <span className="pp-mean-n">{r.n}</span>
            </div>
          );
        })}
      </div>
      {rows.some((r) => r.small) && (
        <p className="pp-sub" style={{ margin: "10px 0 0" }}>{smallNote}</p>
      )}
    </div>
  );
}
