import { POSITION_BINS, SEQ_BINS, binOf, seqBin } from "@/lib/colors";
import { pct, signed } from "@/lib/format";
import type { JevClauseRow } from "@/lib/types";
import "./components.css";

// Rows = items (policy provisions, issues or ways of taking part), columns = groups.
// "seq": each cell is a mean probability (0..1) on a single-hue ramp, printed as a percentage.
// "position": each cell is an expected stance on -1 (oppose) .. +1 (support), diverging colours, printed signed.
export default function ClauseHeatmap({ title, segments, overall, groups, mode = "seq", rowHeader = "조항", note }: {
  title: string; segments: { id: string; label: string }[]; overall: Record<string, number>; groups: JevClauseRow[];
  mode?: "seq" | "position"; rowHeader?: string; note?: string;
}) {
  const shown = groups.filter((g) => !g.small);
  const hidden = groups.filter((g) => g.small);
  const cell = (v: number) => {
    if (mode === "position") {
      const bin = binOf(POSITION_BINS, v);
      return { background: bin.color, color: bin.ink, text: signed(v) };
    }
    const bin = seqBin(v);
    return { background: bin.color, color: bin.ink, text: pct(v) };
  };
  return (
    <div className="pp-card pp-heat">
      <h3 className="pp-h3">{title}</h3>
      <div className="pp-heat-wrap">
        <table className="pp-heat-table">
          <thead>
            <tr>
              <th scope="col">{rowHeader}</th>
              <th scope="col">전체</th>
              {shown.map((g) => <th key={g.group} scope="col">{g.group}<small>{g.n.toLocaleString()}명</small></th>)}
            </tr>
          </thead>
          <tbody>
            {segments.map((s) => (
              <tr key={s.id}>
                <th scope="row">{s.label}</th>
                {[overall[s.id] ?? 0, ...shown.map((g) => g.values[s.id] ?? 0)].map((v, i) => {
                  const c = cell(v);
                  return <td key={i} style={{ background: c.background, color: c.color }}>{c.text}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="pp-legend">
        {(mode === "position" ? POSITION_BINS : SEQ_BINS).map((b) => (
          <li key={b.label}><span className="pp-swatch" style={{ background: b.color }} />{b.label}</li>
        ))}
      </ul>
      {note && <p className="pp-sub" style={{ margin: "4px 0 0" }}>{note}</p>}
      {hidden.length > 0 && (
        <p className="pp-sub" style={{ margin: "4px 0 0" }}>
          30명 미만이라 뺀 집단: {hidden.map((g) => `${g.group}(${g.n}명)`).join(", ")}
        </p>
      )}
    </div>
  );
}
