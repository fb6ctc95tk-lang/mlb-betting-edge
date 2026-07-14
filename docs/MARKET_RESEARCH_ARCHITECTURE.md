# Market Research Architecture
## MLB Betting Edge — Phase 8 Research Layer Foundation

**Status:** Active — Phase 13 Interim Sprint 2 complete (2026-07-14). Two insight generators live. Market Research Board with historical date support shipped. Totals diagnostic pending valid recheck condition.
**Date:** 2026-07-14

This document describes the current architecture and implementation roadmap based only on confirmed data sources currently available in the application. It intentionally avoids assumptions about future APIs, sportsbook markets, or predictive models.

---

## Section 1: Current Data Inventory

Exact fields available in the database and API as of 2026-07-12, confirmed by direct code inspection of `database/schema.sql`, all backend fetchers, and `backend/routers/research.py`.

### 1.1 Games

From `games` table:
- `game_id`, `game_date`, `game_time`, `status`
- `away_team` (name string), `home_team` (name string)

### 1.2 Starting Pitchers

From `starting_pitchers` table:
- `game_id`, `side` ("home" / "away"), `pitcher_name` (string only)
- **No pitcher ID. No stats. No ERA, K/9, FIP, WHIP, or any performance metrics. Names only.**

### 1.3 Team Records

From `team_records` table:
- `team_id`, `wins`, `losses`, `record_date`

### 1.4 Research Layer Fields (Derived at Query Time)

Built in `backend/routers/research.py` from `team_records` and game history:
- Last 10: `last_10_wins`, `last_10_losses`, `last_10_run_diff`
- Home splits: `home_wins`, `home_losses`
- Road splits: `road_wins`, `road_losses`
- Streak: `current_streak` (integer), `streak_type` ("W" or "L")

The game detail endpoint (`GET /research/game/{id}`) now returns the same form, splits, and streak fields as the full research endpoints. This parity was added in Phase 10 and enables Research Insights and Market Opportunities to fire correctly on the Game Detail page.

### 1.5 Odds History

From `odds_history` table:
- `game_id`, `sportsbook`, `home_moneyline` (integer), `away_moneyline` (integer), `recorded_at`
- **No market type column. No over/under total. No run line. Moneyline only.**
- Sportsbooks: Bet365 and DraftKings only.

### 1.6 Line Movement

Derived at query time in `research.py`:
- Opening moneyline, latest moneyline, delta per sportsbook per side
- Computed from `odds_history`; not a stored table

### 1.7 Weather

From `game_weather` table:
- `temperature` (°F), `wind_speed` (mph), `wind_direction` (degrees), `precipitation_chance` (%)
- **Captured at ingestion time (11 AM and/or 7 PM), not at actual game time.**
- All 30 stadiums covered including domed and retractable-roof venues (HOU, TB, TOR).

### 1.8 Injuries

From `team_injuries` table:
- `team_id`, `player_name`, `injury_status`, `injury_description`
- **Known bug: ESPN abbreviation mapping is incomplete. Most records are skipped at save time.** Data is fetched; the team-name-to-abbreviation mapping fails for most teams.

### 1.9 Bullpen Context

From `team_bullpen_context` table:
- `team_id`, `previous_game_date`, `bullpen_innings_last_game` (float), `played_yesterday` (boolean)
- Total bullpen IP from previous game only. No individual pitcher breakdown.

### 1.10 What Does Not Exist Anywhere in This Project

The following data is absent from the database, all fetchers, and all API responses:

- Pitcher statistics (ERA, K/9, BB/9, FIP, WHIP, ground ball rate, first-inning ERA)
- Individual batter statistics (AVG, OBP, SLG, hard-hit rate, K%, exit velocity)
- Batter vs. pitcher (BvP) matchup history of any kind
- Inning-level scoring data (first inning runs, F5 scores)
- NRFI / YRFI historical rates
- First 5 innings moneyline or total odds
- Full-game over/under (total) odds
- Run line / spread odds
- Player prop odds of any kind

---

