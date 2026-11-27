import type { Metadata } from "next";
import AiNotice from "@/components/AiNotice";
import AmendmentCompare from "@/components/AmendmentCompare";
import ClauseHeatmap from "@/components/ClauseHeatmap";
import ConsistencyPanel from "@/components/ConsistencyPanel";
import JevReceipt from "@/components/JevReceipt";
import JevUsageTable from "@/components/JevUsageTable";
import QualityPanel from "@/components/QualityPanel";
import MeanRows from "@/components/MeanRows";
import MetricBar from "@/components/MetricBar";
import PositionBars from "@/components/PositionBars";
import ProbDistribution from "@/components/ProbDistribution";
import RunHeader from "@/components/RunHeader";
import SectionHead from "@/components/SectionHead";
import StatTile from "@/components/StatTile";
import TileMap from "@/components/TileMap";
import { getRun, indexBundle, runParams } from "@/lib/bundles";
import { pct, signed } from "@/lib/format";
import type { GroupRow, JevGroupRow } from "@/lib/types";
import "./jev.css";

export const dynamicParams = false;
export function generateStaticParams() {
  return runParams();
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `정량 점검(Jev) · ${getRun(id).title}` };
}

const GROUPS: [string, string][] = [
  ["age_band", "연령대"], ["region", "권역"], ["sex", "성별"], ["education_level", "학력"],
  ["housing_type", "주거 형태"], ["family", "가구"], ["occupation_major", "직업군"],
];
const KEYS = ["-2", "-1", "0", "1", "2"];

function asGroupRows(rows: JevGroupRow[]): GroupRow[] {
  return rows.map((r) => ({ group: r.group, n: r.n, mean: r.mean, oppose: r.reserve, favor: 1 - r.reserve, small: r.small }));
}

function Rate({ value }: { value: number }) {
  return (
    <span className="pp-rate-cell">
      <span className="pp-rate-track" aria-hidden="true"><span className="pp-rate-fill" style={{ width: `${value * 100}%`, display: "block" }} /></span>
      <b>{pct(value)}</b>
    </span>
  );
}

