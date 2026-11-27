import { GAP_BINS, gapBin } from "@/lib/colors";
import { pct, ppoint } from "@/lib/format";
import type { PairStat, SeriesBundle, SeriesMeasure } from "@/lib/seriesTypes";

type Stat = "favor" | "oppose";
const NAME: Record<Stat, string> = { favor: "찬성 쪽", oppose: "반대 쪽" };
// Against is coloured the other way round, so red always means "moved away from the measure".
const LABELS: Record<Stat, string[]> = {
  favor: ["5%p 이상 내려감", "2~5%p 내려감", "±2%p 안", "2~5%p 올라감", "5%p 이상 올라감"],
  oppose: ["5%p 이상 늘어남", "2~5%p 늘어남", "±2%p 안", "2~5%p 줄어듦", "5%p 이상 줄어듦"],
};

export const change = (p: PairStat, stat: Stat) => p[stat][1] - p[stat][0];

export function ChangeLegend({ stat }: { stat: Stat }) {
  return (
    <ul className="pp-legend">
      {GAP_BINS.map((b, i) => (
        <li key={b.label}><span className="pp-swatch" style={{ background: b.color, border: "1px solid #cdd1d5" }} />{NAME[stat]} {LABELS[stat][i]}</li>
      ))}
      <li><span className="pp-swatch" style={{ background: "#fff", border: "1px dashed #cdd1d5" }} />100명 미만(해석 안 함)</li>
    </ul>
  );
}

// Groups x measures: the paired change (%p) in the share leaning in favour or against once the same people were
// shown their housing information. Rows: everyone, then each group kind with its own header row.
export default function ChangeHeatmap({ s, kinds, stat }: { s: SeriesBundle; kinds: string[]; stat: Stat }) {
  const ms = s.measures.filter((m) => m.before_after);
  const find = (m: SeriesMeasure, kind: string, g: string) => m.before_after!.groups[kind]?.find((x) => x.group === g);
  const cell = (m: SeriesMeasure, label: string, p: (PairStat & { small?: boolean }) | undefined) => {
    if (!p) return <td key={m.id} />;
    const d = change(p, stat);
    const b = gapBin(stat === "favor" ? d : -d);
    const title = `${label} · ${m.short}: ${NAME[stat]} ${pct(p[stat][0])} → ${pct(p[stat][1])} (${ppoint(d)}%p, ${p.n.toLocaleString()}명)`;
    return p.small
      ? <td key={m.id} className="is-small" title={title}>{ppoint(d)}</td>
      : <td key={m.id} style={{ background: b.color, color: b.ink }} title={title}>{ppoint(d)}</td>;
  };
  return (
    <div className="pp-series-heat-wrap">
      <table className="pp-series-heat is-effect is-change">
        <thead>
          <tr><th className="pp-rowh" />{ms.map((m) => <th key={m.id} scope="col">{m.short}</th>)}</tr>
        </thead>
        <tbody>
          <tr className="pp-heat-total">
            <th scope="row" className="pp-rowh">전체</th>
            {ms.map((m) => cell(m, "전체", m.before_after!.overall))}
          </tr>
          {kinds.map((kind) => {
            const groups = s.order[kind].filter((g) => ms.some((m) => find(m, kind, g)));
            return [
              <tr key={`${kind}-head`} className="pp-heat-kind"><th scope="rowgroup" colSpan={ms.length + 1}>{s.kind_label[kind]}</th></tr>,
              ...groups.map((g) => (
                <tr key={`${kind}-${g}`}>
                  <th scope="row" className="pp-rowh">{g}</th>
                  {ms.map((m) => cell(m, g, find(m, kind, g)))}
                </tr>
              )),
            ];
          })}
        </tbody>
      </table>
    </div>
  );
}
