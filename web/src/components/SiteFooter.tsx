import Link from "next/link";

export default function SiteFooter() {
  return (
    <footer className="pp-footer">
      <div className="pp-container pp-footer-in">
        <div>
          <p className="pp-footer-title">백번 미리 묻다 (시제품)</p>
          <p>
            합성 인물로 의견수렴을 미리 설계해 보는 시제품(POC)입니다. 정부 공식 서비스가 아니며, 화면의 반응은 실제 여론이
            아닙니다.
          </p>
          <p className="pp-footer-credits">
            데이터 NVIDIA Nemotron-Personas-Korea(CC BY 4.0) · 의미 검색 기본값 intfloat/multilingual-e5-large(MIT, 인물 벡터 새로 계산 필요) ·
            검색 DB civilian7/korean-people-persona · 화법·다관점 아이디어 hongsw/harness · 판단 모델 TypeSafe Jev · Upstage Solar Decide · tev1(로컬) · 문장 모델 Claude · LG EXAONE · Gemma(로컬) · 지도 경계 국토교통부 행정구역도(공공누리 제1유형) · 공공 통계 출처는 data/SOURCES.md · 디자인 KRDS
          </p>
        </div>
        <nav className="pp-footer-nav" aria-label="바닥글 메뉴">
          <Link href="/explore/">사례</Link>
          <Link href="/series/housing/map/">100만 명</Link>
          <Link href="/method/">한계와 방법</Link>
        </nav>
      </div>
    </footer>
  );
}
