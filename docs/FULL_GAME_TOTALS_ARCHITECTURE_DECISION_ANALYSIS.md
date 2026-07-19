# Full-Game Totals Architecture Decision Analysis
## MLB Betting Edge — Phase 15 Sprint 2 Deliverable

**Status:** Decision analysis only. No architecture decision in this document is approved until explicitly accepted by the Project Manager.

**Phase:** 15 — Full-Game Totals Architecture & Design
**Sprint:** Phase 15 Sprint 2 — Blocking Architecture Decision Analysis
**Date:** 2026-07-17
**Prerequisite:** Phase 15 Sprint 1 approved deliverable — `docs/FULL_GAME_TOTALS_ARCHITECTURE_AND_DESIGN.md`

---

## Repository Evidence Summary

| Item | Value |
|---|---|
| Branch inspected | `master` |
| HEAD commit | `8c478926` — "Add Edge Oracle paper bet tracker and tracking rules" |
| Architecture document inspected | `docs/FULL_GAME_TOTALS_ARCHITECTURE_AND_DESIGN.md` (Phase 15 Sprint 1, approved) |
| Database schema inspected | `database/schema.sql` |
| Migration history inspected | `database/migrations/002_add_game_weather.sql`, `003_add_team_bullpen_context.sql`, `004_add_team_injuries.sql` |
| Provider fetcher inspected | `backend/fetchers/odds_api_io.py` |
| Ingestion orchestrator inspected | `backend/scripts/save_live_data.py` |
| Research router inspected | `backend/routers/research.py` |
| Frontend workspace inspected | `frontend/app/page.tsx` |
| Market opportunity types inspected | `frontend/lib/marketOpportunities.ts` |
| Insight types inspected | `frontend/lib/researchInsights.ts` |
| Board logic inspected | `frontend/lib/marketResearchBoard.ts` |
| Board page inspected | `frontend/app/opportunities/page.tsx` |
| Opportunity tests inspected | `frontend/lib/marketOpportunities.test.ts` |
| Research endpoint tests inspected | `backend/tests/test_research_endpoints.py` |
| Diagnostic script inspected | `backend/scripts/diagnostics/check_oddsapi_totals.py` |
| Diagnostic evidence applied | Phase 13 Sprint 4 output (2026-07-17): Totals confirmed available from Bet365 and DraftKings |

**Evidence limitations:**
- Provider quota semantics (hourly vs. daily limits, cost per call) are not documented in the repository. Quota numbers cited in the architecture document ("100 requests/hour") are stated in `check_oddsapi_totals.py` as a comment but are not verified against the provider's current billing documentation.
- The actual current `ODDS_API_KEY` tier is inferred from diagnostic success, not confirmed from provider account documentation. The free tier is assumed locked to Bet365 and DraftKings based on code comments in `odds_api_io.py:47`.
- No production database was queried during this analysis.

---

## Critical Pre-Analysis Finding: Current Provider Request Behavior

**This finding affects D2 directly and is grounded in `backend/fetchers/odds_api_io.py:83-94`.**

The current production fetcher does **not** send a `markets` parameter in odds requests. The function `_get_odds_for_event(event_id)` sends only `apiKey`, `sport`, `eventId`, and `bookmakers`. The API responds with **all available markets** for that event. Market filtering is done entirely client-side: `_normalize_odds()` at line 109 applies `if market.get("name") != "ML": continue`, discarding non-ML markets before returning results.

Verified from repository code: the per-game odds call sends no server-side market filter, and the parser discards non-Moneyline markets client-side before returning results. Diagnostic evidence (Phase 13 Sprint 4, 2026-07-17, three events) confirmed that such unfiltered requests can return Totals data alongside Moneyline data from Bet365 and DraftKings. Whether Totals appear in every production ingestion response has not been verified — ingestion logs record only post-normalization Moneyline counts, no raw response payloads are saved, and the provider's default behavior for requests that omit the `markets` parameter is not documented. If OddsAPI.io changes this default behavior, Totals ingestion under Option A would silently stop producing data without raising request failures or logging errors. The D2 question therefore includes a third option beyond "separate vs. combined requests": extend local parsing to extract Totals from the same response structure, on the assumption that the provider continues to include them in unfiltered responses.

This third option is documented as Option A in D2 below and is grounded in the current production code structure and the Phase 13 Sprint 4 diagnostic evidence.

---

## D1 — Totals Database Storage Design

### 1. Decision Statement

Choose how Full-Game Totals odds (total line, over price, under price) are stored in the database to support snapshot history, line movement tracking, ingestion persistence, and research queries.

### 2. Available Options

**Option 1 — Separate `totals_history` table**

Create a new table with columns specific to Totals: `game_id`, `sportsbook`, `total_line` (NUMERIC), `over_price` (INTEGER American), `under_price` (INTEGER American), `recorded_at`.

**Option 2 — Extend `odds_history` with additional columns**

Alter the existing `odds_history` table: add a `market_type` discriminator column, add `total_line`, `over_price`, `under_price` columns, drop the `NOT NULL` constraints on `home_moneyline` and `away_moneyline`.

**Option 3 — Considered and rejected**

A hybrid approach (shared `market_lines` table polymorphically storing all market types) was considered. It is not supported by the existing pattern in this codebase, which uses dedicated tables per data type (one table per concern: `odds_history`, `game_weather`, `team_bullpen_context`, `team_injuries`). Introducing a polymorphic table would be a departure from established convention without supporting evidence.

**Cross-document note:** The Phase 15 Sprint 1 architecture document (Section 7) used different option labels for the same two viable alternatives. Sprint 1 Option A (extend `odds_history`) corresponds to Option 2 above. Sprint 1 Option B (separate `totals_history` table) corresponds to Option 1 above. Both documents recommend the separate table design; only the labels differ.

### 3. Repository Evidence

