import { duration } from "@/lib/format";
import type { Meta } from "@/lib/types";
import "./components.css";

// "N calls · time · $" for one Jev job, from the API's own token counts (the showcase-style receipt).
export default function JevReceipt({ meta, stage, tasks, note }: {
  meta: Meta; stage: string; tasks?: string[]; note?: string;
}) {
  const used = meta.jev_usage?.[stage];
  if (!used) return null;
  const rows = Object.entries(used).filter(([task]) => !tasks || tasks.includes(task)).map(([, u]) => u);
  if (!rows.length) return null;
  const calls = rows.reduce((a, u) => a + u.calls, 0);
  const cached = rows.reduce((a, u) => a + (u.cached ?? 0), 0);
  const cost = rows.reduce((a, u) => a + u.cost_usd, 0);
  const seconds = meta.stages.find((s) => s.name === stage)?.seconds;
  return (
    <p className="pp-receipt">
      <b>Jev</b> {calls.toLocaleString()}회{cached > 0 && ` (+캐시 ${cached.toLocaleString()}회)`}
      {seconds !== undefined && !tasks && <> · {duration(seconds)}</>} · ${cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2)}
      {note && <> · {note}</>}
    </p>
  );
}
