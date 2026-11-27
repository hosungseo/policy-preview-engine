import type { Metadata } from "next";
import Link from "next/link";
import ProbDistribution from "@/components/ProbDistribution";
import SectionHead from "@/components/SectionHead";
import StatTile from "@/components/StatTile";
import TileMap from "@/components/TileMap";
import ChangeHeatmap, { change, ChangeLegend } from "@/components/series/ChangeHeatmap";
import DiffStrip from "@/components/series/DiffStrip";
import Dumbbell from "@/components/series/Dumbbell";
import MiniLines, { sharedDomain } from "@/components/series/MiniLines";
import SeriesHeatmap from "@/components/series/SeriesHeatmap";
import SeriesLine from "@/components/series/SeriesLine";
import { GAP_BINS, SERIES_COLOR } from "@/lib/colors";
import { dateKo, duration, peopleKo, pct, ppoint } from "@/lib/format";
import { getSeries } from "@/lib/series";
import type { SeriesBundle, SeriesMeasure } from "@/lib/seriesTypes";
import "./series.css";

export const metadata: Metadata = { title: "부동산 대책 흐름" };

function Key({ cond }: { cond: "alone" | "context" }) {
  return (
    <svg width="30" height="12" aria-hidden="true">
      <line x1="0" y1="6" x2="30" y2="6" stroke={SERIES_COLOR[cond]} strokeWidth="2" />
      {cond === "alone"
        ? <circle cx="15" cy="6" r="4.5" fill={SERIES_COLOR.alone} stroke="#fff" strokeWidth="2" />
        : <circle cx="15" cy="6" r="4" fill="#fff" stroke={SERIES_COLOR.context} strokeWidth="2" />}
    </svg>
  );
}

function groupLines(s: SeriesBundle, kind: string) {
  const ms = s.measures, shorts = ms.map((m) => m.short);
  const national = ms.map((m) => m.conditions.alone.favor);
  const find = (m: SeriesMeasure, g: string) => m.conditions.alone.groups[kind]?.find((x) => x.group === g);
  const groups = s.order[kind].filter((g) => ms.some((m) => find(m, g)));
  const valuesOf = (g: string) => ms.map((m) => find(m, g)?.favor ?? null);
  const domain = sharedDomain([...national, ...groups.flatMap(valuesOf)]);
  return groups.map((g) => {
    const vals = valuesOf(g);
    const ns = ms.map((m) => find(m, g)?.n).filter((n): n is number => n !== undefined);
    const lo = Math.min(...ns), hi = Math.max(...ns);
    const small = ms.some((m) => find(m, g)?.small);
    const allSmall = ms.every((m) => find(m, g)?.small ?? true);
    const seen = vals.flatMap((v, i) => (v === null ? [] : [i]));
    const a = seen[0], b = seen[seen.length - 1];
    return (
      <MiniLines key={g} title={g} shorts={shorts} domain={domain}
        sub={`${lo === hi ? lo.toLocaleString() : `${lo.toLocaleString()}~${hi.toLocaleString()}`}명${allSmall ? " · 적음(해석 안 함)" : small ? " · 일부 적음" : ""}`}
        series={[{ label: "전국", color: "#b1b8be", values: national, width: 1.5 }, { label: g, color: SERIES_COLOR.alone, values: vals }]}
        foot={`${shorts[a]} ${pct(vals[a] as number)} → ${shorts[b]} ${pct(vals[b] as number)}`} />
    );
  });
}

// One legend for every gap-coloured view on the page (heatmaps and the grid of small maps).
function GapLegend() {
  return (
    <ul className="pp-legend">
      {GAP_BINS.map((b) => <li key={b.label}><span className="pp-swatch" style={{ background: b.color, border: "1px solid #cdd1d5" }} />{b.label}</li>)}
      <li><span className="pp-swatch" style={{ background: "#fff", border: "1px dashed #cdd1d5" }} />100명 미만(해석 안 함)</li>
    </ul>
  );
}

