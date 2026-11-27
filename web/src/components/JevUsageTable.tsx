import type { Meta } from "@/lib/types";
import "./components.css";

const TASK_LABEL: Record<string, string> = {
  occupations: "직업 대분류 매핑", assign: "쟁점 소속 판정", consistency: "LLM 응답 자기모순 점검",
  panel: "1인 1회 판정(찬반·영향·조항·쟁점·참여 방식)", alternatives: "수정안 비교(원안·수정안·대조)",
  questions: "예상 질문 우선순위", clarity: "정책문 명료성 점검", order: "쟁점 소속 두 순서 판정",
  lenses: "반응 관점 태그", batching: "묶음 질문 점검", repeat: "반복 호출 점검", debrief: "공청회 발언 읽기",
};
const STAGE_LABEL: Record<string, string> = {
  panel: "패널 구성", clarity: "정책문 점검", issues: "쟁점", jev: "정량 점검", alternatives: "수정안 비교",
  review: "판정 점검", debrief: "공청회 읽기", plan: "계획서",
};

// Speed and price of every Jev judgment in this run, from the API's own token counts.
export default function JevUsageTable({ meta }: { meta: Meta }) {
  const usage = meta.jev_usage ?? {};
  const rows = Object.entries(usage).flatMap(([stage, tasks]) =>
    Object.entries(tasks).map(([task, u], i) => ({ stage, task, first: i === 0, ...u })));
  const stageCalls = Object.fromEntries(Object.entries(usage).map(([stage, tasks]) =>
    [stage, Object.values(tasks).reduce((a, u) => a + u.calls, 0)]));
  if (!rows.length) return null;
  const seconds = Object.fromEntries(meta.stages.map((s) => [s.name, s.seconds]));
  const total = rows.reduce((a, r) => ({ calls: a.calls + r.calls, tokens: a.tokens + r.input_tokens, cost: a.cost + r.cost_usd }),
    { calls: 0, tokens: 0, cost: 0 });
  return (
    <div className="pp-card" style={{ overflowX: "auto" }}>
      <table className="pp-usage-table">
        <thead>
          <tr><th>단계</th><th>판정</th><th>호출</th><th>1회 응답(대기 포함)</th><th>입력 토큰</th><th>비용(USD)</th><th>단계 소요·처리 속도</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.stage + r.task}>
              <td>{STAGE_LABEL[r.stage] ?? r.stage}</td>
              <td>{TASK_LABEL[r.task] ?? r.task}</td>
              <td className="pp-num">{r.calls.toLocaleString()}회{r.cached ? <small> +캐시 {r.cached.toLocaleString()}</small> : null}</td>
              <td className="pp-num">{(r.call_seconds / Math.max(1, r.calls)).toFixed(2)}초</td>
              <td className="pp-num">{r.input_tokens.toLocaleString()}</td>
              <td className="pp-num">${r.cost_usd.toFixed(3)}</td>
              <td className="pp-num">{r.first && seconds[r.stage] !== undefined
                ? `${Math.round(seconds[r.stage])}초 · 초당 ${(stageCalls[r.stage] / Math.max(1, seconds[r.stage])).toFixed(1)}건` : ""}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr><th colSpan={2}>합계</th><td className="pp-num">{total.calls.toLocaleString()}회</td><td />
            <td className="pp-num">{total.tokens.toLocaleString()}</td><td className="pp-num">${total.cost.toFixed(2)}</td><td /></tr>
        </tfoot>
      </table>
      <ul className="pp-usage-list">
        {rows.map((r) => (
          <li key={r.stage + r.task}>
            <b>{STAGE_LABEL[r.stage] ?? r.stage} · {TASK_LABEL[r.task] ?? r.task}</b>
            <span>{r.calls.toLocaleString()}회{r.cached ? ` (+캐시 ${r.cached.toLocaleString()})` : ""} · 1회 {(r.call_seconds / Math.max(1, r.calls)).toFixed(2)}초 · 입력 {r.input_tokens.toLocaleString()}토큰 · ${r.cost_usd.toFixed(3)}
              {r.first && seconds[r.stage] !== undefined && <> · 단계 {Math.round(seconds[r.stage])}초(초당 {(stageCalls[r.stage] / Math.max(1, seconds[r.stage])).toFixed(1)}건)</>}</span>
          </li>
        ))}
        <li><b>합계</b><span>{total.calls.toLocaleString()}회 · 입력 {total.tokens.toLocaleString()}토큰 · ${total.cost.toFixed(2)}</span></li>
      </ul>
      <p className="pp-sub" style={{ margin: "10px 0 0" }}>
        비용은 API가 돌려준 입력 토큰 수에 100만 토큰당 $0.042를 곱한 값입니다(출력은 무료). 캐시는 같은 질문을 다시 사지 않고 저장해 둔 답을 쓴 횟수이며 비용이 들지 않습니다. 1회 응답은 여러 호출을 동시에 보낼 때 서버에서 기다린
        시간까지 포함합니다. 처리 속도는 단계의 Jev 호출 수를 단계 전체 시간으로 나눈 값이며, 쟁점·수정안 단계에는 LLM 호출 시간도 섞여 있습니다.
      </p>
    </div>
  );
}
