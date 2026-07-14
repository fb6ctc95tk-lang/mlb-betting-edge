import {
  getResearchInsights,
  type InsightableGame,
  type ResearchInsight,
} from "./researchInsights";
import { getMarketOpportunities, type MarketOpportunity } from "./marketOpportunities";

export type BoardEntry = {
  opportunity: MarketOpportunity;
  sourceInsights: ResearchInsight[];
};

export function buildBoardEntries(games: InsightableGame[]): BoardEntry[] {
  return games.flatMap((game) => {
    const insights = getResearchInsights(game);
    const opportunities = getMarketOpportunities(game, insights);
    return opportunities.map((opp) => ({
      opportunity: opp,
      sourceInsights: insights.filter((ins) => opp.sourceInsightIds.includes(ins.id)),
    }));
  });
}

/**
 * Returns the API URL to load board data for a given date selection.
 * An empty selectedDate means "today" — use /research/today.
 * Any non-empty date string uses /research/date/{date}.
 */
export function getBoardResearchUrl(apiBase: string, selectedDate: string): string {
  return selectedDate
    ? `${apiBase}/research/date/${selectedDate}`
    : `${apiBase}/research/today`;
}
