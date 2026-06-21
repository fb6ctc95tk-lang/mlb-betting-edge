import type { GameFlag } from "../lib/gameFlags";

type ResearchFlagsProps = {
  flags: GameFlag[];
  emptyState?: React.ReactNode;
  compact?: boolean;
};

export default function ResearchFlags({
  flags,
  emptyState,
  compact = false,
}: ResearchFlagsProps) {
  if (flags.length === 0) {
    return emptyState !== undefined ? <>{emptyState}</> : null;
  }

  const padding = compact ? "2px 6px" : "2px 8px";
  const fontSize = compact ? "0.72em" : "0.8em";
  const marginRight = compact ? "4px" : "6px";

  return (
    <>
      {flags.map((f) => (
        <span
          key={f.label}
          style={{
            display: "inline-block",
            padding,
            fontSize,
            fontWeight: "bold",
            color: "#fff",
            background: f.color,
            borderRadius: "3px",
            marginRight,
            whiteSpace: "nowrap",
          }}
        >
          {f.emoji} {f.label}
        </span>
      ))}
    </>
  );
}