function RateTable({ title, rows }: { title: string; rows: JevGroupRow[] }) {
  return (
    <div className="pp-card">
      <h3 className="pp-h3">{title}</h3>
      <table className="pp-rate-table">
        <thead><tr><th>집단</th><th>인원</th><th>직접 영향 확률</th><th>스스로 의견 낼 확률</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.group} className={r.small ? "pp-rate-small" : undefined}>
              <th scope="row">{r.group}</th>
              <td className="pp-num">{r.n}</td>
              <td><Rate value={r.direct} /></td>
              <td><Rate value={r.comment} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function JevPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const b = getRun(id);
  const j = b.analysis.jev;
  const segments = b.segments.map((s) => ({ id: s.id, label: s.label }));

  if (!j) {
    return (
      <div>
        <AiNotice />
        <RunHeader bundle={b} active="jev" />
        <div className="pp-container pp-section"><p className="pp-lead">이 사례는 Jev 정량 점검 없이 실행됐습니다.</p></div>
      </div>
    );
  }

  const mass = j.overall.mass;
  const favor = mass[3] + mass[4];
  const reserve = mass[0] + mass[1] + mass[2];
  const cmp = j.compare;
  const llmShares = cmp.llm_dist ? KEYS.map((k) => (cmp.llm_dist?.[k] ?? 0) / cmp.n) : null;
  const maxChannel = Math.max(...j.channels.map((c) => c.share), 0.01);
  const ia = b.meta.counts.issue_assignment;
  const ix = indexBundle(b);
  const nQuestions = 4 + segments.length + (j.positions ? segments.length : 0) + (j.methods?.length ?? 0)
    + (j.explain ? 2 : 0) + (j.issue_prevalence ? b.analysis.issues.length : 0);
  const segLabel = (id: string) => ix.segment.get(id)?.label;
  const issueRows = b.analysis.issues.map((it) => ({ id: it.id, label: it.title }));
  const methodRows = (j.methods ?? []).map((m) => ({ id: m.key, label: m.label }));
  const positionOverall = j.positions ? Object.fromEntries(Object.entries(j.positions.overall).map(([k, v]) => [k, v.mean])) : {};
  const methodOverall = Object.fromEntries((j.methods ?? []).map((m) => [m.key, m.p]));
  const tiles = (key: "direct" | "reserve") => (j.provinces ?? []).map((t) => ({ province: t.province, n: t.n, mean: t[key] }));
  const spread = (key: "direct" | "reserve") => {
    const values = (j.provinces ?? []).filter((t) => t.n >= 30).map((t) => t[key]);
    return values.length > 1 ? Math.max(...values) - Math.min(...values) : 0;
  };

  return (
    <div>
      <AiNotice extra="Jev는 합성 인물에 대해 보정된 확률을 답합니다. 실제 여론이 아니며, 수치는 집단 단위로 읽습니다." />
      <RunHeader bundle={b} active="jev" />
      <div className="pp-container">
        <section className="pp-section">
          <div className="pp-jev-intro">
            <h2 className="pp-h2">{j.n.toLocaleString()}명에게 확률로 다시 물었습니다</h2>
            <p className="pp-sub" style={{ marginBottom: 8 }}>
              TypeSafe의 Jev는 문장을 쓰지 않고, 정해 둔 질문에 보정된(calibrated) 확률로 답하는 판단 모델(System One)입니다.
              대표 패널과 같은 방식(시도×연령대×성별 층화)으로 뽑은 {j.n.toLocaleString()}명과 LLM 패널 {cmp.n}명에게 한 사람당
              한 번씩, 아래 질문을 한꺼번에 물었습니다.
            </p>
            <ul className="pp-jev-asked">
              <li><b>찬반</b> 5단계 점수 — <code>How would this person react to the policy?</code></li>
              <li><b>직접 영향</b> 예·아니오 확률 — 이 정책이 이 사람의 일·일상·지출을 직접 바꾸는가</li>
              <li><b>조항별 영향</b> 조항 {segments.length}개 각각에 대한 예·아니오 확률</li>
              <li><b>참여 가능성</b> 공식 의견수렴(입법예고 의견, 공청회)에 스스로 의견을 낼 확률</li>
              <li><b>소식 경로</b> 이런 소식을 주로 접하는 곳(10개 중 하나)</li>
              {j.positions && <li><b>조항별 찬반</b> 조항마다 반대·중립·찬성 3단계 점수</li>}
              {j.issue_prevalence && <li><b>쟁점 공감</b> LLM 패널에서 나온 쟁점 {b.analysis.issues.length}개 각각을 이 사람도 제기할 확률</li>}
              {j.methods && <li><b>참여 방식</b> 설명회, 경로당·마을 방문, 문자 설문, 전화, 직장·단체, 입법예고 의견 여섯 가지 각각에 실제로 참여할 확률</li>}
              {j.explain && <li><b>설명 필요 조항</b> 의견을 내기 전에 설명이 가장 필요한 조항, 원문만으로 이해할 확률</li>}
            </ul>
            {j.positions && (
              <p className="pp-sub" style={{ margin: "8px 0 0" }}>
                질문을 10개에서 31개로 늘려도 한 번 호출에 걸리는 시간은 0.3~1.3초로 같았고, 늘어나는 것은 입력 토큰(비용)뿐이었습니다.
                그래서 한 사람에게 필요한 판단을 한 번에 모두 묻습니다.
              </p>
            )}
          </div>
          <JevReceipt meta={b.meta} stage="jev" tasks={["panel"]} note="한 사람당 한 번, 질문을 모두 담아" />
          <div className="pp-grid-4 pp-jev-tiles">
            <StatTile label="정량 패널" value={`${j.n.toLocaleString()}명`} note="층화 추출" />
            <StatTile label="찬성 쪽 확률" value={pct(favor)} note="찬성+강한 찬성" />
            <StatTile label="반대·유보" value={pct(reserve)} note="반대·중립" />
            <StatTile label="평균 지지" value={signed(j.overall.mean)}
              note={j.overall.ci95 ? `95% 구간 ${signed(j.overall.ci95[0])} ~ ${signed(j.overall.ci95[1])}` : undefined} />
          </div>
        </section>

        <section className="pp-section">
          <SectionHead title="찬반 확률 분포" desc="사람마다 받은 5단계 확률을 평균한 값입니다. 한 사람의 답 하나가 아니라 확률의 합입니다." />
          <div className="pp-card">
            <ProbDistribution rows={[{ label: "Jev 정량 패널", sub: `${j.n.toLocaleString()}명`, shares: mass }]} />
          </div>
        </section>

        {llmShares && cmp.jev_mass && (
          <section className="pp-section">
            <SectionHead title="같은 사람, 두 도구"
              desc="LLM 패널 사람들에게 LLM은 한 사람당 답 하나를 뽑았고, Jev는 같은 사람들에게 확률 분포를 줬습니다. LLM이 한쪽으로 쏠리는지 여기서 확인합니다." />
            <div className="pp-card">
              <ProbDistribution rows={[
                { label: "LLM", sub: `${cmp.n}명 · 한 번씩 답함`, shares: llmShares },
                { label: "Jev", sub: `같은 ${cmp.n}명 · 확률`, shares: cmp.jev_mass },
              ]} />
            </div>
            <div className="pp-grid-4" style={{ marginTop: 12 }}>
              <StatTile label="LLM 찬성 비율" value={pct(cmp.llm_favor ?? 0)} note="찬성·강한 찬성으로 답한 사람" />
              <StatTile label="Jev 찬성 쪽 확률" value={pct(cmp.jev_favor ?? 0)} note="같은 사람들의 평균" />
              <StatTile label="차이" value={`${Math.round(((cmp.llm_favor ?? 0) - (cmp.jev_favor ?? 0)) * 100)}%p`} note="LLM − Jev" />
              <StatTile label="상관계수" value={cmp.corr === null || cmp.corr === undefined ? "–" : cmp.corr.toFixed(2)}
                note="사람별 LLM 답과 Jev 기댓값" />
            </div>
          </section>
        )}

        {j.positions && (
          <section className="pp-section">
            <SectionHead title="조항별 찬반 지도"
              desc="조항마다 반대(−1)·중립(0)·찬성(+1) 확률을 물어 기댓값을 칸에 적었습니다. 빨강 쪽일수록 그 집단이 그 조항에 반대할 가능성이 큽니다." />
            <div className="pp-heat-stack">
              <ClauseHeatmap title="연령대" mode="position" segments={segments} overall={positionOverall} groups={j.positions.groups.age_band ?? []} />
              <ClauseHeatmap title="직업군" mode="position" segments={segments} overall={positionOverall} groups={j.positions.groups.occupation_major ?? []} />
            </div>
            <div className="pp-card" style={{ marginTop: 12 }}>
              <h3 className="pp-h3">조항별 반대·중립·찬성 확률(전체 {j.n.toLocaleString()}명)</h3>
              <PositionBars rows={[...segments]
                .map((s) => ({ id: s.id, label: s.label, oppose: j.positions!.overall[s.id]?.oppose ?? 0, support: j.positions!.overall[s.id]?.support ?? 0 }))
                .sort((a, c) => c.oppose - a.oppose || a.support - c.support)} />
            </div>
          </section>
        )}

        <section className="pp-section">
          <SectionHead title="조항별 영향 지도"
            desc="칸의 숫자는 그 집단 사람들이 해당 조항의 직접 영향을 받는다고 Jev가 본 확률의 평균입니다. 인용 기반 쟁점 지도와 달리 모든 사람·모든 조항을 빠짐없이 봅니다." />
          <div className="pp-heat-stack">
            <ClauseHeatmap title="연령대" segments={segments} overall={j.clauses.overall} groups={j.clauses.groups.age_band ?? []} />
            <ClauseHeatmap title="권역" segments={segments} overall={j.clauses.overall} groups={j.clauses.groups.region ?? []} />
            <ClauseHeatmap title="직업군" segments={segments} overall={j.clauses.overall} groups={j.clauses.groups.occupation_major ?? []} />
          </div>
        </section>

        {j.issue_prevalence && (
          <section className="pp-section">
            <SectionHead title="쟁점 확산도"
              desc={`LLM 패널 400명의 반응에서 나온 쟁점을 대표 ${j.n.toLocaleString()}명에게 되물었습니다. 칸의 숫자는 그 집단 사람들이 그 쟁점을 제기할 확률의 평균입니다(한 사람이 여러 쟁점에 공감할 수 있습니다).`} />
            <div className="pp-heat-stack">
              <ClauseHeatmap title="연령대" rowHeader="쟁점" segments={issueRows} overall={j.issue_prevalence.overall} groups={j.issue_prevalence.groups.age_band ?? []} />
              <ClauseHeatmap title="직업군" rowHeader="쟁점" segments={issueRows} overall={j.issue_prevalence.overall} groups={j.issue_prevalence.groups.occupation_major ?? []} />
            </div>
          </section>
        )}

        {j.provinces && j.provinces.length > 0 && (
          <section className="pp-section">
            <SectionHead title="시도별 지도" desc="정량 패널을 사는 곳(시도)으로 묶었습니다. 30명 미만 시도는 해석하지 않습니다." />
            <div className="pp-grid-2">
              <div className="pp-card"><h3 className="pp-h3">직접 영향 확률</h3><TileMap tiles={tiles("direct")} minN={30} mode="share" label="시도별 직접 영향 확률" /></div>
              <div className="pp-card"><h3 className="pp-h3">반대·유보 확률</h3><TileMap tiles={tiles("reserve")} minN={30} mode="share" label="시도별 반대·유보 확률" /></div>
            </div>
            <p className="pp-sub" style={{ marginTop: 12 }}>
              30명 이상인 시도 사이의 차이는 직접 영향 최대 {(spread("direct") * 100).toFixed(1)}%p, 반대·유보 최대 {(spread("reserve") * 100).toFixed(1)}%p입니다.
              색 구간 경계 근처의 작은 차이로 색이 갈릴 수 있으니 칸의 숫자를 함께 봅니다.
            </p>
          </section>
        )}

        <section className="pp-section">
          <SectionHead title="집단별 평균 지지 (Jev)" desc="0을 기준으로 왼쪽은 반대, 오른쪽은 찬성 쪽입니다. 30명 미만 집단은 회색으로 두고 해석하지 않습니다." />
          <div className="pp-grid-2">
            {GROUPS.map(([key, title]) => (
              <MeanRows key={key} title={title} rows={asGroupRows(j.by_group[key] ?? [])} smallNote="회색은 30명 미만이라 해석하지 않습니다." />
            ))}
          </div>
        </section>

        <section className="pp-section">
          <SectionHead title="직접 영향과 참여 가능성"
            desc="직접 영향 확률이 높은데 스스로 의견 낼 확률이 낮은 집단이 ‘찾아가 들어야 할 집단’의 후보입니다." />
          <div className="pp-grid-2">
            <RateTable title="직업군" rows={j.by_group.occupation_major ?? []} />
            <RateTable title="연령대" rows={j.by_group.age_band ?? []} />
          </div>
        </section>

        {j.methods && (
          <section className="pp-section">
            <SectionHead title="참여 방식별 참여 확률"
              desc="여섯 가지 의견수렴 방식 각각에 초대받으면 실제로 참여할 확률입니다. 찾아갈 집단 카드와 계획서의 접촉 방법은 이 숫자를 근거로 삼습니다." />
            <div className="pp-card">
              <h3 className="pp-h3">전체 {j.n.toLocaleString()}명</h3>
              {j.methods.map((m) => <MetricBar key={m.key} label={m.label} value={m.p} wide />)}
            </div>
            <div className="pp-heat-stack" style={{ marginTop: 16 }}>
              <ClauseHeatmap title="연령대" rowHeader="방식" segments={methodRows} overall={methodOverall} groups={j.methods_by_group?.age_band ?? []} />
              <ClauseHeatmap title="직업군" rowHeader="방식" segments={methodRows} overall={methodOverall} groups={j.methods_by_group?.occupation_major ?? []} />
            </div>
          </section>
        )}

        {j.explain && (
          <section className="pp-section">
            <SectionHead title="설명이 필요한 조항"
              desc="의견을 내기 전에 설명이 가장 필요한 조항을 하나씩 고르게 한 확률의 평균입니다. 설명자료와 공청회 순서를 정할 때 씁니다." />
            <div className="pp-grid-2">
              <div className="pp-card">
                <h3 className="pp-h3">가장 설명이 필요한 조항</h3>
                {[...segments].sort((a, c) => (j.explain!.overall[c.id] ?? 0) - (j.explain!.overall[a.id] ?? 0)).map((s) => (
                  <MetricBar key={s.id} label={s.label} value={j.explain!.overall[s.id] ?? 0} wide />
                ))}
              </div>
              <div className="pp-card">
                <h3 className="pp-h3">원문만으로 자기에게 무엇이 바뀌는지 이해할 확률</h3>
                <p className="pp-sub" style={{ margin: "0 0 8px" }}>전체 {pct(j.explain.understand.overall)}</p>
                {j.explain.understand.education_level.filter((g) => !g.small).map((g) => (
                  <MetricBar key={g.group} label={`${g.group}(${g.n.toLocaleString()}명)`} value={g.mean} wide />
                ))}
              </div>
            </div>
          </section>
        )}

        <section className="pp-section">
          <SectionHead title="소식을 접하는 경로" desc="이런 정책 소식을 주로 어디서 접하는지 Jev가 고른 곳의 비율입니다." />
          <div className="pp-card">
            {j.channels.map((c) => (
              <div key={c.key} className="pp-channel-row">
                <span>{c.label}</span>
                <span className="pp-rate-track" aria-hidden="true"><span className="pp-rate-fill" style={{ width: `${(c.share / maxChannel) * 100}%`, display: "block" }} /></span>
                <b className="pp-num" style={{ textAlign: "right" }}>{pct(c.share)}</b>
              </div>
            ))}
          </div>
        </section>

        {b.analysis.alternatives && b.analysis.alternatives.items.length > 0 && (
          <section className="pp-section" id="amendments">
            <SectionHead title="수정안 비교"
              desc="LLM 패널이 낸 보완 제안 가운데 큰 묶음을 AI가 구체적인 수정 문장으로 바꾸고, 같은 사람들에게 원안과 수정안을 각각 물어 변화를 쟀습니다. 판단이 싸고 빨라서 가능한 짝지은 비교입니다." />
            <JevReceipt meta={b.meta} stage="alternatives" />
            <AmendmentCompare alternatives={b.analysis.alternatives} segmentLabel={segLabel} />
            <p className="pp-sub" style={{ marginTop: 12 }}>
              한계: 효과가 날짜·나이 계산에 달린 수정안(예: “2031년부터 시행”)은 Jev가 잘못 읽을 수 있어, 수정 문장에는 누가 어떤 영향을 받는지를 직접 쓰게 했습니다.
            </p>
          </section>
        )}

        {b.analysis.consistency && (
          <section className="pp-section">
            <SectionHead title="LLM 응답 자기모순 점검"
              desc={`Jev가 LLM 패널의 이유 문장만 읽고(찬반 표시는 가린 채) 어떤 태도로 읽히는지 5단계로 판정했습니다. 인물이 스스로 붙인 찬반과 ${b.analysis.consistency.threshold}단계 이상 다르면 개별 응답에 표시합니다.`} />
            <JevReceipt meta={b.meta} stage="issues" tasks={["consistency"]} />
            <ConsistencyPanel consistency={b.analysis.consistency} reactions={ix.reactionByRid} />
          </section>
        )}

        {b.analysis.quality && (
          <section className="pp-section" id="quality">
            <SectionHead title="판정 품질 점검"
              desc="Jev의 판단을 얼마나 믿을 수 있는지 이 사례의 데이터로 쟀습니다. 선택지 순서, 질문 묶음, 같은 호출 반복, 다른 도구(LLM)와의 대조입니다." />
            <JevReceipt meta={b.meta} stage="review" tasks={["order", "batching", "repeat"]} />
            <QualityPanel quality={b.analysis.quality} />
          </section>
        )}

        {ia && (
          <section className="pp-section">
            <SectionHead title="쟁점 소속 판정"
              desc={`쟁점의 이름과 요약은 LLM이 지었고, LLM 패널의 반응 하나하나가 어느 쟁점을 말하는지는 Jev가 골랐습니다. 확률 ${pct(ia.threshold)} 이상일 때만 소속으로 인정하고, 인용문도 확률이 높은 반응부터 고릅니다.${b.analysis.quality ? " 확률은 선택지를 원래 순서와 뒤집은 순서로 물어 평균한 값입니다." : ""}`} />
            <JevReceipt meta={b.meta} stage="issues" tasks={["assign"]} />
            <div className="pp-grid-4">
              <StatTile label="판정한 반응" value={`${ia.reactions}건`} note="LLM 패널 전체" />
              <StatTile label="쟁점에 소속" value={`${b.analysis.quality?.order.assigned ?? ia.jev_assigned}건`}
                note={`확률 ${pct(ia.threshold)} 이상${b.analysis.quality ? " · 두 순서 평균" : ""}`} />
              <StatTile label="어디에도 안 속함" value={`${ia.reactions - (b.analysis.quality?.order.assigned ?? ia.jev_assigned)}건`} note="개별 응답에서 확인" />
              <StatTile label="LLM 묶음과 일치" value={ia.agreement === null ? "–" : pct(ia.agreement)}
                note={`원래 순서 판정 기준, 둘 다 소속을 정한 ${ia.both}건`} />
            </div>
          </section>
        )}

        <section className="pp-section">
          <SectionHead title="실행 정보" desc="이 사례에서 Jev가 한 판정의 수, 속도, 비용입니다." />
          <JevUsageTable meta={b.meta} />
        </section>

        <section className="pp-section">
          <div className="pp-grid-4">
            <StatTile label="1인 1회 호출" value={`${(b.meta.counts.jev_calls ?? 0).toLocaleString()}회`} note={`실패 ${b.meta.counts.jev_failed ?? 0}건`} />
            <StatTile label="모델" value={b.meta.models.jev ?? "jev-latest"} note="TypeSafe System One" />
            <StatTile label="질문 수" value={`${nQuestions}개/인`}
              note={j.positions ? "찬반·영향·참여·경로·조항 영향·조항 찬반·쟁점·방식·설명" : "찬반·영향·참여·경로 + 조항"} />
            <StatTile label="언어" value="한국어 상태" note="질문 문장은 영어(Jev 주 언어)" />
          </div>
          <p className="pp-sub" style={{ marginTop: 12 }}>
            Jev의 확률은 여러 사람을 묶어 볼 때 보정된 값이며, 한 사람의 답이 맞는다는 보장은 아닙니다. 한국어는 영어보다 정확도가 낮을 수
            있어 집단 단위 경향으로만 읽습니다. 출처: docs.typesafe.ai
          </p>
        </section>
      </div>
    </div>
  );
}
