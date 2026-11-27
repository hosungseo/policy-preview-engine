import Link from "next/link";
import RunCard from "@/components/RunCard";
import SectionHead from "@/components/SectionHead";
import AskBox from "@/components/home/AskBox";
import { listRuns } from "@/lib/bundles";
import "./home.css";

// What officials use today, and what asking beforehand adds to each. "Doing nothing" is an alternative too.
const NOW = [
  { way: "의견란", gap: "스스로 찾아와야 닿는 창구", now: "정책안이 나온 뒤에 열려, 평소 글을 쓰던 분들의 의견부터 모입니다.", pre: "글을 잘 남기지 않는 집단이 누구이고 어디에 사는지부터 살핍니다." },
  { way: "공청회·간담회", gap: "경험에 기대어 모시는 자리", now: "참석할 여건이 되는 분들이 오고, 모실 분은 경험에 기대어 정합니다.", pre: "전체와 생각이 다른 집단을 근거로 먼저 만날 분들을 추립니다." },
  { way: "여론조사", gap: "고쳐 가며 묻기 어려운 여건", now: "문안을 고칠 때마다 다시 조사하기엔 시간과 예산 부담이 큽니다.", pre: "표현을 바꿔 여러 번 물어본 뒤 꼭 필요한 질문만 조사합니다." },
  { way: "묻지 않고 진행", gap: "현장에 나간 뒤에야 마주하는 반응", now: "현장 면담이나 공청회를 연 뒤에야 예상하지 못한 쟁점을 처음 마주합니다.", pre: "공개·가상 문안으로 어떤 질문과 대상을 먼저 챙길지 미리 정리합니다." },
];

// Share who did each in the past year. 한국행정연구원 「사회통합실태조사」 2025, age 19+, via 국가지표체계.
const SPOKE = { pct: 9.9, online: 10.6, minwon: 8.5, href: "https://www.index.go.kr/unity/potal/eNara/sub/showStblGams3.do?stts_cd=F025301&idx_cd=F0253&freq=Y&period=N" };

// Example questions about the sample policies in engine/policies (two of them are fictional drafts).
const EXAMPLES = [
  { label: "도시철도 무임승차(가상)", question: "도시철도 무임승차 기준 연령을 2035년까지 70세로 단계적으로 올리는 데 찬성하십니까?" },
  { label: "농어촌 기본소득", question: "농어촌 인구감소지역 주민에게 기본소득을 지급하는 시범사업을 넓히는 데 찬성하십니까?" },
];