## Section 2: Market Readiness Matrix

Assessment of 10 target markets. Three status levels:

- **READY** — all necessary data exists; can build now without new sources or schema changes
- **PARTIAL** — some data available; buildable with minor additions
- **BLOCKED** — critical data missing; cannot build without at least one new data source or provider change

---

### 2.1 Full-Game Moneyline

**Status: READY**

What we need: Team form, records, pitcher names, weather, injuries, bullpen context, moneyline odds.
What we have: All of the above.
Active gaps: Injury data unreliable (mapping bug). Game detail endpoint missing form/splits/streak (backend fix needed, no schema change).
Notes: The only market with live odds. `formVsMarketDivergence` is already running. This is the market every other sprint builds on top of.

---

### 2.2 Full-Game Totals (O/U)

**Status: BLOCKED — but the closest non-ready market to unlockable**

What we need: Over/under odds, pitcher quality metrics, historical run totals, weather context.
What we have: Weather (wind direction and speed already present and relevant). Pitcher names.
Key uncertainty: `docs/ODDS_API_SETUP.md` states the free tier includes "Moneyline, spreads, totals." However, this was never live-tested. Our fetcher (`odds_api_io.py`) contains `if market.get("name") != "ML": continue` — all non-ML markets are discarded. Whether the API actually returns totals in the response for Bet365/DraftKings on the free tier is unknown.

This is the single most important unknown in the entire market roadmap. If the API returns totals, enabling them requires no provider change — only a schema column and a fetcher update.

Path to unlock: (1) Run a raw API call without the ML filter. (2) If totals appear in the response: add over/under columns to `odds_history` or a new `game_totals` table, update the fetcher, update the research endpoint. (3) Add pitcher quality context separately (ERA or similar from MLB Stats API). Steps 1–2 could ship in one sprint. Step 3 is separate.

---

### 2.3 NRFI / YRFI (No/Yes Run in First Inning)

**Status: BLOCKED**

What we need: Historical NRFI/YRFI rates per pitcher and per team, pitcher first-inning ERA or first-inning run-allowed rate, current NRFI/YRFI odds.
What we have: Pitcher names only. No historical inning-level scoring. No NRFI-specific odds.
Gap: Complete on all three dimensions. This market cannot be built on existing data.
Path to unlock: (1) Source first-inning scoring data from MLB Stats API (game linescore endpoint exists but is not currently fetched). (2) Source NRFI odds — not standard on low-tier providers. Likely requires a paid plan or a prop-specific API. (3) Minimum 2–3 sprints from scratch.

---

### 2.4 First 5 Innings Moneyline (F5 ML)

**Status: BLOCKED**

What we need: F5 moneyline odds, historical F5 results, pitcher quality for a 5-inning projection.
What we have: Pitcher names only. No F5 odds.
Gap: No F5 odds from any source. The free OddsAPI.io tier appears to expose only full-game markets in practice. No pitcher performance stats to assess starter quality.
Path to unlock: (1) Confirm whether free tier or a paid upgrade provides F5 markets. (2) Add pitcher stats. (3) Schema changes for F5 odds. This market is at least one full sprint behind Full-Game Totals on the priority ladder.

---

### 2.5 First 5 Innings Totals (F5 O/U)

**Status: BLOCKED**

Same blockers as F5 ML, plus no over/under data structure. Triple-blocked: no F5 odds, no pitcher stats, no schema.

---

### 2.6 Pitcher Strikeouts (K's prop)

**Status: BLOCKED**

What we need: Pitcher K/9, K%, career strikeout rates, opposing lineup K-rate, pitcher K prop odds.
What we have: Pitcher names only.
Gap: Complete. No pitcher stats exist anywhere in the project. No prop odds of any kind available on the current provider.

---

### 2.7 Pitcher Outs Recorded (prop)

**Status: BLOCKED**

Same as Pitcher K's. Additionally requires expected game script (large leads cause early hooks), which is also unavailable.

---

### 2.8 Hitter Hits (H prop)

**Status: BLOCKED**

