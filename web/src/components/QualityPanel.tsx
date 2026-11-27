import { pct } from "@/lib/format";
import type { Quality } from "@/lib/types";
import StatTile from "./StatTile";
import "./components.css";

const fmt = (v: number | null | undefined, digits = 2) => (v === null || v === undefined ? "–" : v.toFixed(digits));

// How far Jev's own judgments can be trusted here: option order, batching, repetition, a second instrument.
export default function QualityPanel({ quality }: { quality: Quality }) {
  const { order, batching, repeat, occupations } = quality;
  return (
    <div>
      <div className="pp-grid-4">
        <StatTile label="선택지 순서를 뒤집어도 같은 쟁점" value={order.agreement === null ? "–" : pct(order.agreement)}
          note={`${order.reactions}건 중 ${order.same_choice}건 · 확률 이동 평균 ${fmt(order.mean_shift)}`} />
        <StatTile label="따로 물어도 같은 찬반" value={`±${fmt(batching.mean_abs_diff)}`}
          note={`${batching.n}명 · 질문 40개 묶음 대비 평균 차이(5단계)`} />
        <StatTile label="같은 호출을 다시 보내면" value={`±${fmt(repeat.stance_mean_abs_diff)}`}
          note={`${repeat.n}명 · 찬반 평균 차이, 소식 경로 ${repeat.channel_same === null ? "–" : pct(repeat.channel_same)} 일치`} />
        <StatTile label="직업 분류 Jev–LLM 일치" value={occupations.share === null ? "–" : pct(occupations.share)}
          note={`직업 ${occupations.n}개 중 ${occupations.agree}개`} />
      </div>
      <div className="pp-grid-2" style={{ marginTop: 12 }}>
        <div className="pp-card">
          <h3 className="pp-h3">어떻게 보정했나</h3>
          <ul className="pp-bullets">
            <li>쟁점 소속은 선택지를 원래 순서와 뒤집은 순서로 두 번 묻고 확률을 평균해 정했습니다. 순서만 바꿔도 같은 답의 확률이
              크게 움직였고, 이 보정으로 {pct(order.threshold)} 기준 판정이 바뀐 반응이 {order.flips}건 나왔습니다.</li>
            <li>한 사람에게 질문 40개 안팎을 한 번에 물어도, 찬반만 따로 물은 답과 평균 {fmt(batching.mean_abs_diff)}(최대 {fmt(batching.max_abs_diff)}) 차이였습니다.</li>
            <li>같은 호출을 캐시를 거치지 않고 다시 보내면 찬반이 평균 {fmt(repeat.stance_mean_abs_diff)}(최대 {fmt(repeat.stance_max_abs_diff)}) 움직였습니다. 완전히 같지는 않으므로 한 사람의 값보다 집단 평균으로 읽습니다.</li>
          </ul>
        </div>
        <div className="pp-card">
          <h3 className="pp-h3">직업 분류가 갈린 예</h3>
          {occupations.examples.length === 0 ? <p className="pp-sub">갈린 직업이 없습니다.</p> : (
            <table className="pp-rate-table">
              <thead><tr><th>직업</th><th>Jev</th><th>LLM</th></tr></thead>
              <tbody>
                {occupations.examples.slice(0, 8).map((e) => (
                  <tr key={e.occupation}><th scope="row">{e.occupation}</th><td>{e.jev}</td><td>{e.llm}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="pp-sub" style={{ margin: "8px 0 0" }}>정답 목록이 아니라 두 도구의 비교입니다. 어느 쪽이 맞는지는 사람이 확인합니다.</p>
        </div>
      </div>
    </div>
  );
}
