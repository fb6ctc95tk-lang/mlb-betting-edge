import type { InsightableGame, ResearchInsight } from "./researchInsights";

export type MarketType = "FULL_GAME_MONEYLINE";

export type MarketOpportunity = {
  id: string;
  gameId: string;
  marketType: MarketType;
  title: string;
  summary: string;
  reasons: string[];
  cautionNotes: string[];
  sourceInsightIds: string[];
  displayPriority?: number;
};

type OpportunityContext = {
  game: InsightableGame;
  insights: ResearchInsight[];
};

type MarketOpportunityGenerator = {
  id: string;
  supportedMarket: MarketType;
  generate: (context: OpportunityContext) => MarketOpportunity[];
};

const CAUTION_NOTES: string[] = [
  "This is not a betting recommendation.",
  "This does not calculate expected value or fair odds.",
  "Review pitching, injuries, bullpen context, weather, and current price before making any decision.",
];

const formDivergenceToMoneyline: MarketOpportunityGenerator = {
  id: "form-divergence-moneyline",
  supportedMarket: "FULL_GAME_MONEYLINE",
  generate({ game, insights }) {
    const matched = insights.filter((i) => i.id === "form-market-divergence");
    if (matched.length === 0) return [];
    return [
      {
        id: "form-divergence-moneyline",
        gameId: String(game.game_id ?? ""),
        marketType: "FULL_GAME_MONEYLINE",
        title: "Full-Game Moneyline Research Candidate",
        summary:
          "This game may deserve additional moneyline review because existing research indicates a potential difference between recent team form and current market pricing.",
        reasons: [
          "Form vs. Market Divergence insight detected.",
          "Full-game moneyline odds and line movement data are available for this game.",
        ],
        cautionNotes: CAUTION_NOTES,
        sourceInsightIds: matched.map((i) => i.id),
        displayPriority: 1,
      },
    ];
  },
};

// Registry — add new opportunity generators here. Order determines display order.
const OPPORTUNITY_GENERATORS: MarketOpportunityGenerator[] = [
  formDivergenceToMoneyline,
];

export function getMarketOpportunities(
  game: InsightableGame,
  insights: ResearchInsight[]
): MarketOpportunity[] {
  return OPPORTUNITY_GENERATORS.flatMap((gen) => gen.generate({ game, insights }));
}
