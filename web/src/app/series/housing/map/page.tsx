import type { Metadata } from "next";
import Link from "next/link";
import MillionMap from "@/components/map/MillionMap";
import { peopleKo } from "@/lib/format";
import { getSeries } from "@/lib/series";
import "../series.css";

export const metadata: Metadata = { title: "100만 명 지도 · 부동산 대책 흐름" };

export default function PeopleMap() {
  const s = getSeries("housing");
  const n = s ? peopleKo(s.panel.n) : "1만 명";
  return (
    <div className="pp-container pp-page">
      <nav className="krds-breadcrumb-wrap pp-crumbs" aria-label="현재 경로">
        <ol className="breadcrumb">
          <li className="home"><Link href="/" className="txt">홈</Link></li>
          <li><Link href="/series/housing/" className="txt">부동산 대책 흐름</Link></li>
          <li><span className="txt">100만 명 지도</span></li>
        </ol>
      </nav>
      <h1 className="pp-h1">100만 명 지도</h1>
      <p className="pp-lead">한국인 합성 인물 100만 명이 점 하나씩입니다. 그중 지역·나이·성별 비율대로 뽑은 {n}이 현 정부 부동산 대책 {s?.measures.length ?? 10}건에 답했습니다. 판단 모델 Jev의 확률 추정입니다.</p>
      <div className="pp-series-caution">
        <ul>
          <li>인물은 NVIDIA Nemotron-Personas-Korea(CC BY 4.0)의 합성 인물을 이 프로젝트가 뽑고 줄여 보인 것이고, 답은 AI가 추정한 확률입니다. 실제 여론이 아닙니다.</li>
          <li>인물 카드의 가구는 원자료의 가구 구성(함께 사는 사람)입니다. &lsquo;(한부모)&rsquo; 표기도 한부모가족 지원 대상인지를 뜻하지 않습니다.</li>
          <li>점의 위치는 시군구까지만 실제입니다. 시군구 안에서는 읍면동 넓이에 맞춰 흩었습니다.</li>
          <li>경계: 국토교통부 행정구역도(브이월드, 2026-04-23 기준, 단순화), 공공누리 제1유형(출처표시).</li>
          <li>숫자는 &lsquo;대책만&rsquo;(그 대책만 보고 답한 값)입니다. 누적 맥락과 집단별 표는 <Link href="/series/housing/">부동산 대책 흐름</Link>에 있습니다.</li>
        </ul>
      </div>
      <MillionMap />
    </div>
  );
}