What we need: Batter AVG, contact rate, hit rate vs. pitcher handedness, hit prop odds.
What we have: Nothing. No batter data exists in any form.
Gap: Complete.

---

### 2.9 Hitter Total Bases (TB prop)

**Status: BLOCKED**

Same as Hitter Hits, plus requires power metrics (ISO, SLG, fly-ball rate, exit velocity). None exist.

---

### 2.10 Hitter Home Runs (HR prop)

**Status: BLOCKED**

Same as Hitter Hits, plus requires HR rate, stadium factors, launch angle — none of which exist.

---

### Market Readiness Summary

| Market | Status | Primary Blocker |
|--------|--------|-----------------|
| Full-Game Moneyline | READY | None — form insight already live |
| Full-Game Totals | BLOCKED | API test needed; odds schema; pitcher stats |
| NRFI / YRFI | BLOCKED | Inning-level data; first-inning stats; prop odds provider |
| F5 Moneyline | BLOCKED | F5 odds; pitcher stats |
| F5 Totals | BLOCKED | F5 odds; pitcher stats; schema |
| Pitcher K's | BLOCKED | All pitcher stats; prop odds provider |
| Pitcher Outs | BLOCKED | All pitcher stats; prop odds provider |
| Hitter Hits | BLOCKED | All batter stats; prop odds provider |
| Hitter Total Bases | BLOCKED | All batter stats; prop odds provider |
| Hitter HRs | BLOCKED | All batter stats; prop odds provider |

**The only market that can grow without new data sources is Full-Game Moneyline.** Full-Game Totals is the next-closest — potentially unlockable with a single API investigation, no provider change.

---

## Section 3: Architecture Boundaries

Five distinct types. Each type has exactly one job and lives in one layer.

### 3.1 ResearchFlag (exists — `frontend/lib/gameFlags.ts`)

**Layer:** Visibility filter

**Job:** Identify games worth examining. A flag says "this game has a characteristic that may warrant attention." It makes no claim about direction or value.

**Examples:** "Has Significant Line Movement", "Has Weather Context", "Has Injuries"

**Rule:** Flags fire on the *presence* of a signal, not its interpretation. A flag fires when `wind_speed > 15 mph` — not when "wind favors the over." No flag ever implies which team to choose.

---

### 3.2 ResearchInsight (exists — `frontend/lib/researchInsights.ts`)

**Layer:** Pattern interpretation

**Job:** Compare two signals and surface a notable divergence. An insight says "this measurable thing is inconsistent with that measurable thing." It is descriptive, not prescriptive.

**Example (Form vs. Market Divergence):** "Hot Team as Underdog — PHI is 7-3 in their last 10 but the market prices them at 38% implied probability."

**Example (Record vs. Recent Form Divergence):** "PHI recent form exceeds season profile — PHI has won 70.0% of its last 10 games compared with a 52.0% season win rate, a +18.0 percentage-point difference."

**Implemented generators (as of 2026-07-14):**
1. `formVsMarketDivergence` — fires when a hot team is priced as a significant underdog, or a cold team is priced as a heavy favorite. IDs: `form-market-divergence`.
2. `recordVsRecentFormDivergence` — fires when recent win rate diverges from season win rate by ≥15 percentage points. IDs: `record-form-divergence-{away|home}-{up|down}`.

**Rule:** Insights never say "bet this." They never recommend a direction. They surface a pattern and stop. The researcher decides what to do with it.

---

### 3.3 MarketOpportunity (implemented — `frontend/lib/marketOpportunities.ts`)

**Layer:** Market research

**Job:** Associate a specific bet type and direction with a supporting research narrative. A MarketOpportunity says: "given these signals, here is the specific wager they point toward and what supports it."

**Implemented fields (as of Phase 9):**
- `id: string` — stable identifier for the opportunity
- `gameId: string` — linked game
- `marketType: MarketType` — currently `"FULL_GAME_MONEYLINE"` only
- `title: string` — short headline
- `summary: string` — one-sentence research narrative
- `reasons: string[]` — bullet points supporting the opportunity
- `cautionNotes: string[]` — known risks or data limitations
- `sourceInsightIds: string[]` — IDs of the ResearchInsights that triggered this opportunity
- `displayPriority?: number` — optional sort hint

