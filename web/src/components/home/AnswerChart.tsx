import CountUp from "./CountUp";
import InView from "./InView";

type Series = { name: string; colour: string; percent: number[]; /** Option this group stands out on; it is labelled there. */ option?: string };

/** Overall answer as bars, with a few groups marked on the same scale so the gap is read directly. */
export default function AnswerChart({ options, percent, groups }: { options: string[]; percent: number[]; groups: Series[] }) {
  const top = Math.max(...percent);
  return (
    <InView className="pp-chart">
      <ul className="pp-chart-rows">
        {options.map((o, i) => (
          <li key={o} className={`${percent[i] === top ? "is-top" : ""} ${groups.some((g) => g.option === o) ? "has-note" : ""}`.trim()}>
            <span className="pp-chart-label">{o}</span>
            <span className="pp-chart-num"><CountUp value={percent[i]} /><small>%</small></span>
            <span className="pp-chart-track" role="img"
              aria-label={`전체 ${percent[i]}%, ${groups.map((g) => `${g.name} ${g.percent[i]}%`).join(", ")}`}>
              <span className="pp-chart-bar" style={{ width: `${percent[i]}%` }} />
              {groups.map((g, j) => {
                // Marks closer than 3 points would cover each other.
                const near = groups.findIndex((h, k) => k !== j && Math.abs(h.percent[i] - g.percent[i]) < 3);
                const shift = near < 0 ? "" : j < near ? " is-up" : " is-down";
                return <span key={g.name} className={`pp-chart-mark${shift}`} style={{ left: `${g.percent[i]}%`, background: g.colour }} />;
              })}
              {groups.filter((g) => g.option === o).map((g) => (
                <span key={g.name} className="pp-chart-note" aria-hidden="true" style={{ left: `${g.percent[i]}%` }}>
                  <span className="pp-key-dot" style={{ background: g.colour }} />{g.name} {g.percent[i]}%
                </span>
              ))}
            </span>
          </li>
        ))}
      </ul>
      <div className="pp-chart-axis" aria-hidden="true"><span>0</span><span>25</span><span>50</span><span>75</span><span>100%</span></div>
    </InView>
  );
}
