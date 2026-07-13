import { describe, it, expect } from "vitest";
import {
  getResearchInsights,
  type InsightableGame,
  FORM_HOT_WIN_RATE,
  FORM_COLD_WIN_RATE,
  FORM_UNDERDOG_PROB_MAX,
  FORM_FAVORITE_PROB_MIN,
  FORM_MIN_GAMES,
} from "./researchInsights";

// Silence TS unused-import warnings — constants are used as documentation anchors below.
void FORM_HOT_WIN_RATE;
void FORM_COLD_WIN_RATE;
void FORM_UNDERDOG_PROB_MAX;
void FORM_FAVORITE_PROB_MIN;

function bare(): InsightableGame {
  return {
    away_team: "MIA",
    home_team: "PHI",
    away_team_form: null,
    home_team_form: null,
    odds: [],
  };
}

// away at 36% (underdog), home at 64% (heavy favorite)
const awayUnderdog = [{ away_implied_probability: 36, home_implied_probability: 64 }];
// away at 64% (heavy favorite), home at 36% (underdog)
const homeUnderdog = [{ away_implied_probability: 64, home_implied_probability: 36 }];

// 70% — above FORM_HOT_WIN_RATE
const hotForm = { last_10_wins: 7, last_10_games_count: 10 };
// 30% — below FORM_COLD_WIN_RATE
const coldForm = { last_10_wins: 3, last_10_games_count: 10 };
// 50% — neither hot nor cold
const neutralForm = { last_10_wins: 5, last_10_games_count: 10 };
// Sample smaller than FORM_MIN_GAMES
const tinyForm = { last_10_wins: 4, last_10_games_count: FORM_MIN_GAMES - 1 };