// "공식 임차 38%보다 낮고" style comparison (the sentence's last clause ends in "-습니다"); within 2%p reads as similar.
function versus(est: number, official: number, name: string, last = false) {
  const [similar, lower, higher] = last ? ["와 비슷합니다", "보다 낮습니다", "보다 높습니다"] : ["와 비슷하고", "보다 낮고", "보다 높고"];
  return `${name} ${pct(official)}${Math.abs(est - official) < 0.02 ? similar : est < official ? lower : higher}`;
}

const USAGE_LABEL: Record<string, string> = { tenure: "점유 형태 추정", alone: "대책 판정 · 대책만", context: "대책 판정 · 누적 맥락" };
// Group kinds of the housing information (shown before the comparison) and the rest.
const HOUSING_GROUP_KINDS = ["price_band", "tenure"];
const OTHER_GROUP_KINDS = ["age_band", "regulated", "housing_type"];
// The measure whose example housing blocks the method section shows.
const EXAMPLE_MEASURE = "2025-10-15-stabilization";

function groupDesc(s: SeriesBundle, kind: string): string {
  const assigned = s.housing_context?.tenure === "assigned";
  if (kind === "price_band") return `${s.housing_context?.price_band_note ?? "사는 곳 아파트값으로 나눴습니다"}. 파란 선은 그 집단, 회색 선은 전국입니다(대책만).`;
  if (kind === "tenure") return assigned
    ? "점유 형태는 공식 통계(2020 인구주택총조사·2024 주거실태조사)로 사람마다 배정했습니다. 아래 배정 확인을 함께 보십시오."
    : "점유 형태는 인물 서술로 Jev가 추정한 확률로 가중했습니다(AI 추정). 아래 공식 통계 대조를 함께 보십시오.";
  if (kind === "regulated") return "대책 발표일에 그 인물의 시군구가 투기과열지구·조정대상지역이었는지로 나눴습니다. 화성시는 인물 DB에 구 구분이 없어 동탄구 지정 뒤 '일부'로 둡니다.";
  return "파란 선은 그 집단, 회색 선은 전국입니다(대책만).";
}

function GroupSection({ s, kind }: { s: SeriesBundle; kind: string }) {
  if (!s.measures[0].conditions.alone.groups[kind]) return null;
  return (
    <section className="pp-section">
      <SectionHead title={`집단별 흐름: ${s.kind_label[kind]}`} desc={groupDesc(s, kind)} />
      <div className="pp-series-multiples">{groupLines(s, kind)}</div>
    </section>
  );
}

