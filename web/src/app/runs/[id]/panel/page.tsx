import type { Metadata } from "next";
import AiNotice from "@/components/AiNotice";
import PersonaCard from "@/components/PersonaCard";
import RunHeader from "@/components/RunHeader";
import SectionHead from "@/components/SectionHead";
import ShareBar from "@/components/ShareBar";
import StatTile from "@/components/StatTile";
import TileMap from "@/components/TileMap";
import { getRun, indexBundle, runParams } from "@/lib/bundles";
import { CHANNEL_LABEL, PROVINCE_DISPLAY, pct } from "@/lib/format";
import type { Persona, Population } from "@/lib/types";
import "./panel.css";

export const dynamicParams = false;
export function generateStaticParams() {
  return runParams();
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `패널·영향권 · ${getRun(id).title}` };
}

type CompareKey = "age_band" | "region" | "sex";
const COMPARE: { title: string; key: CompareKey; order: string[] }[] = [
  { title: "연령대", key: "age_band", order: ["19–29세", "30대", "40대", "50대", "60대", "70세 이상"] },
  { title: "권역", key: "region", order: ["수도권", "충청권", "호남권", "대경권", "동남권", "강원", "제주"] },
  { title: "성별", key: "sex", order: ["남자", "여자"] },
];
const TILE_ORDER = ["서울", "강원", "인천", "경기", "충북", "경북", "충남", "세종", "대전", "대구", "울산", "전북", "경남", "부산", "광주", "전남", "제주"];
const COMBOS = ["속성 조건만", "키워드만", "의미 검색만", "두 경로 이상"];

function describe(group: Record<string, unknown>): string[] {
  const list = (v: unknown) => (Array.isArray(v) ? v.map(String).join("·") : String(v));
  const out: string[] = [];
  if (group.occupation_like) out.push(`직업에 ‘${list(group.occupation_like)}’`);
  if (group.age_min !== undefined || group.age_max !== undefined) out.push(`나이 ${group.age_min ?? ""}~${group.age_max ?? ""}세`);
  if (group.province_in) out.push(`시도 ${(group.province_in as string[]).map((p) => PROVINCE_DISPLAY[p] ?? p).join("·")}`);
  if (group.family_type_like) out.push(`가구에 ‘${list(group.family_type_like)}’`);
  if (group.housing_type_in) out.push(`주거 ${list(group.housing_type_in)}`);
  if (group.education_in) out.push(`학력 ${list(group.education_in)}`);
  if (group.sex) out.push(String(group.sex));
  return out;
}

function combo(found: string[]): string {
  return found.length > 1 ? "두 경로 이상" : `${CHANNEL_LABEL[found[0]]}만`;
}