**Fields NOT implemented:** No `direction`, no `team`, no `confidence` field. The opportunity is game-level and market-level — it names the market type but does not prescribe which side to choose.

**Rule:** MarketOpportunity does NOT say "this is a good bet." It says "here is the research case for this market on this game." The researcher still decides which side, if any, to act on.

---

### 3.4 ParlayLeg (not yet built — `frontend/lib/parlayBuilder.ts`)

**Layer:** Parlay construction

**Job:** Represent one confirmed leg in a parlay that the researcher has consciously chosen to add.

**Proposed fields:** `leg_id`, `game_id`, `away_team`, `home_team`, `market`, `direction`, `team` (the side selected), `odds_at_time_of_research` (optional — entered manually or pulled from odds table), `added_at`

**Rule:** ParlayLegs are researcher-chosen. The system never auto-populates them. Nothing in the system moves a ResearchInsight to a ParlayLeg without the researcher explicitly acting.

---

### 3.5 CorrelationWarning (not yet built — `frontend/lib/parlayBuilder.ts` or `correlations.ts`)

**Layer:** Parlay risk awareness

**Job:** Surface known correlations that reduce parlay value. A CorrelationWarning says "two legs you've selected share a root cause — sportsbooks typically price this in, reducing expected edge."

**Example warnings:**
- "NRFI + Home Team ML are positively correlated. A dominant pitching performance tends to suppress the home team's run total and improve their win probability simultaneously — these legs are not independent."
- "F5 Under + Full-Game Under overlap. If the first five innings go under, the full game is likely to follow. These legs are not independent."

**Rule:** CorrelationWarnings do NOT say "remove this leg." They surface the relationship and let the researcher decide whether the combined case still justifies the parlay.

---

## Section 4: Module Structure

Modules marked [exists] are implemented and tested. Modules marked [future] are not yet built.

```
frontend/lib/
├── gameFilters.ts           [exists] — filter logic (has injuries, has line move, etc.)
├── gameFlags.ts             [exists] — flag derivation (⚠ 📈 🌬)
├── gameFlagSummary.ts       [exists] — flag counts for the summary bar
├── researchInsights.ts      [exists] — InsightGenerator registry; formVsMarketDivergence;
│                                        recordVsRecentFormDivergence
├── marketOpportunities.ts   [exists] — MarketOpportunity type; FULL_GAME_MONEYLINE only;
│                                        formDivergenceToMoneyline generator
├── marketResearchBoard.ts   [exists] — getBoardResearchUrl(); getMarketOpportunitiesForBoard()
│
├── parlayBuilder.ts         [future] — ParlayLeg; CorrelationWarning; active parlay state
└── correlations.ts          [future] — known correlation rules, indexed by market pair
```

**Growth rule:** each module has one job. `researchInsights.ts` surfaces patterns in game data. `marketOpportunities.ts` connects those patterns to specific market types. `marketResearchBoard.ts` aggregates the full board view. `parlayBuilder.ts` manages the researcher's active parlay. `correlations.ts` knows which legs reduce each other's independence.

No module reaches into another module's layer. Insights do not create MarketOpportunities. The parlay builder does not generate insights.

---

## Section 5: Edge Calculation Boundary

The most important architectural constraint in the project. This defines where the system stops and the researcher begins.

### What This System Calculates

- Implied probability from moneyline — `backend/odds_math.py` (working)
- Average implied probability across books — `researchInsights.ts` (working)
- Win rate from recent form — `researchInsights.ts` (working)
- Divergence between form and market pricing — `formVsMarketDivergence` (working)
- Season win rate from wins/losses record string — `parseSeasonRecord()` in `researchInsights.ts` (working)
- Divergence between season record and recent win rate — `recordVsRecentFormDivergence` (working)
- Line movement delta — research endpoints (working)
- Weather signals — weather data + thresholds (working)
- Bullpen stress signals — bullpen context data (working, not yet an insight)

