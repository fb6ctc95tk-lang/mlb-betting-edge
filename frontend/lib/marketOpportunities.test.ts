import { describe, it, expect } from "vitest";
import { getMarketOpportunities } from "./marketOpportunities";
import type { InsightableGame, ResearchInsight } from "./researchInsights";

function bareGame(): InsightableGame {
  return { game_id: 1, away_team: "MIA", home_team: "PHI", odds: [] };
}

function formInsight(description = "MIA has gone 7-3 but priced at 36%"): ResearchInsight {
  return {
    id: "form-market-divergence",
    title: "Hot Team as Underdog",
    description,
    severity: "attention",
    category: "form",
  };
}

function otherInsight(): ResearchInsight {
  return {
    id: "some-other-insight",
    title: "Other",
    description: "Other description",
    severity: "info",
    category: "market",
  };
}

describe("getMarketOpportunities", () => {
  describe("no opportunities produced", () => {
    it("returns empty when insight list is empty", () => {
      expect(getMarketOpportunities(bareGame(), [])).toHaveLength(0);
    });

    it("returns empty when no insight matches form-market-divergence", () => {
      expect(getMarketOpportunities(bareGame(), [otherInsight()])).toHaveLength(0);
    });
  });

  describe("form-divergence-moneyline generator", () => {
    it("returns one opportunity when one form-market-divergence insight is present", () => {
      expect(getMarketOpportunities(bareGame(), [formInsight()])).toHaveLength(1);
    });

    it("returns one opportunity even when two form-market-divergence insights are present", () => {
      const insights = [
        formInsight("MIA has gone 7-3 but priced at 36%"),
        formInsight("PHI has gone 3-7 but priced at 64%"),
      ];
      expect(getMarketOpportunities(bareGame(), insights)).toHaveLength(1);
    });

    it("opportunity has correct id", () => {
      const [opp] = getMarketOpportunities(bareGame(), [formInsight()]);
      expect(opp.id).toBe("form-divergence-moneyline");
    });

    it("opportunity has correct marketType", () => {
      const [opp] = getMarketOpportunities(bareGame(), [formInsight()]);
      expect(opp.marketType).toBe("FULL_GAME_MONEYLINE");
    });

    it("opportunity title is the research candidate label", () => {
      const [opp] = getMarketOpportunities(bareGame(), [formInsight()]);
      expect(opp.title).toBe("Full-Game Moneyline Research Candidate");
    });

    it("opportunity summary is non-empty", () => {
      const [opp] = getMarketOpportunities(bareGame(), [formInsight()]);
      expect(opp.summary.length).toBeGreaterThan(0);
    });

    it("opportunity reasons are non-empty", () => {
      const [opp] = getMarketOpportunities(bareGame(), [formInsight()]);
      expect(opp.reasons.length).toBeGreaterThan(0);
    });

    it("cautionNotes include a disclaimer that this is not a betting recommendation", () => {
      const [opp] = getMarketOpportunities(bareGame(), [formInsight()]);
      expect(opp.cautionNotes.length).toBeGreaterThan(0);
      expect(
        opp.cautionNotes.some((n) => n.toLowerCase().includes("not a betting recommendation"))
      ).toBe(true);
    });

    it("cautionNotes disclaim expected value calculations", () => {
      const [opp] = getMarketOpportunities(bareGame(), [formInsight()]);
      expect(
        opp.cautionNotes.some((n) => n.toLowerCase().includes("expected value"))
      ).toBe(true);
    });

    it("sourceInsightIds contains form-market-divergence", () => {
      const [opp] = getMarketOpportunities(bareGame(), [formInsight()]);
      expect(opp.sourceInsightIds).toContain("form-market-divergence");
    });

    it("gameId reflects the game_id field on the game object", () => {
      const game = { ...bareGame(), game_id: 99 };
      const [opp] = getMarketOpportunities(game, [formInsight()]);
      expect(opp.gameId).toBe("99");
    });

    it("unrelated insights do not inflate the opportunity count", () => {
      const result = getMarketOpportunities(bareGame(), [formInsight(), otherInsight()]);
      expect(result).toHaveLength(1);
    });
  });
});
