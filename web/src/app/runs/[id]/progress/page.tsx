import type { Metadata } from "next";
import AiNotice from "@/components/AiNotice";
import { getRun, runParams } from "@/lib/bundles";
import Replay from "./Replay";
import "./progress.css";

export const dynamicParams = false;
export function generateStaticParams() {
  return runParams();
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `진행 · ${getRun(id).title}` };
}

export default async function ProgressPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const bundle = getRun(id);
  return (
    <div>
      <AiNotice />
      <div className="pp-container pp-page">
        <h1 className="pp-h1">{bundle.title}</h1>
        <p className="pp-lead">실제 실행 기록을 빠르게 다시 보여줍니다. 단계 옆의 시간은 실제로 걸린 시간입니다.</p>
        <Replay
          id={bundle.id}
          stages={bundle.meta.stages}
          counts={{
            personas: bundle.personas.length,
            reactions: bundle.reactions.length,
            issues: bundle.analysis.issues.length,
            turns: bundle.hearing.turns.length,
          }}
        />
      </div>
    </div>
  );
}
