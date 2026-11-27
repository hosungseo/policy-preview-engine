import Link from "next/link";
import { dateKo, duration } from "@/lib/format";
import type { Bundle } from "@/lib/types";
import KindBadge from "./KindBadge";
import "./components.css";

const TABS = [
  { key: "summary", path: "", label: "결과 요약" },
  { key: "jev", path: "jev/", label: "정량 점검(Jev)" },
  { key: "text", path: "text/", label: "정책문 쟁점 지도" },
  { key: "panel", path: "panel/", label: "패널·영향권" },
  { key: "hearing", path: "hearing/", label: "가상 공청회" },
  { key: "plan", path: "plan/", label: "의견수렴 계획서" },
];

export default function RunHeader({ bundle, active }: { bundle: Bundle; active: string }) {
  const seconds = bundle.meta.stages.reduce((sum, s) => sum + s.seconds, 0);
  return (
    <div className="pp-container pp-run-head">
      <nav className="krds-breadcrumb-wrap pp-crumbs" aria-label="현재 경로">
        <ol className="breadcrumb">
          <li className="home"><Link href="/" className="txt">홈</Link></li>
          <li><Link href="/explore/" className="txt">사례</Link></li>
          <li><span className="txt">{bundle.title}</span></li>
        </ol>
      </nav>
      <div className="pp-run-kind">
        <KindBadge kind={bundle.kind} />
        {bundle.agency && <span className="pp-sub">{bundle.agency}</span>}
      </div>
      <h1 className="pp-h1">{bundle.title}</h1>
      <ul className="pp-meta">
        <li>대표 패널 <b>{bundle.analysis.overall.n}명</b></li>
        <li>영향권 패널 <b>{bundle.analysis.overall_aff.n}명</b></li>
        <li>실행 <b>{dateKo(bundle.meta.created_at)}</b></li>
        <li>생성 시간 <b>{duration(seconds)}</b></li>
        <li>모델 <b>{bundle.meta.models.react} · {bundle.meta.models.synth}</b></li>
        {bundle.meta.provider === "mock" && <li><b style={{ color: "#ab2b36" }}>개발용 모의 결과(배포 안 함)</b></li>}
      </ul>
      <p className="pp-run-source">
        {bundle.source.period && <>의견제출 기간 {bundle.source.period} · </>}
        {bundle.source.note}
        {bundle.source.url && (
          <> · <a href={bundle.source.url} target="_blank" rel="noreferrer">원문 보기</a></>
        )}
      </p>
      <nav className="pp-run-nav" aria-label="결과 화면">
        <ul>
          {TABS.map((tab) => (
            <li key={tab.key}>
              <Link href={`/runs/${bundle.id}/${tab.path}`} aria-current={tab.key === active ? "page" : undefined}>
                {tab.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