| Evidence | File / Symbol | Relevance |
|---|---|---|
| `home_moneyline INTEGER NOT NULL` | `database/schema.sql:74` | Cannot be null — adding Totals rows to this table requires `ALTER TABLE ... DROP NOT NULL` |
| `away_moneyline INTEGER NOT NULL` | `database/schema.sql:75` | Same constraint |
| No market type column | `database/schema.sql:69-82` | All rows are implicitly Moneyline |
| `DISTINCT ON (game_id, sportsbook) ORDER BY recorded_at DESC` | `backend/routers/research.py:47-52` | This query returns one row per game+sportsbook — adding mixed-market rows corrupts this without a `WHERE market_type = 'moneyline'` filter |
| `DISTINCT ON (game_id, sportsbook) ORDER BY recorded_at DESC` | `backend/routers/research.py:361-365` (game detail) | Same issue in per-game query |
| `INSERT INTO odds_history (game_id, sportsbook, home_moneyline, away_moneyline, recorded_at)` | `backend/scripts/save_live_data.py:391-397` | Hard-coded column list — would fail if Totals rows required different columns |
| Migration pattern: `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS` | `database/migrations/004_add_team_injuries.sql` | Idempotent SQL files applied manually with psql; sequential numbering (002, 003, 004) |
| One table per data concern | `database/schema.sql` | `game_weather`, `team_bullpen_context`, `team_injuries` all follow separate-table convention |
| `idx_odds_history_game_time ON odds_history (game_id, recorded_at DESC)` | `database/schema.sql:81-82` | Existing index adequate for Moneyline; a multi-market table would need `(game_id, market_type, recorded_at DESC)` |
| `RESEARCH_KEYS = {"odds", "line_movement", ...}` | `backend/tests/test_research_endpoints.py:8-17` | API contract test — "odds" key must remain in responses; adding Totals must not remove it |

### 4. Option Comparison Table

| Dimension | Option 1 (Separate table) | Option 2 (Extend odds_history) |
|---|---|---|
| Schema clarity | Each table has one semantic meaning | One table holds heterogeneous row types |
| Moneyline NOT NULL constraint | Preserved — `odds_history` unchanged | Must be dropped (`ALTER TABLE ... DROP NOT NULL`) |
| Market type column | Not needed in either table | Required in `odds_history` |
| Existing queries | All unaffected | All must add `WHERE market_type = 'moneyline'` or return wrong results |
| Regression risk to Moneyline | Low — changes are additive; regression testing required before deployment | High — DISTINCT ON queries silently mix Totals rows without filter |
| Migration complexity | `CREATE TABLE` + `CREATE INDEX` (idempotent) | `ALTER TABLE` with NOT NULL removal and new columns (harder to roll back) |
| Rollback (in isolated test env) | `DROP TABLE totals_history` — Moneyline unaffected | Must revert `ALTER TABLE`; complex if Totals rows exist |
| Transaction safety | Totals INSERT to new table; Moneyline INSERT to existing — no cross-contamination | Single table; market_type filter required throughout |
| `save_odds()` function | Unchanged | Must be updated or split |
| New persistence function | `save_totals()` — parallel to `save_odds()` | `save_odds()` must accept market type parameter |
| Research query JOIN | One new LEFT JOIN per query | Existing queries need WHERE clause additions |
| Index adequacy | New `idx_totals_history_game_time` needed | Existing index inadequate; new compound index needed |
| Line movement tracking | Same DISTINCT ON pattern on new table | Same DISTINCT ON with additional `AND market_type = ...` |
| Multi-market extensibility | Add one table per new market | Add columns and rows per new market; table grows wider and more complex |
| Test isolation | Totals tests operate on separate table | Totals and Moneyline tests share a table; filter errors can cause cross-contamination |
| Observability | `SELECT COUNT(*) FROM totals_history` gives unambiguous count | Row counts mixed; requires WHERE market_type filter |
| Data backfill | No backfill needed (new table starts empty) | `UPDATE odds_history SET market_type = 'moneyline'` required for all ~18K+ existing rows |
| Existing test contracts | `RESEARCH_KEYS` test passes unchanged | Must verify all tests still pass after query modifications |

### 5. Benefits

**Option 1 benefits:**
- Substantially reduced regression risk to the existing Moneyline data path — `odds_history` is not modified and no existing queries, functions, or tests require changes. All Totals-specific code is additive. Regression testing is required before deployment to confirm existing Moneyline behavior is unaffected by the additions.
- Clean rollback in an isolated test environment (`DROP TABLE totals_history`) with no Moneyline side effects.
- Consistent with the repository convention (one dedicated table per data concern).
- `save_odds()` remains unchanged — existing ingestion tests continue to pass.
- The `odds_history` NOT NULL constraints remain enforced, maintaining data integrity for all existing Moneyline rows.
- Future markets follow the same pattern — each gets a dedicated table, and no existing table loses clarity.

**Option 2 benefits:**
- One table for all market-type odds history, simpler JOIN in research queries.
- Uniform line-movement derivation pattern across all markets.
- One migration file rather than separate table per market.

### 6. Risks

**Option 1 risks:**
- Research queries that combine Moneyline and Totals context for the same game require a JOIN between two tables. This adds one LEFT JOIN per research query.
- As more markets are added in the future, the number of tables grows. For three or more markets, a different design might be warranted. At one additional market (Totals), this risk is minor.

**Option 2 risks:**
- All existing `odds_history` queries (`research.py:47-52`, `research.py:361-365`, `odds.py`) must be updated to add `WHERE market_type = 'moneyline'` or they silently return Totals rows alongside Moneyline rows. This is a silent correctness regression.
- Dropping `NOT NULL` on `home_moneyline` and `away_moneyline` weakens the data integrity contract for all existing Moneyline rows. These columns becoming nullable is irreversible after Totals rows are inserted.
- All existing Moneyline rows need a `UPDATE SET market_type = 'moneyline'` backfill. The 18 rows per ingestion run × 15+ days of historical data = hundreds of existing rows that need backfill.
- Migration rollback (in isolated test environment) is significantly more complex than `CREATE TABLE` rollback.

### 7. Backward-Compatibility Impact

**Option 1:** Design-level backward compatibility. `odds_history` is not modified. All existing `odds_history` queries, `save_odds()`, and ingestion functions remain unchanged. New Totals-specific code is additive — a `save_totals()` function and LEFT JOIN extensions to research queries. The `RESEARCH_KEYS` API contract shape is expected to remain valid without modification. All compatibility expectations must be confirmed by running the existing test suite during implementation.