describe("getResearchInsights", () => {
  describe("no insights produced", () => {
    it("returns empty when there are no odds", () => {
      const game: InsightableGame = {
        ...bare(),
        away_team_form: hotForm,
        home_team_form: coldForm,
      };
      expect(getResearchInsights(game)).toHaveLength(0);
    });

    it("returns empty when form data is null for both teams", () => {
      expect(getResearchInsights({ ...bare(), odds: awayUnderdog })).toHaveLength(0);
    });

    it("returns empty when form fields are entirely absent (game-detail-page shape)", () => {
      // GameDetail does not include team form — the optional fields are simply missing.
      const game = { away_team: "MIA", home_team: "PHI", odds: awayUnderdog };
      expect(getResearchInsights(game)).toHaveLength(0);
    });

    it("returns empty when the form sample is below the minimum", () => {
      const game: InsightableGame = {
        ...bare(),
        away_team_form: tinyForm,
        odds: awayUnderdog,
      };
      expect(getResearchInsights(game)).toHaveLength(0);
    });

    it("returns empty when a hot team is correctly priced as the favorite", () => {
      // Hot + favorite = market agrees with form, no divergence.
      const game: InsightableGame = {
        ...bare(),
        away_team_form: hotForm,
        odds: homeUnderdog, // away at 64% — heavily favored
      };
      expect(getResearchInsights(game)).toHaveLength(0);
    });

    it("returns empty when a cold team is correctly priced as the underdog", () => {
      // Cold + underdog = market agrees with form, no divergence.
      const game: InsightableGame = {
        ...bare(),
        away_team_form: coldForm,
        odds: awayUnderdog, // away at 36% — underdog
      };
      expect(getResearchInsights(game)).toHaveLength(0);
    });

    it("returns empty for a neutral-form team regardless of market price", () => {
      const game: InsightableGame = {
        ...bare(),
        away_team_form: neutralForm,
        home_team_form: neutralForm,
        odds: awayUnderdog,
      };
      expect(getResearchInsights(game)).toHaveLength(0);
    });
  });

  describe("form-market-divergence: hot team as underdog", () => {
    it("flags a hot away team priced as a significant underdog", () => {
      const game: InsightableGame = {
        ...bare(),
        away_team_form: hotForm,
        odds: awayUnderdog,
      };
      const insights = getResearchInsights(game);
      expect(insights).toHaveLength(1);
      expect(insights[0].id).toBe("form-market-divergence");
      expect(insights[0].title).toBe("Hot Team as Underdog");
      expect(insights[0].severity).toBe("attention");
      expect(insights[0].category).toBe("form");
    });

    it("flags a hot home team priced as a significant underdog", () => {
      const game: InsightableGame = {
        ...bare(),
        home_team_form: hotForm,
        odds: homeUnderdog,
      };
      const insights = getResearchInsights(game);
      expect(insights).toHaveLength(1);
      expect(insights[0].title).toBe("Hot Team as Underdog");
    });

    it("description names the team, shows their record, and shows implied probability", () => {
      const game: InsightableGame = {
        ...bare(),
        away_team_form: hotForm,
        odds: awayUnderdog,
      };
      const { description } = getResearchInsights(game)[0];
      expect(description).toContain("MIA");
      expect(description).toContain("7-3");
      expect(description).toContain("36%");
    });

    it("description names the home team when home is the hot underdog", () => {
      const game: InsightableGame = {
        ...bare(),
        home_team_form: hotForm,
        odds: homeUnderdog,
      };
      expect(getResearchInsights(game)[0].description).toContain("PHI");
    });
  });

  describe("form-market-divergence: cold team as favorite", () => {
    it("flags a cold away team priced as a heavy favorite", () => {
      const game: InsightableGame = {
        ...bare(),
        away_team_form: coldForm,
        odds: homeUnderdog, // away at 64% — heavy favorite
      };
      const insights = getResearchInsights(game);
      expect(insights).toHaveLength(1);
      expect(insights[0].id).toBe("form-market-divergence");
      expect(insights[0].title).toBe("Cold Team as Favorite");
      expect(insights[0].severity).toBe("attention");
      expect(insights[0].category).toBe("form");
    });

    it("flags a cold home team priced as a heavy favorite", () => {
      const game: InsightableGame = {
        ...bare(),
        home_team_form: coldForm,
        odds: awayUnderdog, // home at 64% — heavy favorite
      };
      const insights = getResearchInsights(game);
      expect(insights).toHaveLength(1);
      expect(insights[0].title).toBe("Cold Team as Favorite");
    });

    it("description names the team, shows their record, and shows implied probability", () => {
      const game: InsightableGame = {
        ...bare(),
        away_team_form: coldForm,
        odds: homeUnderdog,
      };
      const { description } = getResearchInsights(game)[0];
      expect(description).toContain("MIA");
      expect(description).toContain("3-7");
      expect(description).toContain("64%");
    });
  });

  describe("simultaneous insights", () => {
    it("returns two insights when both teams meet divergence thresholds at once", () => {
      // away: hot (70%) + underdog (36%); home: cold (30%) + favorite (64%)
      const game: InsightableGame = {
        ...bare(),
        away_team_form: hotForm,
        home_team_form: coldForm,
        odds: awayUnderdog,
      };
      const insights = getResearchInsights(game);
      expect(insights).toHaveLength(2);
      expect(insights[0].title).toBe("Hot Team as Underdog");
      expect(insights[1].title).toBe("Cold Team as Favorite");
    });
  });

  describe("multi-book odds", () => {
    it("averages implied probability across multiple sportsbooks before applying thresholds", () => {
      // Average away prob: (38 + 40) / 2 = 39 — below FORM_UNDERDOG_PROB_MAX
      const multiBook = [
        { away_implied_probability: 38, home_implied_probability: 62 },
        { away_implied_probability: 40, home_implied_probability: 60 },
      ];
      const game: InsightableGame = {
        ...bare(),
        away_team_form: hotForm,
        odds: multiBook,
      };
      const insights = getResearchInsights(game);
      expect(insights).toHaveLength(1);
      expect(insights[0].description).toContain("39%");
    });

    it("does not fire when averaged probability crosses a threshold that individual books don't", () => {
      // Book A: away at 40% (underdog), Book B: away at 46% (not underdog)
      // Average: 43% — above FORM_UNDERDOG_PROB_MAX (42%), so no insight.
      const splitBooks = [
        { away_implied_probability: 40, home_implied_probability: 60 },
        { away_implied_probability: 46, home_implied_probability: 54 },
      ];
      const game: InsightableGame = {
        ...bare(),
        away_team_form: hotForm,
        odds: splitBooks,
      };
      expect(getResearchInsights(game)).toHaveLength(0);
    });
  });
});
