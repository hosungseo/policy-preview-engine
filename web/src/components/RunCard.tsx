import Link from "next/link";
import { dateKo, duration } from "@/lib/format";
import type { RunSummary } from "@/lib/types";
import KindBadge from "./KindBadge";
import "./components.css";
import "./runcard.css";

export default function RunCard({ run }: { run: RunSummary }) {
  return (
    <Link href={`/runs/${run.id}/`} className="pp-card pp-runcard">
      <div className="pp-runcard-top">
        <KindBadge kind={run.kind} />
        {run.dev && <span className="pp-chip is-point">모의 결과</span>}
      </div>
      <h3 className="pp-h3">{run.title}</h3>
      <p className="pp-runcard-agency">{run.agency}</p>
      <ul className="pp-chips">
        <li className="pp-chip">대표 {run.n_rep}명</li>
        <li className="pp-chip">영향권 {run.n_aff}명</li>
        <li className="pp-chip">쟁점 {run.n_issues}개</li>
        <li className="pp-chip">생성 {duration(run.seconds)}</li>
      </ul>
      {run.top_issue && <p className="pp-runcard-issue">가장 큰 쟁점 <b>{run.top_issue}</b></p>}
      <p className="pp-runcard-date">{dateKo(run.created_at)} 실행</p>
    </Link>
  );
}