**Option 2:** Requires modifying every existing `odds_history` query to add a market type filter. The `RESEARCH_KEYS` test remains structurally valid but the underlying queries must be updated to avoid incorrect results.

### 8. Future Extensibility Impact

**Option 1:** Each future market (run line, first-5-innings totals) follows the same pattern — a new dedicated table. Simple to reason about, no existing table becomes more complex. The cost is one LEFT JOIN per additional market in research queries.

**Option 2:** Each future market adds columns and mixed row types to `odds_history`. The table grows in both width (new columns) and row complexity (nullable columns per market type). At three or more markets this becomes difficult to maintain.

### 9. Recommended Option

**Recommendation: Option 1 — Separate `totals_history` table.**

This recommendation is advisory only and requires Project Manager approval.

**Primary reason:** The existing `odds_history` NOT NULL constraints on `home_moneyline` and `away_moneyline` are not a historical accident — they correctly reflect the Moneyline data model. Weakening those constraints for a secondary market introduces both data-integrity risk and silent query-correctness risk across every existing `odds_history` query. A separate table eliminates both risks at the cost of one additional LEFT JOIN in research queries.

**Secondary reason:** The repository's established convention is one dedicated table per data concern. `game_weather`, `team_bullpen_context`, and `team_injuries` each have dedicated tables. `totals_history` follows this convention; extending `odds_history` does not.

### 10. Consequences of the Recommendation

If Option 1 is approved:
- A migration file `database/migrations/005_add_totals_history.sql` must be created and applied to the live database before any Totals ingestion can run.
- A new `save_totals()` function is needed in `save_live_data.py`.
- Research queries require one new LEFT JOIN on `totals_history`.
- `save_odds()`, all existing `odds_history` queries, all existing tests, and all existing API response shapes remain unchanged.

### 11. Blocking Classification

**Blocking before any implementation.**

The database storage design must be decided and the migration applied before any persistence, ingestion, or API implementation can function. No Totals rows can be stored without the table or schema extension.

### 12. Exact Project Manager Approval Question

> Does the Project Manager approve creating a separate `totals_history` table (Option 1) as the storage design for Full-Game Totals odds snapshots, subject to a separately authorized implementation phase?

---

## D2 — Provider Request Strategy

### 1. Decision Statement

Choose how Full-Game Totals market data is obtained from OddsAPI.io — whether to extend the parsing of the existing per-game odds request, use a separate request with a `markets` filter, or use a combined request with an explicit markets parameter.

### 2. Available Options

**Option A — Single request, parse both markets locally (extension of current behavior)**

Continue calling `_get_odds_for_event(event_id)` with no `markets` parameter. The API already returns all available markets in this call. Extend `_normalize_odds()` (or create a parallel `_normalize_totals()`) to parse `"Totals"` markets from the same response that is already being retrieved. No additional API calls are made.

**Option B — Separate requests (`markets='ML'` for Moneyline, `markets='totals'` for Totals)**

Add a `markets` parameter to `_get_odds_for_event()`. Call it twice per game — once filtering for ML, once filtering for totals. Each call filters server-side, returning only the requested market type.

**Option C — Combined explicit request (`markets='ML,totals'`)**

Add a single `markets='ML,totals'` parameter to one call per game, explicitly requesting both markets in one request.

### 3. Repository Evidence

| Evidence | File / Symbol | Relevance |
|---|---|---|
| `_get_odds_for_event(event_id)` sends NO `markets` param | `backend/fetchers/odds_api_io.py:83-94` | Current behavior: all markets returned from single request |
| `if market.get("name") != "ML": continue` | `backend/fetchers/odds_api_io.py:109` | Client-side filter — Totals data already arrives and is discarded |
| `markets='totals'` — HTTP 200 confirmed | Phase 13 Sprint 4 diagnostic (2026-07-17) | Server accepts the parameter |
| `markets='ML,totals'` — HTTP 200 confirmed | Phase 13 Sprint 4 diagnostic (2026-07-17) | Server accepts combined parameter |
| `response.raise_for_status()` | `backend/fetchers/odds_api_io.py:93` | No retry logic; a failed request throws immediately |
| `try: odds_records = odds_api_io.get_moneyline_odds()` / `except RuntimeError` | `backend/scripts/save_live_data.py:426-431` | Failure sets `odds_records = []`; ingestion continues |
| Rate limit comment: "free tier allows 100 requests/hour" | `backend/scripts/diagnostics/check_oddsapi_totals.py:36` | Comment in code; not verified against provider billing docs |
| Current call volume | `logs/ingestion.log` (latest blocks) | ~1 events call + 15–18 odds calls per run = ~16–19 total per run; two runs/day |
| No backoff or retry logic | `backend/fetchers/odds_api_io.py` | All requests single-attempt; partial failure is not retried |
| `BOOKMAKERS = "Bet365,DraftKings"` | `backend/fetchers/odds_api_io.py:48` | Both sportsbooks confirmed to return Totals in diagnostic |
| Totals data confirmed in response | Phase 13 Sprint 4 diagnostic | `{'name': 'Totals', 'odds': [{'hdp': 8.5, 'over': '1.90', 'under': '1.90'}]}` |

### 4. Option Comparison Table

