import { gapBin } from "@/lib/colors";
import { ppoint } from "@/lib/format";
import type { SeriesMeasure } from "@/lib/seriesTypes";

// Province x measure. "favor": the province's share leaning in favour, coloured by its gap from that measure's
// national value. "effect": the paired context effect, coloured by its size. Groups too small to read are dashed.
export default function SeriesHeatmap({ measures, mode }: { measures: SeriesMeasure[]; mode: "favor" | "effect" }) {
  const provinces = measures[0].conditions.alone.groups.province.map((g) => g.group);
  const cell = (m: SeriesMeasure, prov: string) => {
    if (mode === "favor") {
      const g = m.conditions.alone.groups.province.find((x) => x.group === prov);
      if (!g) return null;
      const gap = g.favor - m.conditions.alone.favor;
      return { text: String(Math.round(g.favor * 100)), gap, small: g.small,
        title: `${prov} · ${m.short} ${m.title}: 찬성 쪽 ${Math.round(g.favor * 100)}% (전국 대비 ${ppoint(gap)}%p, ${g.n}명)` };
    }
    const g = m.effect.groups.province.find((x) => x.group === prov);
    if (!g) return null;
    return { text: ppoint(g.diff), gap: g.diff, small: g.small, title: `${prov} · ${m.short}: 누적 효과 ${ppoint(g.diff)}%p (${g.n}명)` };
  };
  return (
    <div className="pp-series-heat-wrap">
      <table className={`pp-series-heat is-${mode}`}>
        <thead>
          <tr><th className="pp-rowh" />{measures.map((m) => <th key={m.id} scope="col">{m.short}</th>)}</tr>
        </thead>
        <tbody>
          {provinces.map((prov) => (
            <tr key={prov}>
              <th scope="row" className="pp-rowh">{prov}</th>
              {measures.map((m) => {
                const c = cell(m, prov);
                if (!c) return <td key={m.id} />;
                const b = gapBin(c.gap);
                return c.small
                  ? <td key={m.id} className="is-small" title={c.title}>{c.text}</td>
                  : <td key={m.id} style={{ background: b.color, color: b.ink }} title={c.title}>{c.text}</td>;
              })}
            </tr>
          ))}
          <tr className="pp-heat-total">
            <th scope="row" className="pp-rowh">전국</th>
            {measures.map((m) => (
              <td key={m.id}>{mode === "favor" ? Math.round(m.conditions.alone.favor * 100) : ppoint(m.effect.overall.diff)}</td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