### What This System Does Not Calculate

- "True" win probability for either team
- Expected value (EV) of any bet or leg
- Kelly criterion stake sizes
- Any numerical edge estimate ("this line has +3.2% edge")
- Any rating or score that implies one game is a better bet than another
- Any recommendation about which team to choose

### Why This Boundary Exists

EV calculations require an estimate of true win probability. True win probability requires assumptions — about how much to weight recent form vs. season record vs. pitching vs. ballpark vs. weather vs. a dozen other variables. Those assumptions are the researcher's job.

If the system calculates EV, it buries those assumptions inside a number. The researcher sees "+4.2% EV" and can't evaluate whether to trust the model. This is especially dangerous early, when there is no backtesting data to validate any model.

This system surfaces the raw inputs — the form, the price, the divergence, the movement — and the researcher forms their own probability estimate. That is a more honest research tool and one that teaches the researcher rather than replacing their judgment.

### On Confidence Levels

The `MarketOpportunity` type does not include a `confidence` field. When MarketOpportunities were implemented in Phase 9, confidence ratings were intentionally omitted: they imply a model-backed probability estimate that the system does not calculate and does not attempt to calculate.

If a confidence field is added in a future sprint it must be ordinal, not quantitative. "Medium confidence" would mean "2–3 corroborating signals present, no major red flags" — not "58.3% implied true probability." The level must be defined by a count of inspectable supporting signals, not a hidden calculation.

---

## Section 6: Odds Provider Limitations

Confirmed state of OddsAPI.io free tier as of 2026-07-12, from direct code inspection and setup documentation.

### 6.1 What Is Confirmed

**Sportsbooks locked:** Bet365 and DraftKings only. The free account is locked to two sportsbooks on first use. This cannot be changed without upgrading the account or creating a new one.

**Market being fetched:** Moneyline ("ML") only. `backend/fetchers/odds_api_io.py` contains the filter: `if market.get("name") != "ML": continue`. All other markets are discarded at the fetcher level, regardless of what the API returns.

**Schema stores:** Integer American moneylines in `odds_history`. Columns: `home_moneyline`, `away_moneyline`. There is no market type column, no over/under value, no run line.

### 6.2 What Is Unconfirmed

**Does the free tier actually return totals and spreads?**

`docs/ODDS_API_SETUP.md` states the free plan includes "Moneyline (called 'ML'), spreads, totals." This came from the provider's documentation and was not verified by live API inspection — the initial setup test confirmed that moneyline data was returned correctly but did not check whether other markets appeared in the same response.

The ML filter in `odds_api_io.py` was a deliberate V1 scoping decision, not a workaround for a missing feature. It is entirely possible that Bet365 and DraftKings do return totals and run lines in the same API response, and we are silently discarding them.

**This is the single most important thing to investigate before planning any new market work.**

**Diagnostic run: 2026-07-14 — INCONCLUSIVE (All-Star break)**

`backend/scripts/diagnostics/check_oddsapi_totals.py` was run on 2026-07-14.

To run the diagnostic:
```
backend/venv/Scripts/python.exe backend/scripts/diagnostics/check_oddsapi_totals.py
```

This script is read-only. It does not write to the database, modify ingestion, or change any production code path.

**What was found on 2026-07-14:**

- 986 pending MLB events returned by the API (July 16 – September 27)
- No games exist for July 14 (All-Star break; regular season resumes July 17)
- All events returned empty `bookmakers: {}` — bookmakers have not yet posted lines for the July 16+ slate
- `markets=totals` parameter: HTTP 200 ACCEPTED — the API did not reject the parameter or return a plan/authorization error
- `markets=ML,totals` parameter: HTTP 200 ACCEPTED — same result
- No non-ML market names appeared in any response

**Interpretation:** The result is inconclusive, not negative. Empty bookmakers mean lines haven't been posted yet — not that totals are unavailable. The `markets=totals` parameter being accepted without error (HTTP 200, not 400 or 403) is a positive signal: if the free tier blocked totals entirely, an error response would be expected.