| Dimension | Option A (Single request, parse locally) | Option B (Separate requests) | Option C (Combined explicit request) |
|---|---|---|---|
| Additional API calls per game | 0 | +1 per game | 0 |
| Calls per ingestion run | ~16–19 (unchanged) | ~31–37 | ~16–19 (unchanged) |
| Calls per day (2 runs) | ~32–38 (unchanged) | ~62–74 | ~32–38 (unchanged) |
| Matches current behavior | Yes — extends existing pattern | No — changes parameter behavior | No — adds explicit markets param |
| Per-market failure isolation | Poor — one call, both markets parse or both fail | Best — Moneyline and Totals fail independently | Poor — one call, both markets |
| Parsing complexity | One call, one parser per market name | One call per market, one parser per call | One call, two parsers or one combined parser |
| If Totals temporarily disappears | `_normalize_totals()` returns [] gracefully | Totals call fails; Moneyline call unaffected | Combined call returns only ML; Totals parsing returns [] |
| If Moneyline temporarily disappears | ML parser returns []; Totals parser unaffected | ML call fails; Totals call unaffected | Combined call returns only Totals; ML parsing returns [] |
| Backward compatibility | Highest — no change to ML request | Good — ML request now explicit | Good — combined request replaces current no-filter |
| Quota cost increase | None | ~2× current | None |
| Quota risk | None | Moderate (~62–74 calls/day) | None |
| Stale-snapshot risk | Both markets share one `recorded_at` | Each market has its own `recorded_at` | Both markets share one `recorded_at` |
| Implementation change required | Minimal — extend `_normalize_odds()` or add `_normalize_totals()` parsing the same response | Significant — parameterize `_get_odds_for_event()`, add second call per game | Moderate — add `markets` parameter; parse both from combined response |
| Debugging if data is missing | One response to inspect | Two responses to inspect (one per market) | One response to inspect |

### 5. Benefits

**Option A benefits:**
- Zero additional API calls, if the provider continues including Totals in unfiltered responses. The production fetcher sends no `markets` parameter and the parser discards non-Moneyline markets client-side. Diagnostic evidence confirmed that unfiltered requests can return Totals data; consistent Totals inclusion in production ingestion responses has not been independently verified from ingestion logs or saved payloads.
- No change to the provider request contract — the same no-markets-parameter call continues.
- Lowest implementation risk.
- Both markets share one `recorded_at` timestamp, which is the fetch time — consistent with current `_normalize_odds()` behavior.

**Option B benefits:**
- Each market fails independently. A transient Totals API error does not affect Moneyline ingestion and vice versa.
- Cleaner conceptual separation of market-specific fetchers.
- Each market call is independently auditable in logs.

**Option C benefits:**
- One call per game (same as current), explicit about what markets are requested.
- Server-side filtering may reduce response payload size (though this is an operational unknown — provider payload behavior is not documented in the repository).

### 6. Risks

**Option A risks:**
- Failure isolation is weaker: a network failure or `raise_for_status()` failure on the shared request affects both markets for that game.
- In practice, the current code already handles this — if `get_moneyline_odds()` fails, `odds_records = []` and ingestion continues. The same failure would also produce `totals_records = []`.
- If the provider ever begins requiring explicit `markets` parameters, Option A will silently receive fewer markets. This is an operational unknown.

**Option B risks:**
- Approximately doubles API calls per game. At the stated 100 requests/hour limit (operational unknown — not verified against billing docs), two runs of 37 calls each (74/day) remains well within hourly limits but introduces more quota dependence.
- **Operational unknown:** The provider's actual quota semantics (hourly vs. monthly, cost per request) are not documented in the repository. The 100/hour figure appears as a code comment only.
- Requires parameterizing `_get_odds_for_event()`, which changes the interface of a function used in the production ingestion path.

**Option C risks:**
- If Totals become unavailable on the provider, the combined request's behavior is unclear — it may return only ML or return an error. This behavior is not documented in the repository and was not tested in the diagnostic.
- Adds explicit coupling between Moneyline and Totals in a single API parameter.

### 7. Recommended Option

**Recommendation: Option A — Single request, parse both markets locally.**

This recommendation is advisory only and requires Project Manager approval.

**Primary reason:** The production code currently sends no `markets` parameter, and the parser discards non-Moneyline markets client-side. Diagnostic evidence confirmed that such unfiltered requests can return Totals data alongside Moneyline data. Option A extends local parsing to extract Totals from the same response structure — the lowest-complexity extension of existing behavior, at no additional API cost — on the assumption that the provider continues to include Totals in unfiltered responses. This assumption must be validated during implementation before production deployment.

**Secondary reason:** Options B and C both require changing the provider request interface. Option A requires only adding a parallel local parsing function — the lowest-risk change to an already-working system.

**Required safeguards for Option A:**
- `_normalize_totals()` must return `[]` gracefully when no `"Totals"` market appears in the response (already handled by the market-name filter pattern).
- Logging must distinguish Totals records parsed from Moneyline records parsed, even though they come from the same response.
- If the provider introduces a `markets` parameter requirement in the future, Option A will need to be revised.

### 8. API-Rate and Reliability Implications

**Option A:** No additional quota consumption. If the single per-game request fails, both Moneyline and Totals parsing for that game fail. This is the same failure mode as the current system.

**Operational unknown (all options):** The actual OddsAPI.io quota semantics — hourly limit, daily limit, cost per request, and tier capabilities — are not documented in the repository. The 100/hour figure cited in `check_oddsapi_totals.py` is a comment, not a verified contract. Any decision about quota risk should be verified against the provider's current account documentation before implementation.

### 9. Blocking Classification

**Material but non-blocking for early backend work.**

The D2 decision does not block the database migration (D1). It also does not block writing and testing the Totals normalization and parsing functions — those can be unit-tested with fixtures from the Phase 13 Sprint 4 diagnostic output. D2 becomes blocking before wiring the Totals fetch into `save_live_data.py::main()`.

### 10. Exact Project Manager Approval Question

> Does the Project Manager approve Option A (extending local parsing of the existing per-game odds response to extract both Moneyline and Totals data, without adding a `markets` parameter to the API request) as the provider request strategy for Full-Game Totals ingestion, subject to a separately authorized implementation phase?

---

## D3 — MarketType Representation (Resolved in Sprint 1, Excluded from This Document)

D3 was fully resolved in the Phase 15 Sprint 1 architecture document (Section 19). It does not require Project Manager approval and is not implementation-blocking. This document intentionally focuses on decisions that are either blocking or require explicit PM approval before implementation begins. D3 meets neither criterion and is excluded from this analysis.

**Sprint 1 resolution:** Extend the `MarketType` string literal union to add `"FULL_GAME_TOTALS"` as a union member. Converting to a TypeScript enum is not required. No PM approval required. No implementation blocked.

---

## D4 — Workspace Identity Model

### 1. Decision Statement