// The biggest paired moves among groups large enough to read.
function Moves({ s, kinds }: { s: SeriesBundle; kinds: string[] }) {
  const cells = s.measures.flatMap((m) => kinds.flatMap((kind) =>
    (m.before_after?.groups[kind] ?? []).filter((g) => !g.small).map((g) => ({ m, g }))));
  const top = (score: (c: (typeof cells)[number]) => number) => [...cells].sort((a, b) => score(b) - score(a)).slice(0, 4);
  const lists = [
    { title: "반대 쪽이 가장 많이 늘어난 곳", stat: "oppose" as const, rows: top((c) => change(c.g, "oppose")) },
    { title: "찬성 쪽이 가장 많이 내려간 곳", stat: "favor" as const, rows: top((c) => -change(c.g, "favor")) },
    { title: "찬성 쪽이 가장 많이 올라간 곳", stat: "favor" as const, rows: top((c) => change(c.g, "favor")) },
  ];
  return (
    <div className="pp-series-moves">
      {lists.map((l) => (
        <div key={l.title}>
          <h4>{l.title}</h4>
          <ol>
            {l.rows.map(({ m, g }) => (
              <li key={`${m.id}-${g.group}`}><b>{g.group}</b> · {m.short} {pct(g[l.stat][0])} → {pct(g[l.stat][1])} ({ppoint(change(g, l.stat))}%p)</li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  );
}

function tiles(m: SeriesMeasure) {
  return m.conditions.alone.groups.province.map((g) => ({ province: g.group, n: g.n, mean: g.favor }));
}

export default function HousingSeries() {
  const s = getSeries("housing");
  if (!s) {
    return (
      <div className="pp-container pp-page">
        <h1 className="pp-h1">부동산 대책 흐름</h1>
        <p className="pp-lead">결과를 준비하고 있습니다.</p>
      </div>
    );
  }
  const ms = s.measures;
  const usage = Object.values(s.meta.jev_usage).flatMap((stage) => Object.values(stage));
  // Answers reused from the Jev cache are not calls (no tokens, no cost); they are counted separately.
  const calls = usage.reduce((a, u) => a + u.calls, 0), cost = usage.reduce((a, u) => a + u.cost_usd, 0);
  const reused = usage.reduce((a, u) => a + (u.cached ?? 0), 0);
  const seconds = s.meta.stages.reduce((a, st) => a + st.seconds, 0);
  const shorts = ms.map((m) => m.short);
  const housingKeys = Object.keys(s.housing_labels);
  const housingDomain = sharedDomain(ms.flatMap((m) => housingKeys.flatMap((k) => [m.conditions.alone.housing[k], m.conditions.context.housing[k]])));
  const hc = s.housing_context;
  const assigned = hc?.tenure === "assigned";
  const compared = ms.some((m) => m.before_after);
  const example = ms.find((m) => m.id === EXAMPLE_MEASURE && m.housing_examples) ?? ms.find((m) => m.housing_examples);
  return (
    <div className="pp-container pp-page">
      <h1 className="pp-h1">부동산 대책 흐름</h1>
      <p className="pp-lead">{s.subtitle}.{hc ? " 사는 곳 집값과 점유 형태를 공식 통계로 넣었고," : ""} 판단 모델 Jev만 썼습니다(AI 추정).</p>
      {s.dev && <p className="pp-sub" style={{ color: "#ab2b36" }}>개발용 모의 결과입니다(배포 안 함).</p>}
      <div className="pp-series-caution">
        <ul>
          <li>합성 인물 {s.panel.n.toLocaleString()}명(시도·연령·성별 층화)의 반응을 AI가 추정한 값입니다. 실제 여론이 아닙니다.</li>
          {hc ? (
            <>
              <li><b>주거 정보</b>: 인물마다 공식 통계로 자가·전세·월세를 배정하고, 대책마다 사는 시군구의 발표 직전 3개월 실거래가와 주택 소유 통계를 함께 보여 줬습니다. 배정은 통계에 맞춘 가정이지 그 사람의 사실이 아닙니다.</li>
              <li>인물의 나이·직업·가족은 그대로이고, 집값만 대책마다 발표 직전 3개월 실거래로 바꿔 보여 줬습니다. 금리·심리 같은 그때의 다른 시장 상황은 담지 않았습니다.</li>
            </>
          ) : (
            <li>인물은 시간이 흐르지 않습니다. 가로축 날짜는 발표 순서와 간격을 보여 줄 뿐, 그때의 시장 상황은 담지 않았습니다.</li>
          )}
          <li><b>대책만</b>은 그 대책만 보고, <b>누적 맥락</b>은 앞서 발표된 대책의 한 줄 요약을 함께 보고 평가한 값입니다. 같은 사람의 두 답을 뺀 값이 누적 효과입니다.</li>
        </ul>
      </div>
      <p className="pp-series-mapcta"><Link href="/series/housing/map/" className="krds-btn medium secondary">100만 명 지도로 보기</Link>
        <span>합성 인물 100만 명을 점으로 찍고, 1만 명의 답을 대책마다 색으로 봅니다.</span></p>
      <div className="pp-grid-4">
        <StatTile label="대책" value={`${ms.length}건`} note={`${dateKo(ms[0].date + "T00:00:00+09:00")} ~ ${dateKo(ms[ms.length - 1].date + "T00:00:00+09:00")}`} />
        <StatTile label="합성 인물" value={`${s.panel.n.toLocaleString()}명`} note="모든 대책에 같은 사람" />
        <StatTile label="Jev 호출" value={`${calls.toLocaleString()}회`}
          note={`${reused ? `저장한 답 재사용 ${reused.toLocaleString()}건 · ` : ""}계산 시간 합계 ${duration(seconds)}`} />
        <StatTile label="비용" value={`$${cost.toFixed(2)}`} note="100만 토큰당 $0.042" />
      </div>

      <section className="pp-section">
        <SectionHead title="찬성 쪽 비율의 흐름" desc="대책별로 찬성·강한 찬성 확률의 합을 평균 낸 값입니다. 가로축은 실제 발표일 간격이고, 휴대폰에서는 번호로 고르게 폈습니다." />
        <div className="pp-card">
          <ul className="pp-series-legend">
            <li><Key cond="alone" />대책만(그 대책만 보고 평가)</li>
            <li><Key cond="context" />누적 맥락(앞선 대책 요약과 함께 평가)</li>
          </ul>
          <SeriesLine measures={ms} />
          <h3 className="pp-h3" style={{ marginTop: 16 }}>누적 효과</h3>
          <p className="pp-sub">같은 사람의 두 답을 짝지어 뺀 값(누적 맥락 − 대책만), %p. 가는 선은 95% 구간입니다. 첫 대책은 앞선 대책이 없어 두 조건이 같습니다.</p>
          <DiffStrip measures={ms} />
          <ol className="pp-series-list">
            {ms.map((m) => <li key={m.id}><b>{m.short}</b> {m.title}</li>)}
          </ol>
        </div>
      </section>

      <section className="pp-section">
        <SectionHead title="대책별 찬반 5단계" desc="대책만 조건의 확률 평균입니다." />
        <div className="pp-card">
          <ProbDistribution rows={ms.map((m) => ({ label: `${m.short} ${m.title}`, sub: `${m.date} · ${m.agency}`, shares: m.conditions.alone.mass }))} />
        </div>
      </section>

      <section className="pp-section">
        <SectionHead title="지역" desc="칸의 숫자는 찬성 쪽 %입니다. 색은 그 대책의 전국 값 대비 차이라서, 차이가 작아도 어느 쪽인지 보입니다. 점선 칸은 인원이 적어 해석하지 않습니다." />
        <GapLegend />
        <div className="pp-card"><h3 className="pp-h3">시도 × 대책: 찬성 쪽 %</h3><SeriesHeatmap measures={ms} mode="favor" /></div>
        <div className="pp-card" style={{ marginTop: 16 }}>
          <h3 className="pp-h3">시도 × 대책: 누적 효과(%p)</h3>
          <p className="pp-sub pp-narrow-only">표를 좌우로 밀면 모든 대책이 보입니다.</p>
          <SeriesHeatmap measures={ms} mode="effect" />
        </div>
        <div className="pp-card" style={{ marginTop: 16 }}>
          <h3 className="pp-h3">대책별 시도 지도</h3>
          <p className="pp-sub">칸마다 시도, 찬성 쪽 %, 전국 대비 차이(%p)를 적었습니다.</p>
          <GapLegend />
          <div className="pp-series-maps">
            {ms.map((m) => (
              <div key={m.id}>
                <b>{m.short}</b> <span className="pp-sub">전국 {pct(m.conditions.alone.favor)}</span>
                <TileMap tiles={tiles(m)} minN={100} mode="gap" base={m.conditions.alone.favor} label={`${m.short} 시도별 찬성 쪽`} compact />
              </div>
            ))}
          </div>
        </div>
        <h3 className="pp-h3" style={{ marginTop: 16 }}>권역별 흐름</h3>
        <p className="pp-sub">파란 선은 그 권역, 회색 선은 전국입니다(대책만).</p>
        <div className="pp-series-multiples">{groupLines(s, "region")}</div>
      </section>

      {HOUSING_GROUP_KINDS.map((kind) => <GroupSection key={kind} s={s} kind={kind} />)}

      {compared && (
        <section className="pp-section">
          <SectionHead title="주거 정보를 넣기 전과 비교"
            desc={`같은 ${peopleKo(s.panel.n)}이 주거 정보 없이 답한 값(앞선 실행에서 같은 사람의 답)과, 넣고 답한 값의 차이입니다. 대책만 조건이고 단위는 %p입니다. 집단은 넣은 뒤 기준(아파트값·배정한 점유 형태)으로 묶었습니다.`} />
          <div className="pp-card">
            <Moves s={s} kinds={HOUSING_GROUP_KINDS} />
          </div>
          <div className="pp-card" style={{ marginTop: 16 }}>
            <h3 className="pp-h3">찬성 쪽 변화(%p)</h3>
            <p className="pp-sub pp-narrow-only">표를 좌우로 밀면 모든 대책이 보입니다.</p>
            <ChangeLegend stat="favor" />
            <ChangeHeatmap s={s} kinds={HOUSING_GROUP_KINDS} stat="favor" />
          </div>
          <div className="pp-card" style={{ marginTop: 16 }}>
            <h3 className="pp-h3">반대 쪽 변화(%p)</h3>
            <p className="pp-sub">반대·강한 반대 확률의 합입니다. 반대 쪽이 늘면 붉게 칠했습니다.</p>
            <p className="pp-sub pp-narrow-only">표를 좌우로 밀면 모든 대책이 보입니다.</p>
            <ChangeLegend stat="oppose" />
            <ChangeHeatmap s={s} kinds={HOUSING_GROUP_KINDS} stat="oppose" />
          </div>
          {/* Pilot: runs/series-housing-ctxpilot (2,000 people x 4 measures, a same-shape block without facts). */}
          <p className="pp-series-note">
            <b>읽는 법</b>: 시범(2,000명·대책 4건)에서 사실은 빼고 같은 모양의 빈 블록만 넣어도 찬성 쪽이 1.7~3.7%p 내려갔고, 반대 쪽은 −1.1~+0.3%p로 거의 그대로였습니다.
            그래서 찬성 쪽이 조금씩 내려간 칸에는 블록을 넣은 것 자체의 몫이 섞여 있습니다. 반대 쪽 변화와 집단 사이의 차이가 주거 정보의 효과에 가깝습니다.
          </p>
        </section>
      )}

      {OTHER_GROUP_KINDS.map((kind) => <GroupSection key={kind} s={s} kind={kind} />)}

      <section className="pp-section">
        <SectionHead title="부동산 문항 4개" desc="대책마다 같은 네 문항을 물었습니다. 파란 선은 대책만, 보라 선은 누적 맥락입니다." />
        <div className="pp-series-multiples">
          {housingKeys.map((k) => (
            <MiniLines key={k} title={s.housing_labels[k]} shorts={shorts} domain={housingDomain}
              series={[{ label: "대책만", color: SERIES_COLOR.alone, values: ms.map((m) => m.conditions.alone.housing[k]) },
                       { label: "누적 맥락", color: SERIES_COLOR.context, values: ms.map((m) => m.conditions.context.housing[k]) }]}
              foot={`${shorts[0]} ${pct(ms[0].conditions.alone.housing[k])} → ${shorts[shorts.length - 1]} ${pct(ms[ms.length - 1].conditions.alone.housing[k])}`} />
          ))}
        </div>
      </section>

      <section className="pp-section">
        <SectionHead title={assigned ? "점유 형태 배정 확인" : "점유 형태 추정 검증"}
          desc={assigned
            ? `시도별 자가 비율: 배정 결과(사람 단위, 파란 점)와 ${s.tenure.official.survey ?? `공식 통계 ${s.tenure.official.year}`}(${s.tenure.official.unit ?? "가구"} 단위, 회색 네모). 시도 비율에 맞춰 배정했지만, 인물의 주택 종류·나이 구성과 단위 차이(사람 단위에서는 식구가 많은 가구가 크게 잡힘), 뽑기 오차 때문에 시도에 따라 몇 %p 벌어집니다.`
            : `시도별 자가 비율: Jev 추정(사람 단위, 파란 점)과 ${s.tenure.official.survey ?? `공식 통계 ${s.tenure.official.year}`}(${s.tenure.official.unit ?? "가구"} 단위, 회색 네모). 단위가 달라 완전히 같을 수는 없지만, 크게 어긋나면 점유 형태별 결과를 조심해서 읽어야 합니다.`} />
        <div className="pp-card">
          <Dumbbell rows={s.tenure.provinces} label={assigned ? "배정" : "추정"} />
          <p className="pp-sub" style={{ marginTop: 10 }}>
            전국 {assigned ? "배정" : "추정"}(사람): 자가 {pct(s.tenure.overall.own)} · 전세 {pct(s.tenure.overall.jeonse)} · 월세 {pct(s.tenure.overall.monthly)} · 기타 {pct(s.tenure.overall.other)}
            {s.tenure.official.national && <> / 공식(가구): 자가 {pct(s.tenure.official.national.own)} · 임차(전세·월세) {pct(s.tenure.official.national.rent)} · 무상 {pct(s.tenure.official.national.free)}</>}.
            공식 자료: <a href={s.tenure.official.source} target="_blank" rel="noreferrer">{s.tenure.official.publisher ?? "출처"}</a>
          </p>
          {assigned && (() => {
            const far = s.tenure.provinces.filter((r) => r.official_own !== null && Math.abs(r.own - r.official_own) >= 0.05)
              .sort((a, b) => Math.abs(b.own - b.official_own!) - Math.abs(a.own - a.official_own!));
            return far.length > 0 && (
              <p className="pp-sub">5%p 이상 벌어진 시도: {far.map((r) => `${r.province} ${ppoint(r.own - r.official_own!, 0)}%p${r.n < 100 ? `(${r.n}명, 적음)` : ""}`).join(", ")}. 이 시도의 점유 형태별 결과는 조심해서 읽으십시오.</p>
            );
          })()}
          {assigned && hc?.tenure_before && (
            <p className="pp-sub">
              앞선 실행에서는 Jev가 인물 서술만 보고 점유 형태를 추정했는데, 같은 사람들이 자가 {pct(hc.tenure_before.own)} · 전세 {pct(hc.tenure_before.jeonse)} · 월세 {pct(hc.tenure_before.monthly)} · 기타 {pct(hc.tenure_before.other)}로
              임차(전세+월세) {pct(hc.tenure_before.jeonse + hc.tenure_before.monthly)}가 공식 임차 {s.tenure.official.national ? pct(s.tenure.official.national.rent) : "비율"}보다 크게 낮았습니다. 그래서 이번에는 공식 통계로 배정했습니다.
            </p>
          )}
          {!assigned && s.tenure.official.national && (
            <p className="pp-sub">
              추정 임차(전세+월세) {pct(s.tenure.overall.jeonse + s.tenure.overall.monthly)}는 {versus(s.tenure.overall.jeonse + s.tenure.overall.monthly, s.tenure.official.national.rent, "공식 임차")},
              추정 기타 {pct(s.tenure.overall.other)}는 {versus(s.tenure.overall.other, s.tenure.official.national.free, "공식 무상", true)}.
              인물 서술만으로 점유 형태를 짐작한 값이라 공식 통계와 어긋날 수 있으니, 차이가 큰 만큼 점유 형태별 흐름을 조심해서 읽으십시오.
            </p>
          )}
        </div>
      </section>

      <section className="pp-section">
        <SectionHead title={`대책 ${ms.length}건`} desc="요약문은 누적 맥락 조건에서 인물에게 보여 준 문장 그대로입니다. 본문은 정책브리핑(공공누리 제1유형) 원문을 옮겼고, 공공누리 표시가 없는 금융위원회 보도자료 3건은 원문 대신 이 저장소가 쓴 요약을 둡니다." />
        <div className="pp-measure-cards">
          {ms.map((m) => (
            <div key={m.id} className="pp-card pp-measure-card">
              <div className="pp-measure-meta">{m.date} · {m.agency}</div>
              <h3><Link href={`/series/housing/${m.id}/`}>{m.short} {m.title}</Link></h3>
              <p>{m.summary}</p>
              <div className="pp-measure-nums">
                <span>찬성 쪽 <b>{pct(m.conditions.alone.favor)}</b></span>
                <span>누적 효과 <b>{ppoint(m.effect.overall.diff)}%p</b></span>
                {m.top_reserve && <span>가장 유보적: <b>{s.kind_label[m.top_reserve.kind]} · {m.top_reserve.group}</b> (반대·유보 {pct(m.top_reserve.reserve)})</span>}
              </div>
              <a href={m.source.url} target="_blank" rel="noreferrer">출처 원문</a>
              {m.source.license && <span className="pp-measure-meta"> {m.source.license}</span>}
            </div>
          ))}
        </div>
      </section>

      <section className="pp-section">
        <SectionHead title="방법과 비용" />
        <div className="pp-card">
          {assigned ? (
            <>
              <p>100만 명 합성 인물 DB(NVIDIA Nemotron-Personas-Korea)에서 시도·연령대·성별로 층화해 뽑은 앞선 패널에서, 같은 층 비율을 지켜 {s.panel.n.toLocaleString()}명을 다시 뽑고 모든 대책에 같은 사람을 썼습니다. 한 사람에게 한 번 호출로 찬반 5단계, 직접 영향, 조항별 영향·찬반, 부동산 문항 4개를 물었습니다. 점유 형태는 묻지 않고 공식 통계로 배정했고, 질문마다 아래와 같은 주거 정보를 붙였습니다. LLM은 쓰지 않았습니다.</p>
              <ul className="pp-series-usage">
                <li><b>점유 형태</b> {hc!.tenure_note}</li>
                <li><b>주거 정보</b> {hc!.market_note}</li>
                {hc!.price_band_note && <li><b>사는 곳 아파트값</b> {hc!.price_band_note}</li>}
              </ul>
              {example?.housing_examples && (
                <>
                  <h3 className="pp-h3" style={{ marginTop: 16 }}>인물에게 붙인 주거 정보 예시({example.short} {example.title})</h3>
                  <p className="pp-sub">인물에게 보인 글 그대로입니다(시군구 이름도 인물 DB 표기 그대로). 거래가 10건 미만인 칸은 빼고 보였습니다.</p>
                  <div className="pp-housing-examples">
                    {example.housing_examples.map((e) => <div key={e.label}><h4>{e.label}</h4><pre>{e.text}</pre></div>)}
                  </div>
                </>
              )}
            </>
          ) : (
            <p>100만 명 합성 인물 DB(NVIDIA Nemotron-Personas-Korea)에서 시도·연령대·성별로 층화해 {s.panel.n.toLocaleString()}명을 뽑고, 모든 대책에 같은 사람을 썼습니다. 한 사람에게 한 번 호출로 찬반 5단계, 직접 영향, 조항별 영향·찬반, 부동산 문항 4개를 물었습니다. 점유 형태(자가·전세·월세·기타)는 대책과 따로 한 번 물었습니다. LLM은 쓰지 않았습니다.</p>
          )}
          <ul className="pp-series-usage">
            {Object.entries(s.meta.jev_usage).flatMap(([stage, tasks]) => Object.entries(tasks).map(([label, u]) => (
              <li key={`${stage}-${label}`}><b>{USAGE_LABEL[label] ?? label}</b> 호출 {u.calls.toLocaleString()}회{u.cached ? ` + 저장한 답 재사용 ${u.cached.toLocaleString()}건` : ""} · 입력 {u.input_tokens.toLocaleString()}토큰 · ${u.cost_usd.toFixed(2)}</li>
            )))}
          </ul>
        </div>
      </section>
    </div>
  );
}
