import { describe, it, expect } from "vitest";
import {
  getResearchInsights,
  type InsightableGame,
  FORM_HOT_WIN_RATE,
  FORM_COLD_WIN_RATE,
  FORM_UNDERDOG_PROB_MAX,
  FORM_FAVORITE_PROB_MIN,
  FORM_MIN_GAMES,
  RECORD_FORM_DIVERGENCE_THRESHOLD,
} from "./researchInsights";

// Silence TS unused-import warnings — constants are used as documentation anchors below.
void FORM_HOT_WIN_RATE;
void FORM_COLD_WIN_RATE;
void FORM_UNDERDOG_PROB_MAX;
void FORM_FAVORITE_PROB_MIN;
void RECORD_FORM_DIVERGENCE_THRESHOLD;

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

// ---------------------------------------------------------------------------
// Record vs. Recent Form Divergence
// ---------------------------------------------------------------------------

describe("record-vs-recent-form-divergence", () => {
  // Helpers — odds are empty so form-market-divergence never fires in these tests.

  // Away team clearly trending up: season 20% (10-40), recent 70% (7/10) → +50pp
  function awayUpGame(): InsightableGame {
    return {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "10-40",
      away_team_form: { last_10_wins: 7, last_10_games_count: 10 },
      home_team_form: null,
      odds: [],
    };
  }

  // Away team clearly trending down: season 80% (40-10), recent 30% (3/10) → -50pp
  function awayDownGame(): InsightableGame {
    return {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "40-10",
      away_team_form: { last_10_wins: 3, last_10_games_count: 10 },
      home_team_form: null,
      odds: [],
    };
  }

  // 1. Away team trending up
  it("generates insight when away team recent form clearly exceeds season profile", () => {
    const insights = getResearchInsights(awayUpGame());
    expect(insights).toHaveLength(1);
    expect(insights[0].id).toBe("record-form-divergence-away-up");
    expect(insights[0].title).toBe("MIA recent form exceeds season profile");
    expect(insights[0].severity).toBe("attention");
    expect(insights[0].category).toBe("form");
  });

  // 2. Away team trending down
  it("generates insight when away team recent form clearly trails season profile", () => {
    const insights = getResearchInsights(awayDownGame());
    expect(insights).toHaveLength(1);
    expect(insights[0].id).toBe("record-form-divergence-away-down");
    expect(insights[0].title).toBe("MIA recent form trails season profile");
    expect(insights[0].severity).toBe("attention");
    expect(insights[0].category).toBe("form");
  });

  // 3. Home team trending up
  it("generates insight when home team recent form clearly exceeds season profile", () => {
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      home_record: "10-40",
      away_team_form: null,
      home_team_form: { last_10_wins: 7, last_10_games_count: 10 },
      odds: [],
    };
    const insights = getResearchInsights(game);
    expect(insights).toHaveLength(1);
    expect(insights[0].id).toBe("record-form-divergence-home-up");
    expect(insights[0].title).toBe("PHI recent form exceeds season profile");
  });

  // 4. Home team trending down
  it("generates insight when home team recent form clearly trails season profile", () => {
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      home_record: "40-10",
      away_team_form: null,
      home_team_form: { last_10_wins: 3, last_10_games_count: 10 },
      odds: [],
    };
    const insights = getResearchInsights(game);
    expect(insights).toHaveLength(1);
    expect(insights[0].id).toBe("record-form-divergence-home-down");
    expect(insights[0].title).toBe("PHI recent form trails season profile");
  });

  // 5. Both teams trigger independently
  it("generates two insights when both teams independently qualify", () => {
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "10-40",  // 20% season — recent 70% = +50pp
      home_record: "40-10",  // 80% season — recent 30% = -50pp
      away_team_form: { last_10_wins: 7, last_10_games_count: 10 },
      home_team_form: { last_10_wins: 3, last_10_games_count: 10 },
      odds: [],
    };
    const insights = getResearchInsights(game);
    expect(insights).toHaveLength(2);
    expect(insights[0].id).toBe("record-form-divergence-away-up");
    expect(insights[1].id).toBe("record-form-divergence-home-down");
  });

  // 6. Inside threshold — no insight
  it("produces no insight when divergence is within the threshold", () => {
    // season 50% (5-5), recent 60% (3/5) → divergence = +10pp < 15pp
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "5-5",
      away_team_form: { last_10_wins: 3, last_10_games_count: 5 },
      home_team_form: null,
      odds: [],
    };
    expect(getResearchInsights(game)).toHaveLength(0);
  });

  // 7. Exact +15 boundary triggers
  it("triggers at exactly +15 percentage-point divergence (upward boundary)", () => {
    // season = "1-3" → 25% (1/4 — exact in IEEE 754)
    // recent = 2/5 → 40% (2/5 in IEEE 754 is 0.4000...2, slightly above 0.4)
    // divergence = (0.4000...2 - 0.25) * 100 = 15.000...002 ≥ 15 → triggers
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "1-3",
      away_team_form: { last_10_wins: 2, last_10_games_count: 5 },
      home_team_form: null,
      odds: [],
    };
    const insights = getResearchInsights(game);
    expect(insights).toHaveLength(1);
    expect(insights[0].id).toBe("record-form-divergence-away-up");
  });

  // 8. Exact -15 boundary triggers
  it("triggers at exactly -15 percentage-point divergence (downward boundary)", () => {
    // season = "3-1" → 75% (3/4 — exact in IEEE 754)
    // recent = 3/5 → 60% (3/5 in IEEE 754 is 0.5999...8, slightly below 0.6)
    // divergence = (0.5999...8 - 0.75) * 100 = -15.000...002 ≤ -15 → triggers
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "3-1",
      away_team_form: { last_10_wins: 3, last_10_games_count: 5 },
      home_team_form: null,
      odds: [],
    };
    const insights = getResearchInsights(game);
    expect(insights).toHaveLength(1);
    expect(insights[0].id).toBe("record-form-divergence-away-down");
  });

  // 9. Missing season record
  it("produces no insight when season record is missing", () => {
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      // away_record intentionally absent
      away_team_form: { last_10_wins: 7, last_10_games_count: 10 },
      home_team_form: null,
      odds: [],
    };
    expect(getResearchInsights(game)).toHaveLength(0);
  });

  it("produces no insight when season record is null", () => {
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: null,
      away_team_form: { last_10_wins: 7, last_10_games_count: 10 },
      home_team_form: null,
      odds: [],
    };
    expect(getResearchInsights(game)).toHaveLength(0);
  });

  // 10. Invalid season record format
  it("produces no insight when season record is not in wins-losses format", () => {
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "not-a-record",
      away_team_form: { last_10_wins: 7, last_10_games_count: 10 },
      home_team_form: null,
      odds: [],
    };
    expect(getResearchInsights(game)).toHaveLength(0);
  });

  it("produces no insight when season record has three segments", () => {
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "10-20-5",
      away_team_form: { last_10_wins: 7, last_10_games_count: 10 },
      home_team_form: null,
      odds: [],
    };
    expect(getResearchInsights(game)).toHaveLength(0);
  });

  // 11. Missing team form
  it("produces no insight when team form is null", () => {
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "10-40",
      away_team_form: null,
      home_team_form: null,
      odds: [],
    };
    expect(getResearchInsights(game)).toHaveLength(0);
  });

  // 12. last_10_games_count below minimum
  it("produces no insight when recent games count is below the minimum sample", () => {
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "10-40",
      away_team_form: { last_10_wins: 4, last_10_games_count: FORM_MIN_GAMES - 1 },
      home_team_form: null,
      odds: [],
    };
    expect(getResearchInsights(game)).toHaveLength(0);
  });

  // 13. Zero season games
  it("produces no insight when season record is 0-0", () => {
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "0-0",
      away_team_form: { last_10_wins: 7, last_10_games_count: 10 },
      home_team_form: null,
      odds: [],
    };
    expect(getResearchInsights(game)).toHaveLength(0);
  });

  // 14. Stable insight IDs per side and direction
  it("uses stable IDs that distinguish away-up, away-down, home-up, home-down", () => {
    const awayUp = getResearchInsights(awayUpGame());
    expect(awayUp[0].id).toBe("record-form-divergence-away-up");

    const awayDown = getResearchInsights(awayDownGame());
    expect(awayDown[0].id).toBe("record-form-divergence-away-down");

    const homeUp: InsightableGame = {
      away_team: "MIA", home_team: "PHI",
      home_record: "10-40",
      home_team_form: { last_10_wins: 7, last_10_games_count: 10 },
      away_team_form: null, odds: [],
    };
    expect(getResearchInsights(homeUp)[0].id).toBe("record-form-divergence-home-up");

    const homeDown: InsightableGame = {
      away_team: "MIA", home_team: "PHI",
      home_record: "40-10",
      home_team_form: { last_10_wins: 3, last_10_games_count: 10 },
      away_team_form: null, odds: [],
    };
    expect(getResearchInsights(homeDown)[0].id).toBe("record-form-divergence-home-down");
  });

  // 15. Description includes transparent season and recent percentages
  it("description states team name, recent win rate, season win rate, and signed divergence", () => {
    // season = "14-16" → 14/30 = 46.7%; recent = 7/10 = 70.0%; divergence = +23.3pp
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "14-16",
      away_team_form: { last_10_wins: 7, last_10_games_count: 10 },
      home_team_form: null,
      odds: [],
    };
    const { description } = getResearchInsights(game)[0];
    expect(description).toContain("MIA");
    expect(description).toContain("70.0%");
    expect(description).toContain("46.7%");
    expect(description).toContain("+23.3");
  });

  it("description uses a negative sign for downward divergence", () => {
    // season = "40-10" → 80%; recent = 3/10 = 30%; divergence = -50pp
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "40-10",
      away_team_form: { last_10_wins: 3, last_10_games_count: 10 },
      home_team_form: null,
      odds: [],
    };
    const { description } = getResearchInsights(game)[0];
    expect(description).toContain("MIA");
    expect(description).toContain("30.0%");
    expect(description).toContain("80.0%");
    expect(description).toContain("-50.0");
  });

  // 17. Input objects are not mutated
  it("does not mutate the input game object or its form data", () => {
    const form = { last_10_wins: 7, last_10_games_count: 10 };
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "10-40",
      away_team_form: form,
      home_team_form: null,
      odds: [],
    };
    const snapshot = JSON.parse(JSON.stringify(game)) as typeof game;
    getResearchInsights(game);
    expect(game.away_team_form).toBe(form);
    expect(JSON.parse(JSON.stringify(game))).toEqual(snapshot);
  });

  // 18. last_10_games_count fallback from wins + losses
  it("uses wins + losses as games count when last_10_games_count is absent", () => {
    // form without count: 8 wins + 2 losses = 10 games
    // season = "1-3" (25%), recent = 8/10 (80%) → divergence = +55pp
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "1-3",
      away_team_form: { last_10_wins: 8, last_10_losses: 2 },
      home_team_form: null,
      odds: [],
    };
    const insights = getResearchInsights(game);
    expect(insights).toHaveLength(1);
    expect(insights[0].id).toBe("record-form-divergence-away-up");
    expect(insights[0].description).toContain("10 games");
  });

  it("fallback still applies the minimum sample check (wins + losses < 5)", () => {
    // 2 wins + 2 losses = 4 games — below FORM_MIN_GAMES
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "1-3",
      away_team_form: { last_10_wins: 2, last_10_losses: 2 },
      home_team_form: null,
      odds: [],
    };
    expect(getResearchInsights(game)).toHaveLength(0);
  });

  // 19. Fallback does not run when losses are missing
  it("does not apply fallback when last_10_losses is absent", () => {
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "10-40",
      away_team_form: { last_10_wins: 8 },
      home_team_form: null,
      odds: [],
    };
    expect(getResearchInsights(game)).toHaveLength(0);
  });

  it("does not apply fallback when last_10_losses is null", () => {
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "10-40",
      away_team_form: { last_10_wins: 8, last_10_losses: null },
      home_team_form: null,
      odds: [],
    };
    expect(getResearchInsights(game)).toHaveLength(0);
  });

  // 20. No prohibited betting language
  it("titles and descriptions use neutral research language, not betting language", () => {
    const prohibited = ["bet", "pick", " edge", "value", "fade", "lock", "recommend", "expected to win", "strong play", "back this team"];
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "10-40",
      home_record: "40-10",
      away_team_form: { last_10_wins: 7, last_10_games_count: 10 },
      home_team_form: { last_10_wins: 3, last_10_games_count: 10 },
      odds: [],
    };
    const insights = getResearchInsights(game);
    expect(insights).toHaveLength(2);
    for (const insight of insights) {
      for (const word of prohibited) {
        expect(insight.title.toLowerCase()).not.toContain(word);
        expect(insight.description.toLowerCase()).not.toContain(word);
      }
    }
  });

  // 16 (integration) — existing form-market-divergence tests remain passing is verified
  // by running the full suite. This test confirms both generators coexist cleanly.
  it("does not interfere with form-market-divergence when both generators are active", () => {
    // A game with qualifying record-form divergence but also form-market-divergence conditions.
    // hotForm (70%) + underdog (36%) → form-market-divergence fires
    // away_record "1-3" (25%) + recent 2/5 (40%) → record-form-divergence also fires
    const game: InsightableGame = {
      away_team: "MIA",
      home_team: "PHI",
      away_record: "1-3",
      away_team_form: { last_10_wins: 7, last_10_games_count: 10 },
      odds: [{ away_implied_probability: 36, home_implied_probability: 64 }],
    };
    const insights = getResearchInsights(game);
    const ids = insights.map((i) => i.id);
    expect(ids).toContain("form-market-divergence");
    expect(ids).toContain("record-form-divergence-away-up");
  });
});
