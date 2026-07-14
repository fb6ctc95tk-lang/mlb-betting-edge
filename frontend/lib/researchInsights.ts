export type InsightSeverity = "info" | "attention";

export type InsightCategory =
  | "form"
  | "market"
  | "bullpen"
  | "weather"
  | "injuries"
  | "splits"
  | "streaks"
  | "odds";

export type ResearchInsight = {
  id: string;
  title: string;
  description: string;
  severity: InsightSeverity;
  category: InsightCategory;
};

// Internal types — only the fields each insight actually needs.
type TeamForm = {
  last_10_wins: number;
  last_10_losses?: number | null;
  last_10_games_count?: number | null;
};

type OddsEntry = {
  away_implied_probability: number;
  home_implied_probability: number;
};

// Minimal structural type. Optional fields allow use with partial game objects
// (e.g. the game detail page, which doesn't include team form data).
// Any game type whose fields are a superset of this is assignable without casting.
export type InsightableGame = {
  game_id?: number;
  away_team: string;
  home_team: string;
  away_record?: string | null;
  home_record?: string | null;
  away_team_form?: TeamForm | null;
  home_team_form?: TeamForm | null;
  odds: OddsEntry[];
};

type InsightGenerator = (game: InsightableGame) => ResearchInsight[];

// Exported so tests can reference thresholds without embedding magic numbers.
export const FORM_HOT_WIN_RATE = 0.65;
export const FORM_COLD_WIN_RATE = 0.35;
export const FORM_UNDERDOG_PROB_MAX = 42;         // % implied — at or below this = notable underdog
export const FORM_FAVORITE_PROB_MIN = 58;         // % implied — at or above this = notable favorite
export const FORM_MIN_GAMES = 5;                  // minimum last-N sample for form to be meaningful
export const RECORD_FORM_DIVERGENCE_THRESHOLD = 15; // percentage-point gap to trigger the insight

function avgImpliedProb(odds: OddsEntry[], side: "away" | "home"): number | null {
  if (odds.length === 0) return null;
  const vals = odds.map((o) =>
    side === "away" ? o.away_implied_probability : o.home_implied_probability
  );
  return vals.reduce((sum, v) => sum + v, 0) / vals.length;
}

// Insight I-2 — Form vs. Market Divergence
// Fires when a hot team is a significant underdog, or a cold team is a heavy favorite.
// Can produce up to two insights per game (one per team).
function formVsMarketDivergence(game: InsightableGame): ResearchInsight[] {
  const insights: ResearchInsight[] = [];

  const sides = [
    { team: game.away_team, form: game.away_team_form, side: "away" as const },
    { team: game.home_team, form: game.home_team_form, side: "home" as const },
  ];

  for (const { team, form, side } of sides) {
    const prob = avgImpliedProb(game.odds, side);
    if (prob === null || !form) continue;
    const count = form.last_10_games_count;
    if (count == null || count < FORM_MIN_GAMES) continue;

    const rate = form.last_10_wins / count;
    const losses = count - form.last_10_wins;
    const record = `${form.last_10_wins}-${losses}`;
    const probLabel = `${Math.round(prob)}%`;

    if (rate >= FORM_HOT_WIN_RATE && prob <= FORM_UNDERDOG_PROB_MAX) {
      insights.push({
        id: "form-market-divergence",
        title: "Hot Team as Underdog",
        description: `${team} has gone ${record} in their last ${count} games but the market prices them at ${probLabel} implied probability.`,
        severity: "attention",
        category: "form",
      });
    } else if (rate <= FORM_COLD_WIN_RATE && prob >= FORM_FAVORITE_PROB_MIN) {
      insights.push({
        id: "form-market-divergence",
        title: "Cold Team as Favorite",
        description: `${team} has gone ${record} in their last ${count} games but the market prices them at ${probLabel} implied probability.`,
        severity: "attention",
        category: "form",
      });
    }
  }

  return insights;
}

// Parses a "wins-losses" season record string. Returns null for invalid input or 0-0.
function parseSeasonRecord(record: string): { wins: number; losses: number } | null {
  const parts = record.split("-");
  if (parts.length !== 2) return null;
  const wins = parseInt(parts[0], 10);
  const losses = parseInt(parts[1], 10);
  if (!Number.isFinite(wins) || !Number.isFinite(losses)) return null;
  if (wins + losses === 0) return null;
  return { wins, losses };
}

// Returns the number of recent games to use. Prefers last_10_games_count;
// falls back to wins + losses when count is absent and both are valid non-negative numbers.
function resolveGamesCount(form: TeamForm): number | null {
  const count = form.last_10_games_count;
  if (count != null && count > 0) return count;
  const wins = form.last_10_wins;
  const losses = form.last_10_losses;
  if (typeof losses === "number" && losses >= 0 && wins >= 0) {
    return wins + losses;
  }
  return null;
}

// Insight I-3 — Record vs. Recent Form Divergence
// Fires when a team's recent win rate diverges from its season win rate by >= 15pp.
// Can produce up to two insights per game (one per team), independently.
function recordVsRecentFormDivergence(game: InsightableGame): ResearchInsight[] {
  const insights: ResearchInsight[] = [];

  const sides = [
    { team: game.away_team, form: game.away_team_form, record: game.away_record, sideKey: "away" as const },
    { team: game.home_team, form: game.home_team_form, record: game.home_record, sideKey: "home" as const },
  ];

  for (const { team, form, record, sideKey } of sides) {
    if (!form || !record) continue;

    const parsed = parseSeasonRecord(record);
    if (!parsed) continue;

    const gamesCount = resolveGamesCount(form);
    if (gamesCount == null || gamesCount < FORM_MIN_GAMES) continue;

    const seasonWinPct = parsed.wins / (parsed.wins + parsed.losses);
    const recentWinPct = form.last_10_wins / gamesCount;
    const divergence = (recentWinPct - seasonWinPct) * 100;

    const recentLabel = (recentWinPct * 100).toFixed(1);
    const seasonLabel = (seasonWinPct * 100).toFixed(1);

    if (divergence >= RECORD_FORM_DIVERGENCE_THRESHOLD) {
      insights.push({
        id: `record-form-divergence-${sideKey}-up`,
        title: `${team} recent form exceeds season profile`,
        description: `${team} has won ${recentLabel}% of its last ${gamesCount} games compared with a ${seasonLabel}% season win rate, a +${divergence.toFixed(1)} percentage-point difference.`,
        severity: "attention",
        category: "form",
      });
    } else if (divergence <= -RECORD_FORM_DIVERGENCE_THRESHOLD) {
      insights.push({
        id: `record-form-divergence-${sideKey}-down`,
        title: `${team} recent form trails season profile`,
        description: `${team} has won ${recentLabel}% of its last ${gamesCount} games compared with a ${seasonLabel}% season win rate, a ${divergence.toFixed(1)} percentage-point difference.`,
        severity: "attention",
        category: "form",
      });
    }
  }

  return insights;
}

// Registry — add new insight generators here. Order determines display order.
const INSIGHT_GENERATORS: InsightGenerator[] = [
  formVsMarketDivergence,
  recordVsRecentFormDivergence,
];

export function getResearchInsights(game: InsightableGame): ResearchInsight[] {
  return INSIGHT_GENERATORS.flatMap((gen) => gen(game));
}
