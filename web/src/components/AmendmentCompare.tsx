import { DELTA_BINS, binOf } from "@/lib/colors";
import { pct, signed } from "@/lib/format";
import type { AltCell, Alternatives } from "@/lib/types";
import "./components.css";

const SCALE = 0.5; // bars share one fixed scale (±0.5 on the -2..+2 stance) so amendments compare directly

function pp(v: number): string {
  const x = Math.abs(v) < 0.0005 ? 0 : v;
  return `${x > 0 ? "+" : ""}${(x * 100).toFixed(1)}%p`;
}

// Net of the placebo when there is one: what the amendment's content does, beyond appending a sentence.
function effect(c: Pick<AltCell, "d_mean" | "d_reserve" | "d_favor" | "net_mean" | "net_reserve" | "net_favor">) {
  return { mean: c.net_mean ?? c.d_mean, reserve: c.net_reserve ?? c.d_reserve, favor: c.net_favor ?? c.d_favor };
}

function DeltaRows({ cells }: { cells: AltCell[] }) {
  return (
    <div className="pp-delta-rows">
      {cells.map((c) => {
        const v = effect(c).mean;
        const width = Math.min(1, Math.abs(v) / SCALE) * 50;
        const bin = binOf(DELTA_BINS, v);
        return (
          <div key={c.group} className={`pp-delta-row${c.small ? " is-small" : ""}`}>
            <span>{c.group}</span>
            <span className="pp-delta-track" role="img" aria-label={`${c.group} 평균 지지 변화 ${signed(v)}, ${c.n}명`}>
              <span style={{ left: v < 0 ? `${50 - width}%` : "50%", width: `${width}%`, background: c.small ? "#cdd1d5" : bin.color }} />
            </span>
            <b>{signed(v)}</b>
            <span className="pp-delta-n">{c.n}명</span>
          </div>
        );
      })}
    </div>
  );
}

export default function AmendmentCompare({ alternatives, segmentLabel, compact = false }: {
  alternatives: Alternatives; segmentLabel: (id: string) => string | undefined; compact?: boolean;
}) {
  const { placebo, baseline } = alternatives;
  const items = [...alternatives.items].sort((a, b) => effect(a).reserve - effect(b).reserve);
  return (
    <div className="pp-amend">
      <p className="pp-sub" style={{ margin: 0 }}>
        정량 패널에서 무작위로 고른 같은 {alternatives.n.toLocaleString()}명에게 원안과 수정안을 각각 물었습니다(원안 찬성 쪽 확률 {pct(baseline.favor)},
        반대·유보 {pct(baseline.reserve)}).
        {placebo && <> 내용을 바꾸지 않는 대조 문장만 덧붙여도 평균 지지가 {signed(placebo.d_mean)}, 반대·유보가 {pp(placebo.d_reserve)} 움직였습니다.
          아래 변화는 이 대조 변화를 뺀 순효과입니다.</>}
      </p>
      <div className={compact ? "pp-grid-3" : "pp-amend-list"}>
        {items.map((it) => {
          const e = effect(it);
          const seg = it.segment_id ? segmentLabel(it.segment_id) : undefined;
          return (
            <article key={it.id} className="pp-card pp-amend-card">
              <div className="pp-amend-head">
                <h3 className="pp-h3">{it.title}</h3>
                {seg && <span className="pp-chip">{seg}</span>}
              </div>
              <p className="pp-amend-text">{it.text}<span className="pp-tag-ai">AI 작성</span></p>
              <div className="pp-amend-metrics">
                <div><span>반대·유보</span><b>{pp(e.reserve)}</b></div>
                <div><span>찬성 쪽</span><b>{pp(e.favor)}</b></div>
                <div><span>평균 지지</span><b>{signed(e.mean)}</b></div>
              </div>
              <p className="pp-amend-source">
                출처 보완 제안 ‘{it.source_title}’(대표 {it.source_n}명{it.source_n_aff !== undefined && ` · 영향권 ${it.source_n_aff}명: 전체 비율로 읽지 않음`}) — “{it.source_example}”
              </p>
              {!compact && (
                <>
                  <p className="pp-amend-label">연령대별 평균 지지 변화<span className="pp-tag-ai">AI 추정</span></p>
                  <DeltaRows cells={it.groups.age_band ?? []} />
                  {it.movers.length > 0 && (
                    <p className="pp-sub" style={{ margin: "8px 0 0" }}>
                      가장 크게 움직인 집단: {it.movers.map((m) => `${m.group}(${m.kind}) ${signed(effect(m).mean)}`).join(", ")}
                    </p>
                  )}
                </>
              )}
            </article>
          );
        })}
      </div>
      {!compact && (
        <ul className="pp-legend">
          {DELTA_BINS.map((b) => <li key={b.label}><span className="pp-swatch" style={{ background: b.color }} />{b.label}</li>)}
          <li><span className="pp-swatch" style={{ background: "#cdd1d5" }} />30명 미만(해석 안 함)</li>
        </ul>
      )}
    </div>
  );
}
