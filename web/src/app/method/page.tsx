import type { Metadata } from "next";
import SectionHead from "@/components/SectionHead";
import { STAGES } from "@/lib/format";
import "./method.css";

export const metadata: Metadata = { title: "한계와 방법" };

const LIMITS = [
  { title: "합의를 부풀립니다",
    body: "상용 AI 여론 시뮬레이션의 공개 결과(2026. 8. 25., ‘102개 기관 해킹 재발 방지 대응책’, 100명)에서 100명 전원이 같은 선택지를 골랐습니다. 같은 서비스의 자체 비교에서도 실제 여론 69.3%가 부정적인 사안을 AI는 95% 부정으로 답했습니다." },
  { title: "중도로 몰립니다",
    body: "Nemotron 한국인 페르소나 8만여 명에게 9Axes 정치 성향 문항을 풀게 한 공개 실험에서 대부분의 축이 중도 구간에 몰렸습니다." },
  { title: "데이터의 빈칸",
    body: "Nemotron-Personas-Korea는 19세 이상만 포함하고 소득 정보가 없습니다. 세부 직업 배정 등 일부 변수는 서로 독립이라고 가정해 만들어졌습니다." },
  { title: "이름에 끌리는 검색",
    body: "인물 서술에 이름이 반복되어 임베딩 유사도가 이름에 끌립니다(임베딩 공개자 지적). 그래서 상위 1,000명을 이름을 지운 서술로 다시 임베딩해 300명으로 줄이고, 의미 검색 결과는 단서로만 씁니다." },
  { title: "Jev도 합성 인물에 대한 판단입니다",
    body: "Jev의 확률은 합성 인물의 서술을 읽고 낸 보정된 판단이지 실제 사람의 응답이 아닙니다. 보정은 여러 사람을 묶어 볼 때의 성질이고, 한국어는 영어보다 정확도가 낮을 수 있어 집단 단위 경향으로만 읽습니다." },
  { title: "수정안 비교는 계산에 약합니다",
    body: "효과가 날짜·나이 계산에 달린 수정안(예: “2031년부터 시행”)은 Jev가 거꾸로 읽은 적이 있습니다. 그래서 수정 문장에는 누가 어떤 영향을 받는지를 직접 쓰게 하고, 내용 없는 대조 문장의 변화를 빼서 순효과를 봅니다." },
  { title: "뻔한 정책에서는 고정관념",
    body: "이전 실험에서 쟁점이 뻔한 정책은 인구통계만 줘도 같은 결과가 나왔습니다. 인물 서술이 값어치를 하는 것은 이해관계가 교차하는 정책입니다." },
];

const SOURCES: [string, string, string, string][] = [
  ["NVIDIA Nemotron-Personas-Korea", "합성 인물 100만 명(26개 필드, 17개 시도·252개 시군구)", "CC BY 4.0", "https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea"],
  ["intfloat/multilingual-e5-large", "의미 검색 기본값(1024차원). 인물 벡터는 원문에서 새로 계산 필요. 기존 공개 예시는 이전 검색 구성으로 만든 보관 결과", "모델 MIT · 인물 CC BY 4.0", "https://huggingface.co/intfloat/multilingual-e5-large"],
  ["civilian7/korean-people-persona", "SQLite·FTS5 변환 도구(외부 도구로만 사용)", "명시 없음", "https://github.com/civilian7/korean-people-persona"],
  ["hongsw/harness", "한국어 화법 어댑터·다관점 리뷰 아이디어", "—", "https://github.com/hongsw/harness"],
  ["TypeSafe Jev (System One)", "보정된 확률로 답하는 판단 모델 — 정량 점검 5,000명·쟁점 소속·자기모순 점검·수정안 비교·정책문 점검·관점 태그·발언 읽기·직업 분류", "API 이용", "https://docs.typesafe.ai"],
  ["Jev 활용 사례 모음", "여러 지표 채점·판정 품질 검증·자동 태깅·판정 캐시 같은 활용 패턴 참고(jev-lab.com, awesomejev.com, jevable.com, madewithjev.com)", "참고", "https://awesomejev.com"],
  ["KRDS HTML Component Kit 1.1.0", "정부 디자인 시스템 CSS·폰트·아이콘", "KRDS 이용약관", "https://www.krds.go.kr"],
  ["국민참여입법센터", "생명안전기본법 시행령 제정안 입법예고 원문", "공개 자료", "https://opinion.lawmaking.go.kr/gcom/ogLmPp/88826"],
];