Determine whether the workspace (the researcher's shortlist of games for deeper study) should store entries at the game level, the game-and-market level, or the specific-betting-selection level.

### 2. Available Options

**Option 1 — One workspace entry per game (current model)**

The workspace stores `game_id: number`. A single entry represents "this game is in my research shortlist." The researcher uses the notes textarea (keyed by `game_id`) to record which market and side they are examining.

**Option 2 — One workspace entry per game and market**

The workspace stores a composite key, e.g., `{game_id: number, market: "FULL_GAME_MONEYLINE" | "FULL_GAME_TOTALS"}`. A separate entry is created for each market of interest. Notes are keyed by the composite key.

**Option 3 — One workspace entry per specific betting selection**

The workspace stores a selection including game, market, side/direction, line, sportsbook, and optionally price. This represents "I intend to consider this specific offer."

### 3. Repository Evidence

| Evidence | File / Symbol | Relevance |
|---|---|---|
| `WORKSPACE_STORAGE_KEY = "mlb_workspace_ids"` | `frontend/app/page.tsx:109` | Stores JSON array of `game_id` numbers |
| `workspaceIds: Set<number>` | `frontend/app/page.tsx:411` | Identity is a number (game_id); no market type |
| `addToWorkspace(gameId: number)` | `frontend/app/page.tsx:430` | Adds game_id to the Set |
| `JSON.stringify([...next])` | `frontend/app/page.tsx:433` | Persisted as JSON array of numbers |
| `notes: Record<number, string>` | `frontend/app/page.tsx:414` | Notes keyed by game_id (number) |
| `NOTES_STORAGE_KEY = "mlb_workspace_notes"` | `frontend/app/page.tsx:110` | Separate localStorage key for notes |
| `compareIdA: number | null`, `compareIdB: number | null` | `frontend/app/page.tsx:412-413` | Comparison pair identified by game_id only |
| Auto-select comparison pair when 2 workspace entries | `frontend/app/page.tsx:464-471` | Comparison auto-populated at game level |
| `ComparisonTable({ a, b }: { a: Game; b: Game })` | `frontend/app/page.tsx:269` | Comparison operates on full Game objects |
| `removeFromWorkspace(gameId: number)` clears compareIdA/B | `frontend/app/page.tsx:451-460` | Comparison state tied to game_id identity |
| `CAUTION_NOTES`: "This is not a betting recommendation" | `frontend/lib/marketOpportunities.ts:29` | System does not produce selection-level outputs |
| `MarketOpportunity` has no `side`, `line`, `sportsbook` | `frontend/lib/marketOpportunities.ts:5-15` | Opportunity is market-level, not selection-level |
| `formDivergenceToMoneyline` produces one opportunity per game | `frontend/lib/marketOpportunities.ts:34-58` | Market-level opportunity, no team-side field |
| Comparison table sections: Odds (Away/Home), Line Movement | `frontend/app/page.tsx:378-395` | All Moneyline-specific; game-level comparison |

### 4. Product Distinction

The workspace can serve three conceptually distinct purposes, and the correct identity model depends on which purpose the PM intends:

| Purpose | Description | Appropriate Identity |
|---|---|---|
| **Game-level research** | "I want to research this game further" | `game_id` |
| **Market-level research** | "I want to research this game's Totals market specifically" | `game_id + market_type` |
| **Selection-level tracking** | "I am considering Over 8.5 at Bet365 for -111 in this game" | `game_id + market + direction + line + sportsbook` |

The current workspace serves purpose 1. Adding Totals to the system does not automatically require changing to purpose 2 or 3 — but it creates the possibility that a researcher wants to shortlist the same game for Moneyline research and Totals research independently.

### 5. Option Comparison Table

| Dimension | Option 1 (Game-level) | Option 2 (Game + Market) | Option 3 (Selection-level) |
|---|---|---|---|
| Current identity key | `game_id: number` | `{game_id, market_type}` | `{game_id, market, direction, line, sportsbook}` |
| Existing workspace data migration | None required | All existing entries need market_type added | Destructive — incompatible with existing data |
| localStorage format change | None | Breaking — existing `[1,2,3]` becomes `[{...},{...}]` | Breaking |
| Backward compatibility | Complete | Requires migration logic for existing stored arrays | None — incompatible |
| Duplicate prevention | Already handled by `Set<number>` | Must handle `{game_id: 1, market: "ML"}` and `{game_id: 1, market: "TOTALS"}` as distinct entries for same game | Complex deduplication logic |
| Notes model | `Record<number, string>` | `Record<string, string>` (composite key as string) | Complex nested structure |
| Comparison model | Game-level (`Game` objects) | Game-level (comparison is still game-level) | Would need redesign |
| Auto-select comparison pair | Works when 2 entries | Works when 2 game-distinct entries; breaks with 2 entries for same game/different markets | Would need redesign |
| Researcher workflow | One entry to add to shortlist per game | Must choose market at shortlist time | Must choose specific offer at shortlist time |
| User clarity | High — one action per game | Moderate — same game can appear twice | Low for research, high for selection |
| Stale entry risk | None | If market type changes name, entries become stale | High — line, price, sportsbook can all change |
| Future markets (run line) | No change required | `"FULL_GAME_RUN_LINE"` added to market union | Requires new selection-level fields |
| Implementation complexity | None — no change | Moderate — localStorage migration + composite key | High |
| Alignment with "no recommendations" principle | High — game-level research | High — market-level research | Ambiguous — selection-level risks appearing prescriptive |

### 6. Recommended Option

**Recommendation: Option 1 — Game-level identity, unchanged from current model.**

This recommendation is advisory only and requires Project Manager approval.

**Primary reason:** The workspace is currently a research shortlist, not a market or selection tracker. Adding Totals to the system is a backend and research data change — it does not inherently require changing what the workspace represents. A researcher can shortlist a game for Totals review using the same workspace entry, then use the notes textarea to record "Totals: O/U 8.5, watching wind direction."

**Secondary reason:** Option 2 requires migrating existing localStorage data. Any existing user workspace entries (stored as `[gameId1, gameId2, ...]`) would be incompatible with a new `[{game_id, market_type}, ...]` format. This migration must happen client-side in JavaScript when the component mounts, which is a silent data-format change that could lose existing saved data if the migration logic fails. The risk is disproportionate to the benefit for MVP.

**Conditions under which this recommendation should change:** If the PM determines that the workspace should serve a market-tracking purpose (i.e., "I want to track which markets I have shortlisted, not just which games"), Option 2 becomes appropriate. This is a product definition decision, not a technical one.

### 7. Persistence Consequences

**Option 1:** No change. Existing `mlb_workspace_ids` array of numbers and `mlb_workspace_notes` object remain valid. No migration code needed.

**Option 2:** The localStorage format changes. A migration function is needed to convert `[1, 2, 3]` to `[{game_id: 1, market: "FULL_GAME_MONEYLINE"}, ...]`. If this migration fails silently, the researcher loses their workspace. Notes keyed by number (`{1: "text"}`) must be re-keyed to the composite string form.

**Option 3:** Incompatible with existing data. All existing workspace entries are lost without a migration strategy.

### 8. Backward-Compatibility Consequences

**Option 1:** Design-level backward compatibility. Under Option 1, no workspace code changes are required and the existing localStorage format is preserved. Existing saved workspace entries remain valid. Future frontend implementation work in the same files must be carefully scoped to avoid inadvertent effects on workspace behavior when Totals UI is introduced.

**Option 2:** Breaking for existing stored data. Requires client-side migration logic executed at page load.

**Option 3:** Breaking. Existing data is incompatible.

### 9. Future Migration Risk

If Option 1 is implemented for MVP and Option 2 is desired later, the migration from game-level to market-level is possible — it requires writing a localStorage migration that replaces each stored number with `{game_id: N, market: "FULL_GAME_MONEYLINE"}` (defaulting to Moneyline for all existing entries). This migration is straightforward and reversible. The risk of doing the migration later is lower than doing it now when it provides no workflow benefit over Option 1.

### 10. Blocking Classification

**Material but non-blocking for early backend work.**

D4 does not block database, provider, ingestion, or backend API work. It becomes blocking only before workspace-related frontend implementation begins. Given Option 1's recommendation of "no change," it does not block any frontend work either — the workspace requires no modification under Option 1.

### 11. Exact Project Manager Approval Question

> Does the Project Manager approve maintaining the current game-level workspace identity model (one entry per `game_id`, no market type in the identity key) for the Full-Game Totals MVP, subject to a separately authorized future migration if market-level workspace tracking is later required?

---

## D5 — Opportunity Side/Direction Model

### 1. Decision Statement

Determine whether a Full-Game Totals market opportunity should include an explicit `direction` or `side` field representing "over" or "under," and what that field would mean architecturally.

### 2. Available Options

**Option 1 — Market-level opportunity, no explicit direction field**

The opportunity identifies the market type (`"FULL_GAME_TOTALS"`) but does not include a `direction` field. Supporting evidence (run differential, wind, precipitation) is encoded in the `reasons` array as text. The researcher reads the evidence and decides which side, if any, to examine.

**Option 2 — Market opportunity with explicit direction field**

Add a `direction: "over" | "under"` field to `MarketOpportunity`. The opportunity states which side the supporting evidence points toward, while caution notes clarify this is not a recommendation.

**Option 3 — Separate market opportunity and selection representation**

Maintain a market-level `MarketOpportunity` for research identification, and separately introduce a "potential selection" type that includes direction, line, sportsbook, and price. The selection type is a structured research note, not a recommendation.

### 3. Repository Evidence

| Evidence | File / Symbol | Relevance |
|---|---|---|
| `MarketOpportunity` type: no direction/side field | `frontend/lib/marketOpportunities.ts:5-15` | Current Moneyline type sets the pattern |
| `CAUTION_NOTES`: "This is not a betting recommendation." | `frontend/lib/marketOpportunities.ts:29` | Explicit disclaimer |
| `CAUTION_NOTES`: "This does not calculate expected value or fair odds." | `frontend/lib/marketOpportunities.ts:30` | No EV or fair-odds calculation |
| `formDivergenceToMoneyline` produces no `side` field | `frontend/lib/marketOpportunities.ts:34-58` | The team-side that is hot/cold appears in the `description` text on the insight, not as a typed field on the opportunity |
| `summary` and `reasons` are strings | `frontend/lib/marketOpportunities.ts:9-11` | Side-relevant evidence can be expressed in reasons text without a typed direction field |
| `marketType: "FULL_GAME_MONEYLINE"` | `frontend/lib/marketOpportunities.ts:3` | Pattern: market type is the typed identity, not a side |
| Opportunity board shows `Away ML / Home ML` | `frontend/app/opportunities/page.tsx:337-340` | Board displays both sides' prices without marking which is favored |
| `gameId: String(game.game_id ?? "")` | `frontend/lib/marketOpportunities.ts:43` | Opportunity identity is game + market, not game + market + side |
| Caution note test | `frontend/lib/marketOpportunities.test.ts:78-84` | Tests verify "not a betting recommendation" disclaimer is present |
| `entry.opportunity.marketType.replace(/_/g, " ")` | `frontend/app/opportunities/page.tsx:259` | Market type label renders automatically; "FULL GAME TOTALS" works without code change |
| `sourceInsightIds: string[]` | `frontend/lib/marketOpportunities.ts:13` | Traceability to source insights already provided without direction field |

### 4. Architectural Distinction

The PM's brief correctly identifies that a `direction` field can represent different things:

| What `direction` represents | Scope | Appropriate? |
|---|---|---|
| A descriptive market outcome under research ("The over side has weather-supporting evidence") | Research aid | Yes — within scope |
| A selected sportsbook offer ("I intend to examine Over 8.5 at Bet365") | Research note | Yes — within scope as a workspace annotation |
| A system-generated recommendation ("The system recommends Over") | Prediction/recommendation | No — explicitly out of scope; would violate caution notes and research-only design |

Options 1 and 2 both remain within the research-aid scope if implemented carefully. Option 3's "selection representation" is within scope only if it is a structured workspace note, not a system output.

### 5. Option Comparison Table

| Dimension | Option 1 (Market-level, no direction) | Option 2 (Direction field) | Option 3 (Separate market + selection) |
|---|---|---|---|
| Consistent with Moneyline pattern | Yes — Moneyline has no side/direction field | No — Moneyline has no equivalent | Partially — adds a new representation type |
| `MarketOpportunity` type change | None | Add `direction: "over" \| "under"` | None to MarketOpportunity; new Selection type |
| API contract change | None | `MarketOpportunity` shape changes | None to MarketOpportunity |
| Backward compatibility | Expected — no direction fields added; MarketType expansion required when Totals are added; tests must be verified | Breaks any consumer that expects a fixed `MarketOpportunity` shape | Expected for MarketOpportunity; new Selection type adds implementation surface |
| Caution note alignment | Naturally market-level; no implied recommendation | Risk: direction field may appear prescriptive even with caution notes | Naturally market-level; selection is explicit research note |
| Explainability | Evidence in `reasons` strings | Evidence in `reasons` strings + direction typed | Evidence in `reasons` strings |
| Auditability | Opportunity links to source insight IDs | Same plus typed direction | Same |
| Board display | Render over and under prices side by side | Could highlight the direction indicated | Board unchanged; selection shown separately |
| Multiple sportsbooks with different lines | Board shows all lines; researcher compares | Direction applies to market, not to a specific line | Selection can reference specific sportsbook |
| If evidence points both ways | One opportunity with mixed reasons | Two opportunities (one over, one under)? Or one with direction null? | One market opportunity + no selection |
| Implementation complexity | Low | Moderate — generator must determine direction from evidence | High — new type, new UI section |
| Risk of appearing as recommendation | Low | Moderate — typed direction is more prescriptive than text reasons | Low for market opp; moderate for selection |

### 6. Recommended Option

**Recommendation: Option 1 — Market-level opportunity with no explicit direction field.**

This recommendation is advisory only and requires Project Manager approval.

**Primary reason:** The Moneyline pattern establishes that opportunities identify a market, not a side. The `formDivergenceToMoneyline` generator fires when a hot team is priced as an underdog, but the opportunity does not carry a `side: "home" | "away"` field — the team name appears in the `description` string of the triggering insight, and the researcher reads it. The analogous Totals pattern is: evidence suggesting high-scoring conditions fires a "FULL_GAME_TOTALS" opportunity whose `reasons` array includes "Wind blowing out at 15 mph WSW" and "Both offenses ranked in top 5 by run differential last 10 games." The researcher reads the reasons and determines whether the evidence supports over research. No `direction` field is needed for this to be informative.

**Secondary reason:** Adding a `direction: "over" | "under"` field to `MarketOpportunity` changes the type contract for a type that currently has no side-direction concept. This change would need to be backward-compatible for Moneyline opportunities — Moneyline opportunities would either not carry the field (optional) or always carry `direction: null`, introducing a type inconsistency.

**Conditions under which this recommendation should change:** If the PM wants the board to visually distinguish over-supporting from under-supporting opportunities (e.g., green "Over" vs. blue "Under" chips), a typed `direction` field becomes necessary and Option 2 is appropriate. This is a UX product decision.

### 7. Proposed Conceptual Identity Fields for Totals Opportunities

Under Option 1, a Totals opportunity would be conceptually identified by:
- `gameId`: the game
- `marketType: "FULL_GAME_TOTALS"`: the market
- `id`: a generator-specific stable string (e.g., `"run-diff-totals"`)

The evidence (run differential, wind, precipitation) is encoded in `reasons: string[]`. The researcher uses this to decide whether to examine the over, under, or neither.

Under Option 2, the identity adds:
- `direction: "over" | "under"`: the direction the evidence points toward

Both options support `sourceInsightIds` for traceability to source insights.

### 8. Explainability and Auditing Consequences

**Option 1:** The audit trail is: `sourceInsightIds` → specific `ResearchInsight.id` values → insight descriptions that name the specific data points. The researcher can trace from opportunity → insight → evidence without a `direction` field.

**Option 2:** The audit trail is the same, plus the `direction` field declares which direction was inferred. This is more auditable for the generator's logic but risks appearing as a system recommendation.

### 9. Backward-Compatibility Consequences

**Option 1:** No new fields are added to the `MarketOpportunity` struct under this recommendation. However, adding Totals support will require an additive expansion of the `MarketType` union type — from the current single-value `"FULL_GAME_MONEYLINE"` to a union that includes `"FULL_GAME_TOTALS"`. This is expected to be non-breaking for existing Moneyline code but is a type-level code change. The board's `marketType.replace(/_/g, " ")` pattern is expected to render "FULL GAME TOTALS" without additional changes. No tests were executed during Phase 15 Sprint 2; all compatibility expectations must be confirmed by running the existing test suite during implementation.

**Option 2:** `MarketOpportunity` gains a new field. Existing Moneyline opportunities must either have `direction: null` or the field must be optional (`direction?: "over" | "under"`). The test `expect(opp.marketType).toBe("FULL_GAME_MONEYLINE")` passes, but any test checking the shape of the entire opportunity object may need updating.

### 10. Over/Under Direction Across the System

Recommending no explicit direction field on `MarketOpportunity` does not imply that over/under direction is absent from the broader system or that the broader application remains unchanged. The D5 decision governs only the typed structure of the opportunity object in `marketOpportunities.ts`. Direction as a concept is present at multiple other layers, each of which requires its own design and implementation as part of the Totals feature.

| Layer | Over/Under present? | Notes |
|---|---|---|
| Provider offer (raw API response) | Yes — `hdp`, `over`, `under` fields | OddsAPI.io Totals market structure; present regardless of D5 |
| Database storage (`totals_history`) | Yes — `over_price` and `under_price` columns | Required by D1 Option 1; present regardless of D5 |
| Backend API response | Yes — both prices returned to frontend | Researcher needs both to evaluate the line; present regardless of D5 |
| Market identity (`MarketType` union) | Additive expansion required — `"FULL_GAME_TOTALS"` must be added | Required regardless of D5; see note below |
| Board display (frontend) | Yes — displayed as "O 8.5 -110 / U 8.5 -110" or equivalent | Required for researcher to compare prices; present regardless of D5 |
| Opportunity `reasons` text | Implicitly present — evidence strings describe over/under-relevant factors | Direction implied by text; not typed; this is the D5 decision boundary |
| Workspace notes | User-authored text | Researcher records direction intent in the notes textarea |
| Comparison table | Present as display values | A Totals comparison section would show both over and under prices per sportsbook |

**MarketType expansion note:** Regardless of whether a direction field is added, adding Totals to the opportunity system requires `"FULL_GAME_TOTALS"` to be added to the `MarketType` union in `frontend/lib/marketOpportunities.ts`. The current union is a single string literal: `export type MarketType = "FULL_GAME_MONEYLINE"`. Expanding it to include `"FULL_GAME_TOTALS"` is an additive type change that is expected to be non-breaking for existing Moneyline code. This expansion is a prerequisite for any Totals opportunity implementation — it is not a consequence of D5 alone.

**D5 decision scope:** The D5 decision determines only whether a typed `direction: "over" | "under"` field exists on the `MarketOpportunity` object. It does not govern direction representation at the provider, database, API, display, workspace, or comparison layers. Each of those layers will require its own design and implementation decisions, which are outside the scope of D5 and are not resolved by it.

### 11. Blocking Classification

**Material but non-blocking for early backend and database work.**

D5 does not block the database migration, provider parsing, ingestion, or research router. It becomes blocking before the opportunity generator for Totals is implemented in `marketOpportunities.ts`.

### 12. Exact Project Manager Approval Question

> Does the Project Manager approve implementing Full-Game Totals market opportunities without an explicit direction field (Option 1), presenting evidence in `reasons` strings and allowing the researcher to determine which side the evidence supports, consistent with the existing Moneyline opportunity pattern — subject to a separately authorized implementation phase?

---

## Blocking vs. Non-Blocking Classification Summary

| Decision | Classification | Future Work Blocked | Why | PM Approval Timing |
|---|---|---|---|---|
| D1 — Database storage | **Blocking before any implementation** | Database migration; persistence functions; ingestion wiring; research router query extension; any Totals API endpoint | No Totals row can be stored without the table or schema extension; all downstream implementation depends on this choice | Must be approved before any implementation phase is authorized |
| D2 — Provider request strategy | **Material, non-blocking for early backend work** | Provider client implementation; ingestion wiring; end-to-end testing | Does not block migration (D1), parser unit tests (using fixtures), or research router design; blocks wiring the fetch into `main()` | Must be approved before the ingestion persistence implementation stage |
| D4 — Workspace identity | **Advisory — non-blocking under recommended Option 1** | Workspace frontend implementation only | If Option 1 approved: zero implementation impact — no workspace code changes needed; if Option 2 approved: blocks frontend workspace work | May be approved concurrently with or after D1/D2; blocks only workspace-related frontend work |
| D5 — Opportunity direction | **Material, non-blocking for early backend and database work** | Opportunity generator implementation; board display for Totals entries | Does not block D1, D2, D4, or any backend/ingestion work; blocks generator and board code only | Must be approved before the opportunity layer implementation stage |

---

## Assumptions and Unresolved Conflicts

### Assumptions

1. **Provider quota semantics:** The 100 requests/hour quota limit is stated as a comment in `check_oddsapi_totals.py:36` but is not verified against current provider billing documentation. All quota calculations in this analysis use that figure as stated.

2. **Provider tier stability:** The free tier is assumed locked to Bet365 and DraftKings based on `odds_api_io.py:47` ("Free tier accounts are locked to exactly 2 sportsbooks, set on first use."). This tier may have changed since the account was configured.

3. **Option A response stability (D2):** The analysis assumes that OddsAPI.io will continue to return all markets in an unfiltered request (no `markets` parameter). If the provider changes this behavior to require explicit `markets` parameters, Option A will need to be revised.

4. **Diagnostic data representativeness:** The Phase 13 Sprint 4 diagnostic checked 3 events on 2026-07-17. Totals availability on all games, all days, and across all provider configurations is assumed to be consistent with the diagnostic sample.

### Missing Evidence

- Provider billing documentation: hourly vs. daily request limits, cost per request, behavior at limit.
- Provider API contract for behavior when `markets` parameter is absent vs. present.
- Any provider documentation on when/how market availability may change (e.g., close to game time).

### Repository / Document Conflicts

- The Phase 15 Sprint 1 architecture document (Section 19 D2) describes the decision as "Separate requests (`markets='ML'`) vs. Combined requests (`markets='ML,totals'`)" — a two-option framing that did not account for the current production code's no-markets-parameter behavior. This analysis introduces Option A (no parameter, parse locally) as a genuinely evidenced third option.
- `docs/MARKET_RESEARCH_ARCHITECTURE.md` Section 1.5 notes Totals as absent; Section 2.2 describes Totals as "BLOCKED." These sections are now stale following the Phase 13 Sprint 4 diagnostic confirmation. Updating those sections is a separate documentation task, not in scope for this sprint.

### Product Questions

- **D4:** Whether the workspace should serve a game-level research purpose or a market-level research tracking purpose is a product definition decision that cannot be answered purely from repository evidence.
- **D5:** Whether the board should visually distinguish over-supporting from under-supporting evidence (which would require a typed `direction` field) is a UX product decision.

### Operational Unknowns

- Provider rate limit verification (see assumptions above).
- Provider behavior when Totals become unavailable for a specific event (e.g., after line pull close to game time).

---

## Scope Compliance Confirmation

| Item | Status |
|---|---|
| No Totals implementation | Confirmed |
| No backend code changes | Confirmed |
| No frontend code changes | Confirmed |
| No database model changes | Confirmed |
| No migrations created | Confirmed |
| No ingestion changes | Confirmed |
| No provider request changes | Confirmed |
| No MarketType values added | Confirmed |
| No endpoints added or changed | Confirmed |
| No UI added | Confirmed |
| No tests added | Confirmed |
| No scheduler changes | Confirmed |
| No unrelated decisions resolved | Confirmed |
| No commit | Confirmed |
| No push | Confirmed |

---

*All claims in this document are grounded in direct inspection of repository files at commit `8c478926` and confirmed Phase 13 Sprint 4 diagnostic output from 2026-07-17. No architecture decisions have been resolved or approved by this document. Project Manager approval is required for each decision before any implementation phase may begin.*
