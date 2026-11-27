import { meanFill, meanInk } from "@/lib/colors";
import { signed } from "@/lib/format";
import type { Hearing, Persona } from "@/lib/types";
import StatTile from "./StatTile";
import "./components.css";

export const MARK_LABEL: Record<string, string> = { rebut: "반박", new_point: "새 논점", concede: "입장 완화", proposal: "구체적 제안" };

// Jev's reading of each participant's speeches: stance by round, who moved, and what the speeches did.
export default function HearingReads({ hearing, person }: { hearing: Hearing; person: Map<string, Persona> }) {
  const t = hearing.trajectories;
  if (!t || !hearing.reads) return null;
  const rounds = ["1", "2", "3"];
  return (
    <div>
      <div className="pp-grid-4">
        {Object.entries(t.counts).map(([k, n]) => (
          <StatTile key={k} label={MARK_LABEL[k] ?? k} value={`${n}번`} note={`발언 ${hearing.reads!.length}개 중`} />
        ))}
      </div>
      <div className="pp-card" style={{ marginTop: 12, overflowX: "auto" }}>
        <table className="pp-traj-table">
          <thead>
            <tr><th>참석자</th>{rounds.map((r) => <th key={r}>{r}라운드</th>)}<th>변화</th></tr>
          </thead>
          <tbody>
            {t.participants.map((row, idx) => {
              const p = person.get(row.uuid);
              const seat = hearing.participants.indexOf(row.uuid);
              const label = `합성 참석자 ${seat >= 0 ? seat + 1 : idx + 1}`;
              const moved = t.movers.includes(row.uuid);
              return (
                <tr key={row.uuid}>
                  <th scope="row">{label}<small>{p ? `${p.age}세 · ${p.occupation}` : ""}</small></th>
                  {rounds.map((r) => {
                    const v = row.stances[r];
                    return <td key={r}>{v === undefined ? "–" : <span className="pp-traj-cell" style={{ background: meanFill(v), color: meanInk(v) }}>{signed(v)}</span>}</td>;
                  })}
                  <td className="pp-traj-change">{signed(row.change)}{moved && <span className="pp-chip is-primary">움직임</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="pp-sub" style={{ margin: "10px 0 0" }}>
          칸은 Jev가 그 라운드 발언에서 읽은 태도입니다(−2 반대 ~ +2 찬성). 1라운드와 3라운드의 차이가 {t.move} 이상이면 ‘움직임’으로 표시합니다.
          AI가 쓴 회의록은 서로 맞장구치며 합의 쪽으로 기울기 쉬워, 움직임은 실제 설득이 아니라 이 경향일 수 있습니다.
        </p>
      </div>
    </div>
  );
}
