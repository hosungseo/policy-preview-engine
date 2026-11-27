import type { Metadata } from "next";
import { getRun, listRuns } from "@/lib/bundles";
import { STAGES } from "@/lib/format";
import NewForm from "./NewForm";
import "./new.css";

export const metadata: Metadata = { title: "새 의견수렴 설계" };

export default function NewPage() {
  const examples = listRuns().map((run) => {
    const bundle = getRun(run.id);
    return { id: run.id, title: bundle.title, kind: bundle.kind, agency: bundle.agency, text: bundle.policy_text };
  });
  return (
    <div className="pp-container pp-page">
      <h1 className="pp-h1">새 의견수렴 설계</h1>
      <p className="pp-lead">
        정책안이나 입법예고문을 넣으면 합성 국민 패널이 반응하고, 조항별 쟁점 지도와 찾아가 들어야 할 집단, 의견수렴 계획서
        초안을 만듭니다.
      </p>
      <p className="pp-poc">
        이 화면은 <b>예시 체험</b>입니다. 미리 실행해 둔 예시 4건의 결과로만 연결됩니다. 내 정책으로 실제 분석을 하려면{" "}
        <a href="/review/new/">미리 묻기</a>를 쓰세요.
      </p>
      <div className="pp-new">
        <NewForm examples={examples} />
        <aside className="pp-card-soft">
          <h2 className="pp-h3">이렇게 진행됩니다</h2>
          <ol className="pp-steps">
            {STAGES.map((s) => (
              <li key={s.key}><div><b>{s.title}</b><span>{s.desc}</span></div></li>
            ))}
          </ol>
        </aside>
      </div>
    </div>
  );
}
