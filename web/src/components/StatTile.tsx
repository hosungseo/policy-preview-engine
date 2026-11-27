import "./components.css";

export default function StatTile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="pp-card pp-stat">
      <div className="pp-stat-label">{label}</div>
      <div className="pp-stat-value">{value}</div>
      {note && <div className="pp-stat-note">{note}</div>}
    </div>
  );
}
