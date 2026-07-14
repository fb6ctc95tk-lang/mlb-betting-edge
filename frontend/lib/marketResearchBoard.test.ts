import { describe, it, expect } from "vitest";
import { buildBoardEntries, getBoardResearchUrl } from "./marketResearchBoard";
import type { InsightableGame } from "./researchInsights";

// Hot away team as underdog — triggers form-market-divergence insight + moneyline opportunity.
// last_10_wins=7/10 = 0.70 >= FORM_HOT_WIN_RATE (0.65); away_implied_probability=36 <= FORM_UNDERDOG_PROB_MAX (42)
function gameWithOpportunity(id = 1): InsightableGame {
  return {
    game_id: id,
    away_team: "MIA",
    home_team: "PHI",
    away_team_form: { last_10_wins: 7, last_10_games_count: 10 },
    odds: [{ away_implied_probability: 36, home_implied_probability: 64 }],
  };
}

// No form data and no odds — no insights fire, no opportunities.
function gameWithoutOpportunity(id = 2): InsightableGame {
  return {
    game_id: id,
    away_team: "NYY",
    home_team: "BOS",
    odds: [],
  };
}

describe("buildBoardEntries", () => {
  it("returns empty for no games", () => {
    expect(buildBoardEntries([])).toHaveLength(0);
  });

  it("returns empty when no games produce opportunities", () => {
    expect(buildBoardEntries([gameWithoutOpportunity()])).toHaveLength(0);
  });

  it("returns one entry when one game has one opportunity", () => {
    expect(buildBoardEntries([gameWithOpportunity()])).toHaveLength(1);
  });

  it("excludes games with no opportunities when games are mixed", () => {
    const entries = buildBoardEntries([gameWithOpportunity(), gameWithoutOpportunity()]);
    expect(entries).toHaveLength(1);
  });

  it("returns an entry per opportunity across multiple qualifying games", () => {
    const entries = buildBoardEntries([gameWithOpportunity(1), gameWithOpportunity(2)]);
    expect(entries).toHaveLength(2);
  });

  it("opportunity.gameId matches the game_id of the originating game", () => {
    const [entry] = buildBoardEntries([gameWithOpportunity(99)]);
    expect(entry.opportunity.gameId).toBe("99");
  });

  it("opportunity.marketType is FULL_GAME_MONEYLINE", () => {
    const [entry] = buildBoardEntries([gameWithOpportunity()]);
    expect(entry.opportunity.marketType).toBe("FULL_GAME_MONEYLINE");
  });

  it("sourceInsights are populated when the insight id matches sourceInsightIds", () => {
    const [entry] = buildBoardEntries([gameWithOpportunity()]);
    expect(entry.sourceInsights.length).toBeGreaterThan(0);
  });

  it("sourceInsights contain the form-market-divergence insight", () => {
    const [entry] = buildBoardEntries([gameWithOpportunity()]);
    expect(entry.sourceInsights[0].id).toBe("form-market-divergence");
  });

  it("does not crash when a game has no odds", () => {
    const noOddsGame: InsightableGame = {
      game_id: 3,
      away_team: "SEA",
      home_team: "LAA",
      away_team_form: { last_10_wins: 7, last_10_games_count: 10 },
      odds: [],
    };
    expect(() => buildBoardEntries([noOddsGame])).not.toThrow();
    expect(buildBoardEntries([noOddsGame])).toHaveLength(0);
  });

  it("BoardEntry has no score, rank, confidence, or EV fields", () => {
    const [entry] = buildBoardEntries([gameWithOpportunity()]);
    expect(entry).not.toHaveProperty("score");
    expect(entry).not.toHaveProperty("rank");
    expect(entry).not.toHaveProperty("confidence");
    expect(entry).not.toHaveProperty("expectedValue");
    expect(entry.opportunity).not.toHaveProperty("score");
    expect(entry.opportunity).not.toHaveProperty("confidence");
    expect(entry.opportunity).not.toHaveProperty("expectedValue");
  });

  it("opportunity has no team, side, or direction field", () => {
    const [entry] = buildBoardEntries([gameWithOpportunity()]);
    expect(entry.opportunity).not.toHaveProperty("team");
    expect(entry.opportunity).not.toHaveProperty("side");
    expect(entry.opportunity).not.toHaveProperty("direction");
  });
});

describe("getBoardResearchUrl", () => {
  it("returns /research/today when selectedDate is empty", () => {
    expect(getBoardResearchUrl("http://localhost:8000", "")).toBe(
      "http://localhost:8000/research/today"
    );
  });

  it("returns /research/date/{date} when selectedDate is set", () => {
    expect(getBoardResearchUrl("http://localhost:8000", "2026-06-20")).toBe(
      "http://localhost:8000/research/date/2026-06-20"
    );
  });

  it("returns /research/today after resetting selectedDate to empty (Back to Today)", () => {
    expect(getBoardResearchUrl("http://localhost:8000", "")).toBe(
      "http://localhost:8000/research/today"
    );
  });

  it("uses the provided apiBase in the constructed URL", () => {
    expect(getBoardResearchUrl("http://api.example.com:9000", "2026-07-05")).toBe(
      "http://api.example.com:9000/research/date/2026-07-05"
    );
  });

  it("empty historical result does not crash buildBoardEntries", () => {
    expect(() => buildBoardEntries([])).not.toThrow();
    expect(buildBoardEntries([])).toHaveLength(0);
  });
});