export default function Home() {
  const runs = listRuns();

  return (
    <div className="pp-landing">
      <section className="pp-hero">
        <div className="pp-container pp-hero-layout">
          <div className="pp-hero-copy">
            <h1 className="pp-hero-title"><span>백번 미리 묻기,</span> <span>현장 질문 미리 설계.</span></h1>
            <p className="pp-hero-lead">
              현장에 나가기 전에 공개·가상 문안으로 합성 인물 <span className="pp-nowrap">100만 명에게</span> <span className="pp-nowrap">미리 묻고,</span> <span className="pp-nowrap">먼저 만날 사람과</span> 만날 곳까지 정리해 봅니다.
            </p>
            <AskBox examples={EXAMPLES} />
            <p className="pp-hero-note">실제 사람 응답 0명 · 합성 인물의 모의 탐색이며 실제 여론조사가 아닙니다. 합성 인물은 실존 인물이 아니며, 발표 전 비공개 문안은 입력하지 마세요.</p>
          </div>
        </div>
      </section>

      <section className="pp-sec pp-now">
        <div className="pp-container">
          <div className="pp-cols pp-split-head">
            <div className="pp-now-say">
              <h2 className="pp-head"><span>의견을 내는 국민은 100명 중 10명,</span> <span>남은 90명은 찾아가야 들립니다</span></h2>
              <p className="pp-now-cap">지난 1년 동안 정부나 언론에 의견을 낸 적이 있는 사람은 {SPOKE.pct}%입니다. 온라인에 의견을 쓴 사람은 {SPOKE.online}%, 공무원·정치인에게 민원을 전한 사람은 {SPOKE.minwon}%입니다.</p>
              <p className="pp-now-src">한국행정연구원 <a href={SPOKE.href} target="_blank" rel="noreferrer">사회통합실태조사</a> 2025년, 19세 이상</p>
            </div>
            <div className="pp-now-figure">
              <div className="pp-now-dots" role="img" aria-label="점 100개 가운데 10개가 칠해져 있습니다">
                {Array.from({ length: 100 }, (_, i) => <span key={i} className={i < Math.round(SPOKE.pct) ? "is-on" : undefined} />)}
              </div>
              <ul className="pp-now-legend">
                <li className="is-on"><b>10명</b>정부·언론에 의견 제시</li>
                <li><b>90명</b>의견을 내지 않은 사람</li>
              </ul>
            </div>
          </div>
          <ul className="pp-now-rows">
            {NOW.map((r) => (
              <li key={r.way}>
                <h3 className="pp-h3">{r.way}</h3>
                <p className="pp-now-gap">{r.gap}</p>
                <dl>
                  <div><dt>지금</dt><dd>{r.now}</dd></div>
                  <div className="is-do"><dt>미리 물으면</dt><dd>{r.pre}</dd></div>
                </dl>
              </li>
            ))}
          </ul>
          <p className="pp-now-foot">기존 절차를 대신하지 않습니다. 현장에 나가기 전에 어디로 가서 누구를 먼저 만날지 정해 둡니다.</p>
        </div>
      </section>

      <section className="pp-sec pp-band pp-data">
        <div className="pp-container">
          <div className="pp-cols pp-split-head">
            <h2 className="pp-head">합성 국민 <span className="pp-nowrap">100만 명에게</span> 묻습니다</h2>
            <p className="pp-lead">
              기본 설정은 시간과 비용을 줄이려고 그 가운데 인구 비율대로 뽑은 2만 명 묶음에서 응답자를 고릅니다.
              시군구마다 평균 4천 명쯤이라 동네 단위로 짚을 수 있습니다.
            </p>
          </div>
          <dl className="pp-figures">
            <div><dt>묻는 대상</dt><dd>100<small>만 명</small></dd><dd className="pp-figure-note">공공 통계 분포로 만든 합성 인물</dd></div>
            <div><dt>사는 곳</dt><dd>252<small>곳</small></dd><dd className="pp-figure-note">17개 시도의 시군구</dd></div>
            <div><dt>기본 실행</dt><dd>2<small>만 명</small></dd><dd className="pp-figure-note">100만 명에서 인구 비율대로</dd></div>
          </dl>
          <div className="pp-data-foot">
            <p className="pp-sub">
              명단은 NVIDIA Nemotron-Personas-Korea입니다(CC BY 4.0). 통계청·대법원·국민건강보험공단 등의 공공 통계 분포로 만든 합성 인물이며
              실존 인물이 아닙니다. 19세 이상만 있습니다.
            </p>
            <Link href="/series/housing/map/" className="krds-btn medium tertiary">100만 명 지도 보기</Link>
          </div>
        </div>
      </section>

      <section className="pp-band pp-why">
        <div className="pp-container">
          <h2 className="pp-head">묻는 일은 AI에게, 만나는 일은 사람에게</h2>
          <div className="pp-why-body">
            <p>
              묻는 일은 점점 쉬워집니다. 누구나 곁에 자기 AI를 두게 되는 날에는, 질문 하나가 지금보다 훨씬 정확하게 한 사람 한 사람에게
              닿을 것입니다. 그럴수록 직접 찾아가 마주 앉는 시간은 더 귀해집니다. 아직 그날은 오지 않았으니, 지금은 통계로 만든
              합성 인물에게 먼저 물어봅니다.
            </p>
            <p>
              정책도 펴기 전에 여러 번 돌려 볼 수 있습니다. 백 번 미리 묻는 까닭은, 한 번을 제대로 만나기 위해서입니다.
            </p>
          </div>
        </div>
      </section>

      <section className="pp-sec pp-honest">
        <div className="pp-container">
          <div className="pp-cols pp-split-head">
            <h2 className="pp-head">기존 AI 여론 시뮬레이션과 다른 점</h2>
            <p className="pp-lead">찬반 비율을 결론으로 내놓지 않습니다. 답변이 흔들리는 폭을 먼저 재고, 그 폭을 넘는 차이만 찾아갈 곳으로 추립니다.</p>
          </div>
          <div className="pp-cols pp-honest-row">
            <h3 className="pp-h3">AI가 만든 응답은 합의를 부풀리기 쉽습니다</h3>
            <ul>
              <li>합성 응답은 한쪽 선택지나 ‘중도’로 쏠리기 쉽습니다.</li>
              <li>같은 질문도 문장과 선택지 순서에 따라 답이 흔들립니다.</li>
            </ul>
          </div>
          <div className="pp-cols pp-honest-row">
            <h3 className="pp-h3">그래서 「백번 미리 묻다」는 이렇게 씁니다</h3>
            <ul>
              <li>찬반 비율은 기본 화면에서 숨기고 참고용 내부 지표로만 두어, 여론 수치로 오인되지 않게 합니다.</li>
              <li>문장을 바꾸거나 선택지 순서를 뒤집은 질문을 함께 던져 답변이 흔들리는 폭을 잽니다.</li>
              <li>흔들리는 폭을 넘어선 뚜렷한 차이만 「찾아갈 곳」 카드로 만듭니다.</li>
              <li>최종 결론은 현장에서 국민을 실제로 만나 들은 말로 내립니다.</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="pp-sec pp-faq">
        <div className="pp-container pp-cols">
          <div className="pp-faq-head">
            <h2 className="pp-head">물어보기 전에,<br />이것부터 답합니다</h2>
            <p>합성 응답을 실제 여론으로 오인하지 않도록, 쓰는 방법과 한계를 먼저 묶었습니다.</p>
          </div>
          <div className="pp-faq-list">
            <details open>
              <summary>실제 여론조사나 공청회를 대신하나요?</summary>
              <p>아닙니다. 실제 사람 응답 0명이며, 공개·가상 문안을 바탕으로 실제 조사와 현장 만남에서 먼저 확인할 사람과 질문을 고르는 데 씁니다. 발표 전 비공개 문안은 넣지 마시고, 최종 결론은 국민을 직접 만나 들은 말로 내립니다.</p>
            </details>
            <details>
              <summary>ChatGPT에 한 번 묻는 것과 무엇이 다른가요?</summary>
              <p>100만 명 명단에서 인구 비율대로 사람을 뽑고, 문장과 선택지 순서를 바꾼 질문도 함께 던집니다. 한 번 나온 답보다 답이 흔들리는 폭을 먼저 확인합니다.</p>
            </details>
            <details>
              <summary>왜 찬반 비율보다 먼저 만날 사람을 보여 주나요?</summary>
              <p>전체 비율만으로는 어느 집단이 왜 다르게 받아들이는지 알기 어렵습니다. 전체와 뚜렷하게 다르게 답한 집단을 찾아 후속 질문과 현장 만남으로 이어지게 하기 위해서입니다.</p>
            </details>
            <details>
              <summary>합성 명단에 없는 사람은 어떻게 하나요?</summary>
              <p>AI에게 묻지 않습니다. 명단에 없는 당사자가 있으면 결과 화면이 이를 먼저 알리고, 가족센터나 다국어 상담 창구처럼 실제로 만날 경로를 제시합니다.</p>
            </details>
          </div>
        </div>
      </section>

      <section className="pp-sec pp-cases">
        <div className="pp-container">
          <SectionHead title="문안 전체를 깊게 읽은 사례" desc="조항마다 쟁점이 어디에 몰리는지, 합성 인물이 저마다의 말로 반응한 결과입니다."
            right={<span className="pp-home-actions"><Link href="/series/housing/" className="krds-btn medium tertiary">부동산 대책 흐름</Link><Link href="/explore/" className="krds-btn medium tertiary">전체 보기</Link></span>} />
          <div className="pp-grid-3">
            {runs.slice(0, 3).map((run) => <RunCard key={run.id} run={run} />)}
          </div>
        </div>
      </section>

      <section className="pp-sec pp-sec-l pp-cta">
        <div className="pp-container pp-cta-in">
          <div>
            <h2>백번 미리 묻고, 한 번 제대로 만납니다</h2>
            <p>문안과 질문 하나면 됩니다. 합성 인물에게 묻는 일이라 누구에게도 부담을 주지 않고, 문장을 고쳐 몇 번이든 다시 물을 수 있습니다.</p>
          </div>
          <div className="pp-cta-actions">
            <Link href="/explore/" className="krds-btn large tertiary">사례 먼저 보기</Link>
            <Link href="/review/new/" className="krds-btn large primary">질문 넣어 보기</Link>
          </div>
        </div>
      </section>
    </div>
  );
}