export default async function PanelPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const b = getRun(id);
  const ix = indexBundle(b);
  const rep = b.personas.filter((p) => p.panel === "rep");
  const aff = b.personas.filter((p) => p.panel === "aff");
  const pop = "total" in b.population ? (b.population as Population) : null;
  const share = (list: Persona[], key: CompareKey, value: string) =>
    list.length ? list.filter((p) => p[key] === value).length / list.length : 0;
  const popShare = (key: CompareKey, value: string) => (pop ? (pop[key][value] ?? 0) / pop.total : null);
  const tiles = TILE_ORDER.map((province) => {
    const supports = rep.filter((p) => p.province === province)
      .map((p) => ix.reactionByUuid.get(p.uuid)?.support)
      .filter((s): s is NonNullable<typeof s> => s !== undefined);
    return { province, n: supports.length, mean: supports.length ? supports.reduce((a: number, s) => a + s, 0) / supports.length : null };
  });
  const combos = new Map<string, number>();
  for (const p of aff) combos.set(combo(p.found_by), (combos.get(combo(p.found_by)) ?? 0) + 1);
  const occupations = (channel: string) => {
    const count = new Map<string, number>();
    for (const p of aff) if ((p.found_by as string[]).includes(channel)) count.set(p.occupation, (count.get(p.occupation) ?? 0) + 1);
    return [...count.entries()].sort((a, c) => c[1] - a[1]).slice(0, 6);
  };
  const semanticOnly = aff.filter((p) => p.found_by.length === 1 && p.found_by[0] === "semantic");
  const spec = b.panel.affected.spec;
  const channels = b.panel.affected.channels;

  return (
    <div>
      <AiNotice />
      <RunHeader bundle={b} active="panel" />
      <div className="pp-container">
        <section className="pp-section pp-grid-3">
          <StatTile label="대표 패널" value={`${rep.length}명`} note="시도×연령대×성별 비례 층화 추출" />
          <StatTile label="영향권 패널" value={`${aff.length}명`} note="대표 패널과 겹치지 않게, 직업은 5명까지" />
          <StatTile label="영향권 후보" value={`${channels.filter + channels.fts + channels.semantic}명`}
            note={`속성 ${channels.filter} · 키워드 ${channels.fts} · 의미 ${channels.semantic}`} />
        </section>

        <section className="pp-section">
          <SectionHead title="대표 패널과 전국 분포"
            desc="막대는 대표 패널 비율, 검은 눈금은 합성 인물 100만 명 전체 비율입니다. 층화 추출이라 대체로 겹쳐야 정상입니다." />
          <div className="pp-grid-3">
            {COMPARE.map((c) => (
              <div key={c.key} className="pp-card">
                <h3 className="pp-h3">{c.title}</h3>
                <div className="pp-compare">
                  {c.order.map((value) => {
                    const mine = share(rep, c.key, value);
                    const all = popShare(c.key, value);
                    return (
                      <div key={value} className="pp-compare-row">
                        <span>{value}</span>
                        <span className="pp-compare-track" role="img" aria-label={`${value}: 패널 ${pct(mine)}${all === null ? "" : `, 전국 ${pct(all)}`}`}>
                          <span className="pp-compare-fill" style={{ width: `${mine * 100}%` }} />
                          {all !== null && <span className="pp-compare-tick" style={{ left: `calc(${all * 100}% - 1px)` }} />}
                        </span>
                        <span className="pp-compare-val">{pct(mine)}{all !== null && <> · 전국 {pct(all)}</>}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          <ul className="pp-legend">
            <li><span className="pp-swatch" style={{ background: "#256ef4" }} />대표 패널</li>
            <li><span className="pp-tick-swatch" />전국(합성 인물 100만 명)</li>
          </ul>
        </section>

        <section className="pp-section">
          <SectionHead title="시도별 대표 패널 평균 지지"
            desc="인구 비율대로 뽑았기 때문에 작은 시도는 인원이 적습니다. 5명 미만인 시도는 평균을 해석하지 않습니다." />
          <div className="pp-card pp-map-wrap">
            <TileMap tiles={tiles} />
            <div className="pp-sub" style={{ margin: 0 }}>
              <p>칸 안의 숫자는 평균 지지(−2~+2)와 인원입니다. 권역 차이를 볼 때는 결과 요약의 ‘집단별 평균 지지’(권역)가 표본이 커서 더 안정적입니다.</p>
            </div>
          </div>
        </section>

        <section className="pp-section">
          <SectionHead title="영향권 탐색" desc="정책문을 읽고 AI가 만든 표적 명세로 세 경로에서 후보를 찾은 뒤, 직업과 지역이 쏠리지 않게 골랐습니다." />
          <div className="pp-grid-2">
            <div className="pp-card pp-spec">
              <h3 className="pp-h3">표적 명세<span className="pp-tag-ai">AI 작성</span></h3>
              <dl>
                <dt>속성 조건</dt>
                <dd>
                  {spec.filters.length === 0 ? "없음" : (
                    <ol className="pp-spec-groups">{spec.filters.map((g, i) => <li key={i}>{describe(g).join(" 그리고 ")}</li>)}</ol>
                  )}
                </dd>
                <dt>키워드</dt>
                <dd className="pp-chips">
                  {spec.keywords.map((k) => <span key={k} className={`pp-chip${k.length < 3 ? "" : " is-primary"}`}>{k}{k.length < 3 && " (2글자라 제외)"}</span>)}
                </dd>
                <dt>의미 검색 질의</dt>
                <dd>{spec.semantic_query ? `“${spec.semantic_query}”` : "없음"}</dd>
                <dt>근거</dt>
                <dd>{spec.rationale}</dd>
                {b.panel.affected.semantic_note && (<><dt>이름 편향 보정</dt><dd>{b.panel.affected.semantic_note}</dd></>)}
              </dl>
            </div>
            <div className="pp-card pp-occ">
              <h3 className="pp-h3">경로별로 찾은 사람</h3>
              <div className="pp-combos">
                {COMBOS.map((label) => (
                  <div key={label}>
                    <div className="pp-combo-label">{label}</div>
                    <ShareBar share={aff.length ? (combos.get(label) ?? 0) / aff.length : 0} label={`${combos.get(label) ?? 0}명`} />
                  </div>
                ))}
              </div>
              {(["filter", "fts", "semantic"] as const).map((channel) => (
                <div key={channel}>
                  <h4>{CHANNEL_LABEL[channel]}로 찾은 직업</h4>
                  <div className="pp-chips">
                    {occupations(channel).length === 0 ? <span className="pp-sub">없음</span> :
                      occupations(channel).map(([occ, n]) => <span key={occ} className="pp-chip">{occ} {n}</span>)}
                  </div>
                </div>
              ))}
            </div>
          </div>
          {b.meta.fallbacks.length > 0 && <ul className="pp-fallbacks">{b.meta.fallbacks.map((f) => <li key={f}>{f}</li>)}</ul>}
        </section>

        {semanticOnly.length > 0 && (
          <section className="pp-section">
            <SectionHead title="의미 검색만 찾아낸 인물"
              desc="속성 조건과 키워드로는 잡히지 않았지만 정책문과 삶의 맥락이 가까운 사람들입니다. 놓칠 뻔한 집단의 단서로 봅니다." />
            <div className="pp-grid-3">
              {semanticOnly.slice(0, 6).map((p) => (
                <PersonaCard key={p.uuid} person={p} reaction={ix.reactionByUuid.get(p.uuid)!} />
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
