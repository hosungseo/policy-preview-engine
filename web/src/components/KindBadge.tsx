import { KIND_CLASS } from "@/lib/format";

export default function KindBadge({ kind }: { kind: string }) {
  return <span className={`${KIND_CLASS[kind] ?? "krds-badge bg-gray"} pp-kind`}>{kind}</span>;
}
