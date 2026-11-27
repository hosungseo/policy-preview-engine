import type { Metadata } from "next";
import Link from "next/link";
import RunCard from "@/components/RunCard";
import { listRuns } from "@/lib/bundles";

export const metadata: Metadata = { title: "사례" };

export default function Explore() {
  const runs = listRuns();
  return (
    <div className="pp-container pp-page">
      <h1 className="pp-h1">사례</h1>
      <p className="pp-lead">
        합성 인물 패널로 미리 들어 본 정책입니다. 진행 중인 입법예고 원문, 공개 논의를 바탕으로 쓴 가상 정책안, 공개 자료 요약을
        섞어 두었습니다.
      </p>
      {runs.length === 0 ? (
        <p className="pp-sub">아직 실행된 사례가 없습니다.</p>
      ) : (
        <div className="pp-grid-3">{runs.map((run) => <RunCard key={run.id} run={run} />)}</div>
      )}
      <h2 className="pp-h2 pp-explore-more">이어서 본 사례</h2>
      <ul className="pp-explore-sets">
        <li>
          <Link href="/series/housing/">
            <b>부동산 대책 흐름</b>
            <span>대책이 이어질 때 찬반이 어떻게 움직였는지 대책별로 봅니다.</span>
          </Link>
        </li>
      </ul>
    </div>
  );
}