export default function MethodPage() {
  return (
    <div className="pp-container pp-page">
      <h1 className="pp-h1">한계와 방법</h1>
      <p className="pp-lead">
        백번 미리 묻다는 합성 인물 패널의 반응으로 실제 의견수렴을 설계하는 시제품입니다. 찬성률을 맞히려는 도구가 아니라, 누가
        영향을 받고 어떤 쟁점이 어느 조항에서 나오는지, 누구를 찾아가 들어야 하는지를 넓게 훑는 도구입니다.
      </p>

      <section className="pp-section">
        <SectionHead title="절차" />
        <ol className="pp-steps-row">
          {STAGES.map((s) => (
            <li key={s.key}><div className="pp-card"><b>{s.title}</b><p>{s.desc}</p></div></li>
          ))}
        </ol>
      </section>

      <section className="pp-section">
        <SectionHead title="두 가지 AI를 나눠 씁니다" />
        <div className="pp-grid-2">
          <div className="pp-card">
            <h3 className="pp-h3">LLM — 목소리</h3>
            <ul className="pp-bullets">
              <li>대표 300명·영향권 100명이 각자의 말투로 이유를 말하고, 반응한 정책 문구를 원문에서 인용합니다.</li>
              <li>쟁점의 이름과 요약, 보완 제안 묶기, 가상 공청회 발언, 계획서 문장을 씁니다.</li>
              <li>한 사람당 답을 하나만 뽑기 때문에, 같은 사람들에게 Jev가 준 확률보다 한쪽으로 쏠리는 경향이 있습니다(사례마다 정량 점검 화면에서 비교).</li>
            </ul>
          </div>
          <div className="pp-card">
            <h3 className="pp-h3">Jev — 숫자</h3>
            <ul className="pp-bullets">
              <li>문장을 쓰지 않고 정해 둔 질문에 보정된 확률로 답하는 판단 모델입니다(한 번에 0.3초 안팎).</li>
              <li>5,000명에게 찬반, 직접 영향, 조항별 영향, 참여 가능성, 소식 경로를 묻고, 찾아가 들어야 할 집단을 이 확률로 고릅니다.</li>
              <li>한 사람에게 필요한 판단(찬반, 직접 영향, 조항별 영향·찬반, 쟁점 공감, 참여 방식 여섯 가지, 설명이 필요한 조항)을 한 번의 호출로 묻습니다. 질문을 10개에서 31개로 늘려도 0.3~1.3초로 같고, 늘어나는 것은 입력 토큰(비용)뿐입니다.</li>
              <li>LLM 패널의 반응 하나하나가 어느 쟁점을 말하는지 판정합니다. 확률 50% 이상만 소속으로 인정하고, 쟁점 아래 인용문도 이 확률이 높은 반응부터 고릅니다.</li>
              <li>LLM 응답의 이유 문장만 읽고 어떤 태도로 읽히는지 판정해, 인물이 스스로 붙인 찬반과 크게 어긋나는 답을 표시합니다.</li>
              <li>보완 제안 큰 묶음을 AI가 수정 문장으로 바꾸면, 같은 1,500명에게 원안·수정안·내용 없는 대조 문장을 각각 물어 수정안의 순효과를 잽니다.</li>
              <li>계획서의 예상 질문은 AI가 쓰고, 정량 패널 600명에게 “이 질문의 답을 듣고 싶은가”를 물어 먼저 준비할 순서와 주로 묻는 집단을 정합니다.</li>
              <li>의견을 묻기 전에 정책문을 점검합니다. 조항마다 어려운 용어·대상 모호·기준 누락 등 8가지 문제, 안내문 전체에는 의견 제출 방법·비용 추계 등 6가지 안내가 있는지를 확률로 봅니다.</li>
              <li>반응마다 ‘생계·비용 부담’, ‘형평성’, ‘정보 부족’ 같은 관점 12가지를 붙여, 쟁점 묶음과 다른 축으로 거를 수 있게 합니다.</li>
              <li>AI가 쓴 공청회 회의록을 발언 하나씩 읽어, 참석자의 태도가 라운드마다 어떻게 움직였는지와 반박·입장 완화·제안을 표시합니다.</li>
              <li>자기 판단도 점검합니다. 선택지 순서를 뒤집어 다시 묻고(쟁점 소속은 두 순서를 평균), 질문을 따로 물은 답과 묶어 물은 답, 같은 호출의 반복, 직업 분류의 LLM 대조를 사례마다 공개합니다.</li>
              <li>같은 질문은 저장해 둔 답을 다시 씁니다(캐시). 다시 계산해도 이미 산 판단에는 비용이 들지 않습니다.</li>
              <li>LLM 패널과 같은 사람에게도 물어, 두 도구의 찬반을 나란히 비교합니다.</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="pp-section pp-grid-2">
        <div className="pp-card">
          <h2 className="pp-h3">대표 패널 300명</h2>
          <ul className="pp-bullets">
            <li>합성 인물 100만 명을 시도×연령대(6구간)×성별로 나누고, 인구 비율대로 자리를 나눠(최대잉여법) 무작위로 뽑습니다.</li>
            <li>전체 찬반과 집단별 평균은 이 패널로만 계산합니다.</li>
            <li>10명 미만 집단, 5명 미만 시도는 해석하지 않습니다.</li>
          </ul>
        </div>
        <div className="pp-card">
          <h2 className="pp-h3">영향권 패널 최대 100명</h2>
          <ul className="pp-bullets">
            <li>AI가 정책문을 읽고 표적 명세(속성 조건·키워드·의미 검색 질의)를 만듭니다.</li>
            <li>속성 조건은 SQL로, 키워드는 FTS5 전문 검색으로(3글자 이상만 동작), 의미 검색은 인물 임베딩과 질의 임베딩의 코사인 유사도로 찾은 뒤 이름을 지운 서술로 다시 순위를 매깁니다.</li>
            <li>대표 패널과 겹치는 사람을 빼고, 같은 직업은 5명까지, 권역·연령대를 돌아가며 고릅니다.</li>
          </ul>
        </div>
      </section>

      <section className="pp-section">
        <SectionHead title="정직성 장치" />
        <ul className="pp-bullets">
          <li>모든 결과 화면 위에 “합성 인물(AI)의 반응이며 실제 여론이 아님”을 항상 띄웁니다.</li>
          <li>숫자는 코드가 계산하고, 화면의 발언은 AI 인물의 응답을 코드가 그대로 복사합니다. AI가 쓴 요약·제안에는 ‘AI 작성’, AI가 추정한 값에는 ‘AI 추정’을 붙입니다.</li>
          <li>인물이 반응한 문구는 원문에 글자 그대로 있을 때만 조항에 매깁니다. 맞지 않은 인용 건수를 공개합니다.</li>
          <li>번들을 내보낼 때 인용·참조 무결성을 검사하고, 개발용 모의 결과는 공개 사이트에 올리지 않습니다.</li>
          <li>찬반 수치는 LLM의 한 번 답과 Jev의 확률을 같은 사람 기준으로 나란히 보여줘, 한쪽으로 쏠렸는지 드러냅니다.</li>
          <li>반응은 인물마다 따로 호출해 서로 영향을 주지 않게 했고, 사용자 설정이 섞이지 않도록 LLM 호출에서 도구·설정을 모두 껐습니다.</li>
        </ul>
      </section>

      <section className="pp-section">
        <SectionHead title="알려진 한계" />
        <div className="pp-grid-2">
          {LIMITS.map((l) => (
            <div key={l.title} className="pp-card-soft pp-limit"><h3 className="pp-h3">{l.title}</h3><p>{l.body}</p></div>
          ))}
        </div>
      </section>

      <section className="pp-section">
        <SectionHead title="데이터·도구 출처" />
        <div className="pp-table-wrap">
          <table className="pp-table">
            <thead><tr><th>이름</th><th>쓰임</th><th>라이선스</th><th>주소</th></tr></thead>
            <tbody>
              {SOURCES.map(([name, use, license, url]) => (
                <tr key={name}><td>{name}</td><td>{use}</td><td>{license}</td><td><a href={url} target="_blank" rel="noreferrer">{url.replace("https://", "")}</a></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="pp-section">
        <SectionHead title="로컬에서 새 정책 실행하기" desc="시제품의 화면은 미리 실행한 결과를 보여줍니다. 새 정책은 로컬 엔진에서 돌립니다(README의 데이터 준비 필요)." />
        <pre className="pp-code">{`cd engine
# policies/새정책.json: {"id", "title", "kind", "agency", "source": {...}, "text"}
../.venv/bin/python -m pp run policies/새정책.json   # 정책 하나에 10분 안팎, 문장 모델은 PP_LLM_PROVIDER로 고름
cd ../web && npm run build                            # 결과가 사이트에 추가됩니다`}</pre>
      </section>
    </div>
  );
}
