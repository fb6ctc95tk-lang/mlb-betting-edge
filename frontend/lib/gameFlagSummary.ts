import { getGameFlags } from "./gameFlags";
import type { FlaggableGame } from "./gameFlags";

export type FlagSummary = {
  injuries: number;
  lineMovement: number;
  weather: number;
};

export function getGameFlagSummary(games: FlaggableGame[]): FlagSummary {
  const summary: FlagSummary = { injuries: 0, lineMovement: 0, weather: 0 };
  for (const game of games) {
    for (const flag of getGameFlags(game)) {
      if (flag.emoji === "⚠") summary.injuries++;
      else if (flag.emoji === "📈") summary.lineMovement++;
      else if (flag.emoji === "🌬") summary.weather++;
    }
  }
  return summary;
}
