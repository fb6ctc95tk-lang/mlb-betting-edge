import { LINE_MOVE_THRESHOLD } from "./gameFilters";

export type GameFlag = {
  emoji: string;
  label: string;
  color: string;
};

type FlaggableGame = {
  away_injuries: unknown[];
  home_injuries: unknown[];
  line_movement: { movement: number }[];
  weather: unknown | null;
};

export function getGameFlags(game: FlaggableGame): GameFlag[] {
  const flags: GameFlag[] = [];

  if (game.away_injuries.length > 0 || game.home_injuries.length > 0) {
    flags.push({ emoji: "⚠", label: "Injuries Present", color: "crimson" });
  }

  if (game.line_movement.length > 0) {
    const maxMove = Math.max(...game.line_movement.map((m) => Math.abs(m.movement)));
    if (maxMove >= LINE_MOVE_THRESHOLD) {
      flags.push({ emoji: "📈", label: "Significant Line Movement", color: "#1a56a0" });
    }
  }

  if (game.weather !== null) {
    flags.push({ emoji: "🌬", label: "Weather Context", color: "#5a6e00" });
  }

  return flags;
}
