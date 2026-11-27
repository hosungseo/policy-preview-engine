import type { Metadata } from "next";
import Link from "next/link";
import SectionHead from "@/components/SectionHead";
import StatTile from "@/components/StatTile";
import TileMap from "@/components/TileMap";
import { change } from "@/components/series/ChangeHeatmap";
import { pct, ppoint } from "@/lib/format";
import { getSeries } from "@/lib/series";
import type { PairStat } from "@/lib/seriesTypes";
import "../series.css";

export const dynamicParams = false;
export function generateStaticParams() {
  return (getSeries("housing")?.measures ?? []).map((m) => ({ measure: m.id }));
}

export async function generateMetadata({ params }: { params: Promise<{ measure: string }> }): Promise<Metadata> {
  const { measure } = await params;
  const m = getSeries("housing")?.measures.find((x) => x.id === measure);
  return { title: m ? `${m.short} ${m.title} · 부동산 대책 흐름` : "부동산 대책 흐름" };
}

const KINDS = ["region", "price_band", "tenure", "age_band", "regulated", "housing_type"];
const COMPARE_KINDS = ["price_band", "tenure"];

function PairRow({ label, p, small }: { label: string; p: PairStat; small?: boolean }) {
  return (
    <tr className={small ? "is-small" : undefined}>
      <td>{label}{small ? " (적음)" : ""}</td><td>{p.n.toLocaleString()}</td>
      <td>{pct(p.favor[0])} → {pct(p.favor[1])}</td><td>{ppoint(change(p, "favor"))}</td>
      <td>{pct(p.oppose[0])} → {pct(p.oppose[1])}</td><td>{ppoint(change(p, "oppose"))}</td>
    </tr>
  );
}

