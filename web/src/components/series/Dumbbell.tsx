import { pct } from "@/lib/format";

// Share of owners by province in the panel (people; Jev's estimate or the assignment) against the official survey
// (households). `label` names the panel value: "추정" or "배정".
export default function Dumbbell({ rows, label = "추정" }: { rows: { province: string; own: number; official_own: number | null }[]; label?: string }) {
  return (
    <div>
      {rows.map((r) => (
        <div key={r.province} className="pp-dumbbell-row">
          <div>{r.province}</div>
          <div className="pp-dumbbell-track" role="img" aria-label={`${r.province}: ${label} ${pct(r.own)}, 공식 ${r.official_own === null ? "없음" : pct(r.official_own)}`}>
            {r.official_own !== null && (
              <>
                <span className="pp-dumbbell-bar" style={{ left: `${Math.min(r.own, r.official_own) * 100}%`, width: `${Math.abs(r.own - r.official_own) * 100}%` }} />
                <span className="pp-dumbbell-dot is-official" style={{ left: `${r.official_own * 100}%` }} />
              </>
            )}
            <span className="pp-dumbbell-dot is-jev" style={{ left: `${r.own * 100}%` }} />
          </div>
          <div className="pp-dumbbell-nums">{label} <b>{pct(r.own)}</b> · 공식 <b>{r.official_own === null ? "–" : pct(r.official_own)}</b></div>
        </div>
      ))}
    </div>
  );
}