**Discovery: the API supports a `markets` parameter.** The production fetcher does not currently use it. When lines are posted, specifying `markets=totals` or `markets=ML,totals` may be the correct way to request totals data. This should be tested in the re-run.

**Recheck run: 2026-07-14 (Phase 13 Sprint 2) — STILL INCONCLUSIVE**

The diagnostic was re-run on 2026-07-14 as Phase 13 Sprint 2. A broader pre-flight scan of 50 events (July 16 – July 20) was conducted before running the script.

- 50 events scanned across July 16–20: all returned empty `bookmakers: {}`
- The script confirmed the first event (NYM @ PHI, July 16) still returns empty bookmakers
- The rate limit was hit (HTTP 429) mid-run — the 50-event scan consumed ~50 of the 100 requests/hour budget
- Steps 3 market parameter probes (`markets=totals`, `markets=ML,totals`) returned HTTP 429 due to the exhausted budget; their HTTP 200 behavior from Sprint 1 remains the last confirmed state

**Why still inconclusive:** Lines have not opened for any post-break game as of the time of this test (~1:30 AM on July 14). Regular season resumes July 16. Bookmakers typically post lines for a series on game day or the day prior — not during the break itself.

**Rate limit caution:** The 50-event pre-flight scan is expensive (50 API calls). Future re-runs should use the diagnostic script directly (approximately 5 calls total) rather than the broad event scan. The free tier allows 100 requests/hour.

**Next valid recheck condition (updated after Phase 13 Sprint 3):**

Run the diagnostic only after **both** conditions are met:
1. The 11 AM scheduled ingestion for the day has completed (exit=0).
2. `logs/ingestion.log` shows `Found N odds records` where **N > 0**.

"Games saved" is not sufficient. The July 12 ingestion saved 15 games but found 0 odds records — bookmakers did not post lines that day. The diagnostic must have confirmed bookmaker data to produce a meaningful result.

See `backend/scripts/diagnostics/TOTALS_DIAGNOSTIC_RUNBOOK.md` for the complete step-by-step procedure, verdict rules, and known limitations.

If totals appear: the path to Full-Game Totals research requires no provider change — only a schema addition and fetcher update.

If totals do not appear with active moneyline data confirmed: Full-Game Totals is blocked on a provider upgrade, exactly like every other non-ML market.

### 6.3 What Definitely Requires a Provider Change

These markets are not available on the free OddsAPI.io tier regardless of the API test outcome:

- NRFI / YRFI odds — not a standard market on low-tier or free plans
- First 5 innings odds — typically gated behind paid plans
- Player props (pitcher K's, hitter hits, TB, HR) — explicitly behind paid tiers; requires either The Odds API $30+/month or a specialized prop provider

### 6.4 Upgrade Path

When the project justifies a paid upgrade:

**The Odds API ($30/month tier)** — the clearest path. Includes F5, totals, and run line. At $99/month: player props and full historical odds archive. Large community, extensive documentation, well-understood scaling path. This is the recommended upgrade.

**Continue using OddsAPI.io for moneylines even after upgrading.** There is no reason to discard a free, working moneyline feed when adding a paid source for props or F5. Running both in parallel is straightforward.

---

## Section 7: First Market Recommendation

**Recommendation: Deepen Full-Game Moneyline research — not a new market.**

Every market other than full-game moneyline is blocked on data that doesn't exist. The recommendation is to build more insight generators for the one market with live odds, complete data, and an already-working research engine.

Reasoning: every parlay leg that involves a team winning begins with a full-game moneyline assessment. Improving the quality of that assessment now makes every future parlay decision better-informed, regardless of what other legs are eventually added.

**Five additional insight generators, all buildable from existing data:**

**Bullpen Stress** — Flag games where the previous day's bullpen logged heavy usage. An overworked bullpen entering a game is a concrete research signal for full-game outcome.
- Data needed: `bullpen_innings_last_game`, `played_yesterday`
- Already available: Yes

**Streak Pressure** — Flag games where a team on a long losing streak faces a team on a long winning streak. Identifies games where psychological and momentum factors are most visible in the data.
- Data needed: `current_streak`, `streak_type` for both teams
- Already available: Yes

**Road Form Divergence** — Flag games where the away team's road record diverges significantly from their overall record. A team that looks mediocre overall may be much worse on the road specifically.
- Data needed: `road_wins`, `road_losses`, full `wins`/`losses`
- Already available: Yes

**Home Fortress** — Flag games where the home team has a notably strong home record relative to their overall record.
- Data needed: `home_wins`, `home_losses`, full record
- Already available: Yes

**Line Move Against Form** — Flag games where the line has moved toward a team whose recent form is cold, or away from a team whose form is hot. This is the sharpest divergence signal currently constructible from existing data.
- Data needed: line movement delta, form data (`last_10_wins`, `last_10_games_count`)
- Already available: Yes — but line_movement is not yet in `InsightableGame`; a small type addition is needed

---

## Section 8: Smallest Shippable Sprint

**Sprint: Two new insight generators** (Part A is complete — see note)

### Part A — Fix the game detail endpoint to return form data ✅ COMPLETE (Phase 10)

The `GET /research/game/{id}` endpoint now returns the full form, splits, and streak fields. This was completed in Phase 10. Research Insights and Market Opportunities fire correctly on the Game Detail page. `backend/tests/test_game_detail.py` expanded to 11 tests covering form shape/values, streak shape/values, and splits shape/values.

### Part B — Bullpen Stress insight

A team going to a bullpen that pitched 3+ innings the day before is a concrete research signal. It is the most immediately actionable generator that can be added using data already on the `InsightableGame` shape.

Logic: If a team's bullpen played yesterday and logged ≥ 3.0 innings, fire an "attention" insight noting the stress.
Files: `frontend/lib/researchInsights.ts` (new generator), `frontend/lib/researchInsights.test.ts` (~4 new tests)

Note: This requires adding `away_bullpen` and `home_bullpen` to `InsightableGame`. Both the homepage and the game detail page already have this data in their game objects; the type just needs to expose it.

### Part C — Line Move vs. Form insight

The most analytically meaningful insight constructible from existing data. When the line is moving toward a cold team (or away from a hot team), there is something worth examining.

Logic: If `abs(line_movement_delta) >= LINE_MOVE_THRESHOLD` and the direction of movement is toward the colder team (or away from the hotter team), fire an "attention" insight noting the contradiction.
Files: `frontend/lib/researchInsights.ts` (new generator), `frontend/lib/researchInsights.test.ts`

Note: This requires adding line movement data to `InsightableGame`. The homepage already has `line_movement` arrays; the game detail page does too.

### What This Sprint Ships

- Game detail page shows form-based insights (the endpoint gap is closed)
- Two new insight types active on both dashboard and game detail page
- The `InsightableGame` type gains bullpen and line movement fields (all optional — backward-compatible with existing tests)
- All existing tests continue to pass
- New tests cover both generators

**Complexity: Small.** Two generator functions, one backend query addition, type extensions, and tests. No schema changes. No new data sources.

---

## Section 9: Parlay Path

How a researched opportunity becomes a parlay leg, from first signal to final decision. This is the full flow the architecture is designed to support.

### Step 1: Signals surface

The dashboard and game detail page display ResearchFlags and ResearchInsights. The researcher sees contextual information: "PHI is 7-3 in their last 10 but priced at 38% implied. The line has moved 12 points toward NYM. PHI's bullpen pitched 3.2 innings yesterday."

The system is already doing this. No new architecture needed at this step.

### Step 2: Researcher identifies a potential leg

The researcher reads the signals and makes their own assessment. They decide the form data outweighs the line movement concern, or vice versa. The system plays no role in this decision.

### Step 3: Researcher adds the leg to the Parlay Builder (future feature)

A "Add to Parlay" button appears on the game detail page. The researcher clicks it and selects the market ("Full-Game Moneyline") and direction ("PHI"). The system creates a ParlayLeg:
- `game_id`, `home_team: PHI`, `direction: home`, `market: "full-game moneyline"`
- `odds_at_time_of_research`: pulled from current odds table (or entered manually if not available)
- `supporting_insights`: the ResearchInsights that fired for this game at the time of adding

ParlayLegs are stored in localStorage, following the same pattern as the existing Research Workspace.

### Step 4: Parlay Builder displays the active parlay

A Parlay Builder section (separate from the Research Workspace) shows all active legs. For each leg: the game, the market, the direction, and the supporting signals that existed when the leg was added.

When 2+ legs are present, CorrelationWarnings fire if any known correlation rules apply between the selected legs.

### Step 5: Researcher reviews and decides

The researcher sees the full parlay — all legs, all supporting research, all correlation warnings — and makes their decision. The system never recommends, rates, or suggests what to do with the parlay.

### Step 6: Export (future)

The researcher can copy a plain-text parlay summary to the clipboard: a formatted list of legs with market, direction, and odds. No sportsbook integration. No automatic wagering.

---

## Section 10: Final Recommendation

### Next Sprint

Fix the game detail endpoint to return form data. Add the Bullpen Stress and Line Move vs. Form insight generators. Extend `InsightableGame` to include bullpen and line movement fields.

This sprint delivers: a fully functional game detail research page, two new insight types backed by the existing data, and a validated pattern for writing more insight generators. All within the current data footprint, no backend schema changes, no new APIs.

### Following Three Sprints

**Sprint 2 — OddsAPI.io Totals Investigation**

Before writing any totals-related research code: run a raw API call to confirm what markets the free tier actually returns. If Bet365 or DraftKings returns over/under totals, plan a sprint to add the schema column, update the fetcher, and build weather + pitcher context for totals research. If totals are not in the free tier response, do not attempt this sprint and revisit after a provider upgrade is justified.

**Sprint 3 — Streak and Split Insights**

Add the remaining three insight generators from Section 7: Streak Pressure, Road Form Divergence, and Home Fortress. All built on existing data, no backend changes. This completes the first full set of research tools for full-game moneyline and gives every game on the dashboard meaningful context.

**Sprint 4 — Parlay Builder v1**

Build the ParlayLeg type and the Parlay Builder UI, starting with full-game moneyline as the only available market. Add the "Add to Parlay" button to the game detail page. Display active legs with their supporting insights. Add basic CorrelationWarnings for the most obvious case (same game, opposite sides). Store state in localStorage. No prop markets, no sportsbook integration.

### Risks

**Totals investigation finds nothing.** If the free tier doesn't include totals, the second most researchable market is off the table until the project justifies a paid upgrade. Do not build totals research infrastructure speculatively — investigate first, build second.

**Injury data remains broken.** The team abbreviation mapping bug means injury-based insights would be unreliable at best, misleading at worst. Do not add an injury insight generator until the mapping is fixed and verified. The raw injury display on the game detail page is sufficient for manual research in the interim.

**Pitcher stats are the longest-range blocker.** NRFI, F5, and all pitcher/hitter prop markets require stats data that will take multiple sprints to acquire, clean, and validate. These are the right long-term destination but should not be worked on until the moneyline research layer is complete and the project has demonstrated day-to-day usefulness.

### What Not to Build

- Any numerical score or rating that ranks games or teams against each other
- Automatic parlay suggestions ("best parlay today")
- A backtester or model validator
- Stake sizing or bankroll management features
- Integration with any sportsbook platform
- Predicted game outcomes of any kind
- Features that depend on data not yet confirmed to exist in a live API call

These are not permanently excluded. They belong after the research workflow has proven its day-to-day usefulness — and after there is enough historical data to honestly validate any model that would generate them.

---

*All data inventories and provider limitations in this document are derived from direct inspection of source files, not from documentation inference alone. Section 6.2 describes the one confirmed unknown (totals availability on free tier). Resolve that before planning any totals market work.*