export default async function MeasurePage({ params }: { params: Promise<{ measure: string }> }) {
  const { measure } = await params;
  const s = getSeries("housing")!;
  const m = s.measures.find((x) => x.id === measure)!;
  const a = m.conditions.alone, c = m.conditions.context;
  const tiles = (st: typeof a) => st.groups.province.map((g) => ({ province: g.group, n: g.n, mean: g.favor }));
  const assigned = s.housing_context?.tenure === "assigned";
  const ba = m.before_after;
  return (
    <div className="pp-container pp-page">
      <nav className="krds-breadcrumb-wrap pp-crumbs" aria-label="현재 경로">
        <ol className="breadcrumb">
          <li className="home"><Link href="/" className="txt">홈</Link></li>
          <li><Link href="/series/housing/" className="txt">부동산 대책 흐름</Link></li>
          <li><span className="txt">{m.short}</span></li>
        </ol>
      </nav>
      <p className="pp-sub">{m.date} · {m.agency}</p>
      <h1 className="pp-h1">{m.short} {m.title}</h1>
      <div className="pp-grid-4">
        <StatTile label="찬성 쪽(대책만)" value={pct(a.favor)} note={a.favor_ci95 ? `95% 구간 ${pct(a.favor_ci95[0])}~${pct(a.favor_ci95[1])}` : undefined} />
        <StatTile label="찬성 쪽(누적 맥락)" value={pct(c.favor)} />
        <StatTile label="누적 효과" value={`${ppoint(m.effect.overall.diff)}%p`} note="같은 사람의 두 답 차이" />
        <StatTile label="가장 유보적인 집단" value={m.top_reserve ? m.top_reserve.group : "–"} note={m.top_reserve ? `${s.kind_label[m.top_reserve.kind]} · 반대·유보 ${pct(m.top_reserve.reserve)}` : undefined} />
      </div>

      <section className="pp-section">
        <SectionHead title="조항별 찬반" desc="조항마다 찬성·반대 확률의 평균입니다. 왼쪽 숫자는 대책만, 오른쪽은 누적 맥락입니다(AI 추정)." />
        <div className="pp-card">
          <div className="pp-pos-row is-head"><div>조항</div><div>대책만</div><div>누적 맥락</div></div>
          {m.segments.map((sg) => (
            <div key={sg.id} className="pp-pos-row">
              <div>{sg.label}</div>
              <div>찬성 {pct(a.positions[sg.id].support)}<br /><small>반대 {pct(a.positions[sg.id].oppose)}</small></div>
              <div>찬성 {pct(c.positions[sg.id].support)}<br /><small>반대 {pct(c.positions[sg.id].oppose)}</small></div>
            </div>
          ))}
        </div>
      </section>

      <section className="pp-section">
        <SectionHead title="시도 지도" desc="색은 그 조건의 전국 값 대비 차이입니다. 100명 미만 시도는 해석하지 않습니다." />
        <div className="pp-grid-2">
          <div className="pp-card"><h3 className="pp-h3">대책만 · 전국 {pct(a.favor)}</h3><TileMap tiles={tiles(a)} minN={100} mode="gap" base={a.favor} label="대책만 시도별 찬성 쪽" /></div>
          <div className="pp-card"><h3 className="pp-h3">누적 맥락 · 전국 {pct(c.favor)}</h3><TileMap tiles={tiles(c)} minN={100} mode="gap" base={c.favor} label="누적 맥락 시도별 찬성 쪽" /></div>
        </div>
      </section>

      <section className="pp-section">
        <SectionHead title="집단별" desc={`찬성 쪽 %와 누적 효과(%p). ${assigned ? "점유 형태는 공식 통계로 배정한 값입니다." : "점유 형태는 추정 확률로 가중했습니다."}`} />
        <div className="pp-grid-2">
          {KINDS.filter((kind) => a.groups[kind]).map((kind) => (
            <div key={kind} className="pp-card">
              <h3 className="pp-h3">{s.kind_label[kind]}</h3>
              <div className="pp-series-table-wrap"><table className="pp-series-table">
                <thead><tr><th>집단</th><th>인원</th><th>대책만</th><th>누적</th><th>효과(%p)</th></tr></thead>
                <tbody>
                  {a.groups[kind].map((g) => {
                    const gc = c.groups[kind].find((x) => x.group === g.group);
                    const ge = m.effect.groups[kind]?.find((x) => x.group === g.group);
                    return (
                      <tr key={g.group} className={g.small ? "is-small" : undefined}>
                        <td>{g.group}{g.small ? " (적음)" : ""}</td><td>{g.n.toLocaleString()}</td>
                        <td>{pct(g.favor)}</td><td>{gc ? pct(gc.favor) : "–"}</td><td>{ge ? `${ppoint(ge.diff)}` : "–"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table></div>
            </div>
          ))}
        </div>
      </section>

      {ba && (
        <section className="pp-section">
          <SectionHead title="주거 정보를 넣기 전과 비교"
            desc="같은 사람이 주거 정보 없이 답한 값(앞선 실행)과 넣고 답한 값입니다(대책만). 변화는 %p입니다. 빈 블록만 넣어도 찬성 쪽이 2~4%p 내려가므로(시범), 반대 쪽 변화와 집단 사이 차이를 보십시오." />
          <div className="pp-card">
            <div className="pp-series-table-wrap"><table className="pp-series-table">
              <thead><tr><th>집단</th><th>인원</th><th>찬성 쪽 전 → 후</th><th>변화</th><th>반대 쪽 전 → 후</th><th>변화</th></tr></thead>
              <tbody>
                <PairRow label="전체" p={ba.overall} />
                {COMPARE_KINDS.filter((kind) => ba.groups[kind]).flatMap((kind) => [
                  <tr key={`${kind}-head`}><th colSpan={6} style={{ textAlign: "left", paddingTop: 12 }}>{s.kind_label[kind]}</th></tr>,
                  ...ba.groups[kind].map((g) => <PairRow key={`${kind}-${g.group}`} label={g.group} p={g} small={g.small} />),
                ])}
              </tbody>
            </table></div>
          </div>
        </section>
      )}

      {m.housing_examples && (
        <section className="pp-section">
          <SectionHead title="인물에게 붙인 주거 정보 예시" desc="이 대책을 물을 때 해당 집에 사는 인물에게 보인 글 그대로입니다(시군구 이름도 인물 DB 표기 그대로). 실거래는 발표 달 직전 3개월, 거래 10건 미만인 칸은 뺐습니다." />
          <div className="pp-housing-examples">
            {m.housing_examples.map((e) => <div key={e.label} className="pp-card"><h4>{e.label}</h4><pre>{e.text}</pre></div>)}
          </div>
        </section>
      )}

      <section className="pp-section">
        <SectionHead title="부동산 문항" />
        <div className="pp-grid-4">
          {Object.entries(s.housing_labels).map(([k, label]) => (
            <StatTile key={k} label={label} value={pct(a.housing[k])} note={`누적 맥락 ${pct(c.housing[k])}`} />
          ))}
        </div>
      </section>

      <section className="pp-section">
        <SectionHead title={m.source.text_kind === "summary" ? "본문 요약(원문 대신)" : "인물에게 보여 준 본문"} desc={m.source.note} />
        <div className="pp-measure-text">{m.text}</div>
        <p className="pp-sub" style={{ marginTop: 8 }}>누적 맥락 요약: {m.summary} · <a href={m.source.url} target="_blank" rel="noreferrer">출처 원문</a>
          {m.source.file && <> · <a href={m.source.file} target="_blank" rel="noreferrer">본문을 옮긴 파일</a></>}</p>
        {m.source.title && (
          <p className="pp-sub">출처: {m.source.provider ? `${m.source.provider}, ` : ""}「{m.source.title}」{m.source.license ? ` · ${m.source.license}` : ""}</p>
        )}
      </section>
    </div>
  );
}
