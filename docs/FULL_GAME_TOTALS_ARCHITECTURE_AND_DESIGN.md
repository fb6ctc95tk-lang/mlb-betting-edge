# Full-Game Totals Architecture and Design
## MLB Betting Edge — Phase 15 Sprint 1 Deliverable

**Status:** Architecture and design only. No implementation has occurred.
**Phase:** 15 — Full-Game Totals Architecture & Design
**Sprint:** Phase 15 Sprint 1 — Repository inspection, architecture, and documentation only
**Date:** 2026-07-17
**Based on:** Direct inspection of all relevant repository files as of commit `8c478926`

---

## 1. Executive Summary

### Current Supported Market

Full-Game Moneyline is the only supported betting market. Moneyline odds are fetched from OddsAPI.io for Bet365 and DraftKings, stored in `odds_history`, surfaced through the research API, and presented on the dashboard, game detail page, and Market Research Board. Two research insight generators are active. One market opportunity generator is active.

### Confirmed But Unsupported Totals Provider Capability

On 2026-07-17, a controlled diagnostic (Phase 13 Sprint 4) confirmed that OddsAPI.io returns Full-Game Totals markets from both Bet365 and DraftKings under the market name `"Totals"`. The response structure includes a `hdp` field (the total run line), `over` (decimal odds string), and `under` (decimal odds string). The `markets='totals'` and `markets='ML,totals'` API filter parameters are accepted with HTTP 200. No provider change, tier upgrade, or new credentials are required.

### Purpose of This Document

This document describes the proposed architecture for Full-Game Totals integration. It is grounded entirely in verified repository inspection. It distinguishes design from implementation: no code has been written, no schema has been migrated, and no sprint has been authorized beyond this design document.

### Key Architectural Recommendation

Extend the existing pipeline with a parallel Totals data path rather than forcing Totals into the existing Moneyline structures. The `odds_history` table must be replaced or extended to carry a market type discriminator and market-specific fields (total line, over/under prices). The fetcher, persistence layer, research router, API response shapes, frontend types, and opportunity layer all require targeted extension — not wholesale redesign. Market-neutral contracts should be introduced where justified by actual sharing, not speculatively.

### Key Unresolved Decisions

- Whether to extend `odds_history` with nullable Totals columns versus introduce a new `totals_history` table (see Section 7).
- Whether combined `markets='ML,totals'` requests or separate per-market requests better serve quota and partial-failure isolation (see Section 9).
- Whether Totals opportunities should fire independently of Moneyline insights or share insight inputs (see Section 11).
- Whether research context for Totals requires new backend data sources (see Section 10).
- The workspace identity model for Totals entries alongside Moneyline entries (see Section 13).

All of the above require Project Manager decision before implementation begins.

---

## 2. Verified Current Moneyline Architecture

This section documents the actual end-to-end Moneyline data flow as observed by direct code inspection. All file paths are relative to the repository root.

### 2.1 Data Flow Overview

```
OddsAPI.io
  └─ GET /v3/events → GET /v3/odds?eventId=...&bookmakers=Bet365,DraftKings
       │
       ▼
backend/fetchers/odds_api_io.py
  ├─ _get_upcoming_events()       → filters status='pending', sorts by date
  ├─ _get_odds_for_event(id)      → fetches raw bookmaker markets per event
  ├─ _normalize_odds(event, data) → filters name='ML', extracts home/away decimal odds,
  │                                  converts to American via decimal_to_american()
  └─ get_moneyline_odds()         → returns list of odds_record dicts
       │
       ▼
backend/scripts/save_live_data.py
  ├─ find_matching_game()  → name-overlap fuzzy match to saved games (handles UTC date shift)
  ├─ save_odds()           → INSERTs into odds_history (no ON CONFLICT — appends snapshots)
  └─ conn.commit()         → single transaction for all data types
       │
       ▼
database (PostgreSQL)
  └─ odds_history: id, game_id, sportsbook, home_moneyline (INT), away_moneyline (INT), recorded_at
       │
       ▼
backend/routers/research.py
  ├─ _get_research_for_date() / _get_research_for_game()
  ├─ Queries odds_history → DISTINCT ON (game_id, sportsbook) ORDER BY recorded_at DESC
  ├─ Computes odds_by_game dict: {sportsbook, away_moneyline, home_moneyline,
  │   away_implied_probability, home_implied_probability}
  └─ Assembles full game object including odds[], line_movement[]
       │  (line_movement: derived from first vs. latest odds_history row per sportsbook)
       ▼
FastAPI routes:
  GET /research/today         → research.py: _get_research_for_date(today)
  GET /research/date/{date}   → research.py: _get_research_for_date(date)
  GET /research/game/{id}     → research.py: _get_research_for_game(id)
  GET /odds/latest            → odds.py: latest snapshot per game+sportsbook
  GET /odds/today             → odds.py: today's latest per game+sportsbook
  GET /odds/movement          → odds.py: opening vs. latest per game+sportsbook
  GET /odds/movement/summary  → odds.py: top movers
       │
       ▼
frontend/lib/researchInsights.ts
  ├─ getResearchInsights(game) → produces ResearchInsight[]
  │   ├─ formVsMarketDivergence     → reads game.odds[].away/home_implied_probability
  │   └─ recordVsRecentFormDivergence → reads game.away/home_record, game.away/home_team_form
       │
       ▼
frontend/lib/marketOpportunities.ts
  └─ getMarketOpportunities(game, insights) → produces MarketOpportunity[]
      └─ formDivergenceToMoneyline → MarketType="FULL_GAME_MONEYLINE"
       │
       ▼
frontend/lib/marketResearchBoard.ts
  └─ buildBoardEntries(games) → BoardEntry[] for /opportunities page
       │
       ▼
Pages:
  frontend/app/page.tsx                    → Dashboard (game table + workspace + comparison)
  frontend/app/opportunities/page.tsx      → Market Research Board
  frontend/app/game/[game_id]/page.tsx     → Game detail
```

### 2.2 Key Symbols and Locations

| Layer | File | Key Symbols |
|---|---|---|
| Provider fetcher | `backend/fetchers/odds_api_io.py` | `get_moneyline_odds()`, `_normalize_odds()`, `decimal_to_american()`, `BOOKMAKERS`, `SPORT`, `LEAGUE` |
| Ingestion orchestrator | `backend/scripts/save_live_data.py` | `save_odds()`, `find_matching_game()`, `name_overlap_score()` |
| Database connection | `backend/db.py` | `get_db_connection()` |
| Odds math | `backend/odds_math.py` | `american_odds_to_implied_probability()` |
| Research router | `backend/routers/research.py` | `_get_research_for_date()`, `_get_research_for_game()` |
| Odds router | `backend/routers/odds.py` | `get_latest_odds()`, `get_odds_movement()`, `get_todays_odds()` |
| Services | `backend/services/team_form.py` | `get_team_last_10_form()` |
| Services | `backend/services/streak.py` | `get_team_streak()` |
| Insight types | `frontend/lib/researchInsights.ts` | `ResearchInsight`, `InsightableGame`, `InsightCategory`, `getResearchInsights()` |
| Opportunity types | `frontend/lib/marketOpportunities.ts` | `MarketType`, `MarketOpportunity`, `MarketOpportunityGenerator`, `OPPORTUNITY_GENERATORS`, `getMarketOpportunities()` |
| Board | `frontend/lib/marketResearchBoard.ts` | `BoardEntry`, `buildBoardEntries()`, `getBoardResearchUrl()` |
| Game flags | `frontend/lib/gameFlags.ts` | `GameFlag`, `FlaggableGame`, `getGameFlags()` |
| Filters | `frontend/lib/gameFilters.ts` | `FilterableGame`, `applyFilters()`, `LINE_MOVE_THRESHOLD` |

### 2.3 Database Schema for Odds (Verified)

```sql
CREATE TABLE odds_history (
    id              SERIAL PRIMARY KEY,
    game_id         INTEGER         NOT NULL REFERENCES games(id),
    sportsbook      VARCHAR(50)     NOT NULL DEFAULT 'unknown',
    home_moneyline  INTEGER         NOT NULL,
    away_moneyline  INTEGER         NOT NULL,
    recorded_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_odds_history_game_time
    ON odds_history (game_id, recorded_at DESC);
```

Observations:
- No market type column. No over/under column. No total line column.
- `home_moneyline` and `away_moneyline` are `NOT NULL` — adding Totals to this table requires schema redesign to accommodate rows that have no home/away price.
- No uniqueness constraint per snapshot — the table appends a new row on every ingestion run regardless of whether odds changed. Line movement is derived by comparing first vs. latest row.
- All odds are stored as integer American odds after conversion from provider decimal odds.

---

## 3. Reusable Abstractions

### 3.1 `decimal_to_american()` — `backend/fetchers/odds_api_io.py:134`

**Current responsibility:** Converts provider decimal odds (float) to integer American odds.

**Market-neutral:** Yes. This conversion applies to any decimal price regardless of market.

**Required extension for Totals:** None. Totals over/under prices arrive as decimal strings from OddsAPI.io (`'1.90'`). The same function handles them after `float()` conversion.

**Backward-compatibility risk:** None. Pure function with no state.

### 3.2 `american_odds_to_implied_probability()` — `backend/odds_math.py:1`

**Current responsibility:** Converts American odds to implied probability percentage.

**Market-neutral:** Yes for two-outcome markets. Moneyline and Totals are both binary (home vs. away; over vs. under).

**Required extension for Totals:** None as a function. However, for Totals, implied probability of "over" and "implied probability of "under" should be computed and served similarly to home/away implied probability.

**Backward-compatibility risk:** None. Pure function.

### 3.3 `find_matching_game()` / `name_overlap_score()` — `backend/scripts/save_live_data.py:199`

**Current responsibility:** Fuzzy-matches an OddsAPI.io odds record to a locally stored game using team name overlap and date proximity. Returns `(game, swapped)` where `swapped` indicates home/away labels are reversed.

**Market-neutral:** Yes. The matching logic is about event identity, not market type. Totals records from OddsAPI.io carry the same `home`, `away`, `date` event fields as Moneyline records.

**Required extension for Totals:** None to the matching logic itself. The same game-matching function can be called when processing Totals records.

**Risk:** The swap-detection logic (`score_normal` vs `score_swapped`) currently flips `home_moneyline` and `away_moneyline` on swapped matches. For Totals, a swap means the total line itself stays the same (it is not team-directional) but the event identity match is still needed. Care is needed in `save_odds()` when persisting Totals — swapped records do not require flipping over/under prices, only confirming game identity.

### 3.4 `get_db_connection()` — `backend/db.py:19`

**Market-neutral:** Yes. Connection helper is completely market-agnostic.

### 3.5 `MarketOpportunityGenerator` pattern — `frontend/lib/marketOpportunities.ts:22`

```typescript
type MarketOpportunityGenerator = {
  id: string;
  supportedMarket: MarketType;
  generate: (context: OpportunityContext) => MarketOpportunity[];
};
```

**Market-neutral:** Yes. The registry pattern (`OPPORTUNITY_GENERATORS: MarketOpportunityGenerator[]`) and `getMarketOpportunities()` dispatch function are designed to support multiple markets by iterating generators whose `supportedMarket` field filters which games each generator applies to.

**Required extension for Totals:** Add `"FULL_GAME_TOTALS"` to the `MarketType` union and register new Totals generators. The `OpportunityContext` type may need to include Totals-specific fields (over/under prices). This is the primary extensibility point.

**Risk of premature abstraction:** Low. The pattern is already in use and its extension is straightforward.

### 3.6 `InsightGenerator` and `INSIGHT_GENERATORS` — `frontend/lib/researchInsights.ts:47`

**Market-neutral:** Mostly. Insight generators operate on game-level data (form, odds, injuries, weather). Some insights fire regardless of what market is being researched (e.g., bullpen stress, weather). The `formVsMarketDivergence` insight is Moneyline-specific because it reads implied probability from `away_implied_probability`/`home_implied_probability` fields.

**Required extension for Totals:** Totals-specific insight generators would need access to Totals odds fields (over/under price, total line). These fields are not currently in `InsightableGame`.

### 3.7 `buildBoardEntries()` — `frontend/lib/marketResearchBoard.ts:13`

**Market-neutral:** Yes. The function iterates all games, calls `getResearchInsights(game)`, then `getMarketOpportunities(game, insights)`, and maps opportunities to board entries. It is agnostic about which markets are active.

**Required extension:** None to the function itself. Adding Totals opportunities will cause them to appear on the board automatically once the generators are registered.

---

## 4. Existing Market-Specific Logic

### 4.1 Database Schema — `database/schema.sql`

| Field / Constraint | Moneyline-specific? | Classification |
|---|---|---|
| `odds_history.home_moneyline INTEGER NOT NULL` | Yes — "home" is a Moneyline concept | Requires a shared multi-market contract |
| `odds_history.away_moneyline INTEGER NOT NULL` | Yes — "away" is a Moneyline concept | Requires a shared multi-market contract |
| No market type column | Implicit Moneyline assumption | Requires a shared multi-market contract |
| No total line column | Absence blocks Totals | Requires schema extension |
| `idx_odds_history_game_time` on `(game_id, recorded_at DESC)` | Market-neutral in structure | Can remain but must cover multi-market queries |

### 4.2 Fetcher — `backend/fetchers/odds_api_io.py`

| Code | Moneyline-specific? | Classification |
|---|---|---|
| `if market.get("name") != "ML": continue` | Yes — explicit ML filter | Should move behind a market strategy |
| `home_dec = line.get("home")` | Yes — "home" field name from ML response | Moneyline-specific; Totals uses "over"/"under"/"hdp" |
| `away_dec = line.get("away")` | Yes — "away" field name | Moneyline-specific |
| Return dict keys `home_moneyline_decimal`, `away_moneyline_decimal`, etc. | Yes — ML semantics | Requires a typed market contract |

### 4.3 Ingestion — `backend/scripts/save_live_data.py`

| Code | Moneyline-specific? | Classification |
|---|---|---|
| `save_odds()` — inserts into `odds_history` with `home_moneyline`, `away_moneyline` | Yes | Should later move behind a market adapter |
| `swap` handling: swaps `home_ml` ↔ `away_ml` | Yes — ML has directionality | Totals: swap affects game identity only, not prices |
| Log line: `"Fetching moneyline odds from OddsAPI.io..."` | Yes | Minor; update when Totals is added |

### 4.4 Research Router — `backend/routers/research.py`

| Code | Moneyline-specific? | Classification |
|---|---|---|
| `SELECT ... away_moneyline, home_moneyline FROM odds_history` | Yes | Requires schema-aware extension |
| `american_odds_to_implied_probability(away_ml)` | Yes — applied to ML prices | Totals will use same function for over/under |
| `odds_by_game` dict shape: `{away_moneyline, home_moneyline, away_implied_probability, home_implied_probability}` | Yes | Requires typed market contract |
| `line_movement` computation: `latest_home_ml - opening_home_ml` | Yes — ML movement | Totals line movement requires tracking total_line delta and over/under price delta |

### 4.5 Odds Router — `backend/routers/odds.py`

| Code | Moneyline-specific? | Classification |
|---|---|---|
| All four endpoints query `odds_history.home_moneyline`, `odds_history.away_moneyline` | Yes | Must remain Moneyline-specific; new Totals endpoints needed |
| `"team": home_team`, `"side": "home"` / `"side": "away"` | Yes — ML side vocabulary | Totals uses "over"/"under" |
| `/odds/movement/summary` sorts by `abs(movement)` | Extensible | Totals movement would be a separate concept |

### 4.6 Frontend Types — `frontend/app/page.tsx`

| Type/Field | Moneyline-specific? | Classification |
|---|---|---|
| `type Odds = { away_moneyline, home_moneyline, away_implied_probability, home_implied_probability }` | Yes | Can remain Moneyline-specific; Totals needs its own type |
| `type Movement = { opening_moneyline, latest_moneyline, movement, side: string, team: string }` | Yes | Totals movement needs different shape |
| Column headers "Bet365 Moneyline (Away / Home)" | Yes | Can remain; Totals columns added alongside |
| `compOdds()`: displays "Away {ml} / Home {ml}" | Yes | Can remain; Totals would have separate comparison row |

### 4.7 Market Type — `frontend/lib/marketOpportunities.ts:3`

```typescript
export type MarketType = "FULL_GAME_MONEYLINE";
```

**Classification:** Can remain and must be extended — add `"FULL_GAME_TOTALS"` as a union member. No existing code will break because it is a string union, not an enum.

### 4.8 Board Display — `frontend/app/opportunities/page.tsx`

| Code | Moneyline-specific? | Classification |
|---|---|---|
| Odds display: `Away {ml} ({prob}) / Home {ml} ({prob})` | Yes | Totals requires different display: `O/U {line}: Over {price} / Under {price}` |
| `entry.opportunity.marketType.replace(/_/g, " ")` | Neutral | Works for "FULL GAME TOTALS" automatically |

---

## 5. OddsAPI.io Totals Field Mapping

### 5.1 Confirmed Provider Response Structure

Source: Phase 13 Sprint 4 diagnostic output (2026-07-17), direct API inspection.

**Provider response for one Totals market:**
```json
{
  "name": "Totals",
  "updatedAt": "2026-07-16T20:16:19.023Z",
  "odds": [
    {
      "hdp": 8.5,
      "over": "1.90",
      "under": "1.90"
    }
  ]
}
```

**Confirmed facts (not assumptions):**
- Market name is exactly `"Totals"` (capital T, no abbreviation)
- `hdp` is the total run line (float; e.g., 8.5, 9.0)
- `over` and `under` are decimal odds as strings (e.g., `"1.90"`, `"2.00"`)
- `updatedAt` is a UTC ISO-8601 timestamp string from the provider
- Both Bet365 and DraftKings return this structure in the same `bookmakers` dict as Moneyline

**Observed in diagnostic sample:**
- TB @ BOS (Bet365): `hdp=8.5, over='1.90', under='1.90'` (updatedAt 2026-07-16T20:16Z)
- TB @ BOS (DraftKings): `hdp=8.5, over='1.90', under='1.90'` (updatedAt 2026-07-17T05:18Z)
- LAD @ NYY (Bet365): `hdp=9, over='1.83', under='2.00'` (updatedAt 2026-07-16T22:55Z)
- LAD @ NYY (DraftKings): `hdp=9, over='1.83', under='2.00'` (updatedAt 2026-07-16T18:41Z)

### 5.2 Proposed Internal Field Mapping

| Provider Field | Type (provider) | Proposed Internal Name | Type (internal) | Notes |
|---|---|---|---|---|
| `name == "Totals"` | string | market discriminator | — | Filter: skip if name != "Totals" |
| `hdp` | float or int | `total_line` | `float` | The posted run total (e.g., 8.5) |
| `over` | string | `over_price_decimal` | `float` | Parse: `float(over)` |
| `under` | string | `under_price_decimal` | `float` | Parse: `float(under)` |
| _(derived)_ | — | `over_price_american` | `int` | Via `decimal_to_american()` |
| _(derived)_ | — | `under_price_american` | `int` | Via `decimal_to_american()` |
| `updatedAt` | string | `provider_updated_at` | `str` (UTC ISO) | Provider's own update timestamp |
| _(fetch time)_ | — | `recorded_at` | `str` (UTC ISO) | Time of our ingestion run |
| `event.id` | string | `event_id` | `str` | OddsAPI.io event ID |
| `event.home` | string | `home_team` | `str` | Used for game matching |
| `event.away` | string | `away_team` | `str` | Used for game matching |
| `event.date` | string | `game_time` | `str` (UTC ISO) | Used for game matching |
| _(bookmaker key)_ | string | `sportsbook` | `str` | "Bet365" or "DraftKings" |

### 5.3 Edge Cases and Handling Requirements

**Missing `over` or `under`:** Provider response could theoretically have one side missing. Reject the record. Do not store partial Totals.

**Missing `hdp`:** Without the total line, the record is meaningless. Reject.

**Null values:** `over`, `under`, or `hdp` could be null. Treat as missing; reject.

**Non-numeric `over`/`under`:** `float()` conversion could throw `ValueError`. Catch and reject with a logged warning.

**`hdp` as integer vs. float:** The provider sends `8.5` (float) or `9` (int). Both are valid. Normalize to float.

**Duplicate records:** Same `game_id + sportsbook + total_line` with identical prices arriving on repeated ingestion runs. This is expected behavior (snapshot appending). Design must support idempotent reads of "latest" vs. "opening" values.

**Conflicting `hdp` between sportsbooks:** Two sportsbooks may post different total lines for the same game (e.g., 8.5 vs. 9.0). Both should be stored as separate rows with their respective sportsbook labels.

**Line change between ingestion runs:** The total line itself may move (e.g., opens at 8.5, moves to 9.0). Line movement should be tracked the same way as Moneyline movement: compare the earliest row to the latest row per `game_id + sportsbook`.

**`updatedAt` from provider:** This is the provider's own freshness timestamp. It may be used to detect stale data (provider not updating odds), but it is distinct from `recorded_at` (when we fetched). Both should be stored or at minimum `recorded_at` should be stored.

**`markets='totals'` vs. `markets='ML,totals'`:** Both are confirmed to return HTTP 200. Combined requests reduce API call count but complicate per-market partial-failure handling. See Section 9.

---

## 6. Validation and Normalization Rules

### 6.1 Market Identification

**Rule (required):** Accept only provider records where `market.get("name") == "Totals"`. All other market names must be skipped without error.

### 6.2 Full-Game Scope

**Rule (required):** The current provider configuration (`SPORT = "baseball"`, `LEAGUE = "usa-mlb"`) targets full-game MLB markets. First-5-Innings Totals appear under the name `"First 5 Innings Totals"` and must be filtered out. Only `"Totals"` is in scope.

### 6.3 Total-Line Parsing

**Rule (required):** `hdp` must be a numeric value (float or int). Accept both. Store as `NUMERIC(4, 1)` (e.g., 8.5, 9.0). Reject null, missing, or non-numeric values.

**Rule (required):** Total line must be > 0. Reject zero or negative values as malformed.

### 6.4 Over/Under Price Normalization

**Rule (required):** `over` and `under` are provider decimal odds as strings. Convert via `float(value)` then `decimal_to_american()`. If conversion raises `ValueError`, reject the record and log a warning.

**Rule (required):** Over and under prices must both be present. A record with only one side is incomplete and must be rejected.

**Rule (required):** Decimal odds must be ≥ 1.01. Values below this are malformed.

### 6.5 American Odds Convention

**Rule (verified):** The existing codebase converts decimal odds to American via `decimal_to_american()` in `backend/fetchers/odds_api_io.py:134`. The same convention applies to Totals. Both over and under prices are stored as integer American odds.

**Rule:** The existing `american_odds_to_implied_probability()` in `backend/odds_math.py` is used for derived probability fields. For Totals: apply to both `over_price_american` and `under_price_american`.

### 6.6 Numeric Bounds

**Informational (not hard-gating):** MLB total run lines typically fall between 6.5 and 14.5. Lines outside 5.0–18.0 should generate a log warning but should not automatically reject the record (unusual games exist). American odds outside −10000 to +10000 should be treated as malformed and rejected.

### 6.7 Missing Side Handling

**Rule (required):** If `over` or `under` is missing or null, reject the entire Totals record for that sportsbook/game combination. Do not store partial records.

### 6.8 Equal Over/Under Expectations

**Informational:** When over and under decimal odds are equal (e.g., both `'1.90'`), this is normal provider behavior (vig-adjusted 50/50 line). Do not flag as an error.

**Rule (informational warning):** If over and under American odds sum to a positive number (indicating the line is not vig-adjusted in the expected direction), log a warning for investigation.

### 6.9 Duplicate Sportsbook-Market-Side Records

**Rule:** Multiple Totals records for the same `game_id + sportsbook` on the same ingestion run indicate a provider returning multiple lines (e.g., alternate totals). For MVP, accept only the first record encountered per `game_id + sportsbook`. Log a warning if multiple are present.

### 6.10 Snapshot Timestamps

**Rule (required):** Set `recorded_at` to `datetime.now(timezone.utc)` at fetch time (same pattern as Moneyline in `_normalize_odds()`). Do not rely solely on provider `updatedAt` for ingestion ordering.

### 6.11 Game Matching

**Rule (required):** Use the existing `find_matching_game()` function. Totals records from OddsAPI.io carry the same event fields (`home`, `away`, `date`) as Moneyline records. The matching logic is market-agnostic.

**Rule:** If no matching game is found, log the skip (same pattern as current `odds_skipped` counter in `save_odds()`). Do not fail the transaction.

### 6.12 Postponed or Cancelled Games

**Rule:** Totals ingestion follows the same pattern as Moneyline. If a game is not in the `games` table with status `scheduled`, the odds record will fail to match and will be skipped. No special handling required.

### 6.13 Stale Data

**Informational:** Provider `updatedAt` more than 24 hours before ingestion time should generate a log warning. Not a rejection criterion for MVP.

### 6.14 Unsupported Provider Variants

**Rule:** Only `name == "Totals"` is accepted. Alternative names such as `"Game Total"`, `"Run Total"`, or any other spelling are logged as warnings and skipped.

### 6.15 Error Reporting and Observability

**Rule:** Log the count of Totals records fetched, the count skipped, and the count saved — matching the existing pattern in `main()` of `save_live_data.py` (e.g., `"Saved N totals rows"`).

---

## 7. Database Design and Migration Requirements

### 7.1 Current Schema Assessment

The `odds_history` table stores one row per ingestion snapshot per `game_id + sportsbook`. Key constraints:

- `home_moneyline INTEGER NOT NULL` — Totals has no "home" price; this column cannot be null.
- `away_moneyline INTEGER NOT NULL` — Same problem.
- No market type discriminator.
- No total line column.
- The `NOT NULL` constraints on both moneyline columns are a hard block: adding Totals rows to this table as-is is impossible without schema changes.

### 7.2 Option A: Add Nullable Totals Columns to `odds_history`

**Proposed changes:**
```sql
-- Proposed future migration (NOT to be created in this sprint)
ALTER TABLE odds_history
    ADD COLUMN market_type   VARCHAR(30) NOT NULL DEFAULT 'moneyline',
    ADD COLUMN total_line    NUMERIC(4, 1),
    ADD COLUMN over_price    INTEGER,
    ADD COLUMN under_price   INTEGER,
    ALTER COLUMN home_moneyline DROP NOT NULL,
    ALTER COLUMN away_moneyline DROP NOT NULL;
```

**Uniqueness:** No unique constraint currently exists on `odds_history`. For multi-market queries, an index on `(game_id, sportsbook, market_type, recorded_at DESC)` would be required.

**Pros:**
- One table, simpler joins in research queries.
- Existing queries continue to work with a `WHERE market_type = 'moneyline'` filter.
- Line movement derived uniformly.

**Cons:**
- `home_moneyline` and `away_moneyline` becoming nullable is a schema relaxation that weakens the existing Moneyline data contract.
- Every existing query must be updated to add a `market_type` filter or it will return mixed results.
- The table becomes a mixed-type store — Totals rows have null `home_moneyline`/`away_moneyline`; Moneyline rows have null `total_line`/`over_price`/`under_price`.
- Tooling-level confusion: queries on `odds_history` without a market filter return mixed semantics.

### 7.3 Option B: Separate `totals_history` Table

**Proposed table (NOT to be created in this sprint):**
```sql
-- Proposed future migration (NOT to be created in this sprint)
CREATE TABLE totals_history (
    id              SERIAL PRIMARY KEY,
    game_id         INTEGER         NOT NULL REFERENCES games(id),
    sportsbook      VARCHAR(50)     NOT NULL,
    total_line      NUMERIC(4, 1)   NOT NULL,
    over_price      INTEGER         NOT NULL,
    under_price     INTEGER         NOT NULL,
    recorded_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_totals_history_game_time
    ON totals_history (game_id, recorded_at DESC);
```

**Pros:**
- `odds_history` is unchanged. All existing Moneyline code, queries, and tests are unaffected.
- `totals_history` has clean `NOT NULL` constraints on all meaningful columns.
- Each table has one semantic meaning.
- No risk of mixed-market queries returning incorrect results.
- Rollback is trivial: `DROP TABLE totals_history` removes all Totals infrastructure without touching Moneyline data.

**Cons:**
- Research queries that want both Moneyline and Totals for a game must JOIN two tables.
- Two persistence functions, two indexes, two migration files.
- Future markets (run lines, F5) each need their own table or the pattern must evolve.

### 7.4 Recommendation

**Option B (separate `totals_history` table) is recommended.** The primary reason is backward compatibility: the `odds_history` table has established behavior, tested queries, and `NOT NULL` constraints that correctly reflect the Moneyline data model. Weakening those constraints for a secondary market introduces both data-integrity risk and query-correctness risk across all existing code.

The cost of a separate table is modest: one additional JOIN in research queries and two persistence functions instead of one. Both are straightforward given the existing patterns.

This recommendation requires Project Manager approval before any migration is created.

**Cross-document note:** The Phase 15 Sprint 2 Decision Analysis (D1) uses different option labels for the same alternatives. Sprint 1 Option A (extend `odds_history`) corresponds to Sprint 2 Option 2. Sprint 1 Option B (separate `totals_history` table, recommended here) corresponds to Sprint 2 Option 1. The recommendation is identical in both documents.

### 7.5 Historical Snapshot Strategy

Like Moneyline, Totals odds should be snapshot-appended (no ON CONFLICT / upsert). Line movement is derived by comparing the earliest and latest rows. This maintains the full history of how the total line and over/under prices have moved since tracking began.

### 7.6 Backfill Implications

Totals data before the implementation date will not exist. There is no retroactive backfill planned. The first ingestion run after implementation will establish the "opening" line for any games that day.

### 7.7 Rollback Considerations

With Option B: rollback is `DROP TABLE totals_history`. No Moneyline data is affected.

With Option A: rollback requires reverting the `ALTER TABLE`, which is destructive if Totals rows already exist. Option A rollback is significantly more complex.

### 7.8 Data Migration Risks

- No migration of historical data is planned or required.
- The only risk is during the schema migration: if the migration fails mid-run, `totals_history` may be partially created. Use `CREATE TABLE IF NOT EXISTS` and ensure the migration is idempotent.

### 7.9 Compatibility with Existing Moneyline Rows

With Option B: complete compatibility. `odds_history` is never touched by Totals code paths. With Option A: requires careful column-default handling for all existing rows.

---

## 8. Backend Models, Services, and API Design

### 8.1 Domain Models

**Current Moneyline odds record (internal dict):**
```python
{
    "event_id": str,
    "home_team": str,
    "away_team": str,
    "game_time": str,
    "sportsbook": str,
    "home_moneyline_decimal": float,
    "away_moneyline_decimal": float,
    "home_moneyline_american": int,
    "away_moneyline_american": int,
    "recorded_at": str,
}
```

**Proposed Totals odds record (new internal dict):**
```python
{
    "event_id": str,
    "home_team": str,
    "away_team": str,
    "game_time": str,
    "sportsbook": str,
    "total_line": float,
    "over_price_decimal": float,
    "under_price_decimal": float,
    "over_price_american": int,
    "under_price_american": int,
    "provider_updated_at": str,
    "recorded_at": str,
}
```

These are plain dicts (consistent with current pattern — no ORM, no dataclasses required at MVP).

### 8.2 Provider Adapter Design

**Proposed function (not to be implemented in this sprint):**

```python
# backend/fetchers/odds_api_io.py (proposed addition)
def get_totals_odds(max_games=10):
    """Fetch full-game totals for the next max_games upcoming MLB games."""
    ...

def _normalize_totals(event, odds_data):
    ...
    for sportsbook, markets in bookmakers.items():
        for market in markets:
            if market.get("name") != "Totals":
                continue
            for line in market.get("odds", []):
                hdp = line.get("hdp")
                over = line.get("over")
                under = line.get("under")
                if hdp is None or over is None or under is None:
                    continue
                # ... float conversion, decimal_to_american, record append
```

**Design decision:** Whether `get_totals_odds()` calls `_get_odds_for_event()` separately (two API calls per game) or whether a combined `markets='ML,totals'` call is used to fetch both in one request is deferred to Section 9.

### 8.3 Persistence Service

**Proposed function (not to be implemented in this sprint):**

```python
# backend/scripts/save_live_data.py (proposed addition)
def save_totals(cur, saved_games, totals_records):
    """Insert one totals_history row per totals record that matches a saved game."""
    saved = 0
    skipped = 0
    for record in totals_records:
        match = find_matching_game(saved_games, record)
        if match is None:
            skipped += 1
            continue
        game, _ = match  # swap is not meaningful for total line
        cur.execute(
            """
            INSERT INTO totals_history (game_id, sportsbook, total_line, over_price, under_price, recorded_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (game["id"], record["sportsbook"], record["total_line"],
             record["over_price_american"], record["under_price_american"],
             record["recorded_at"]),
        )
        saved += 1
    return saved, skipped
```

### 8.4 Query Services

The research router will need to query `totals_history` in the same "latest per game+sportsbook" pattern used for `odds_history`:

```sql
-- Proposed query pattern (not to be implemented in this sprint)
SELECT DISTINCT ON (game_id, sportsbook)
    game_id, sportsbook, total_line, over_price, under_price, recorded_at
FROM totals_history
WHERE game_id = ANY(%s)
ORDER BY game_id, sportsbook, recorded_at DESC
```

### 8.5 API Response Shape Extensions

**Existing research response per game includes:**
```json
{
  "odds": [
    {
      "sportsbook": "Bet365",
      "away_moneyline": 120,
      "away_implied_probability": 45.45,
      "home_moneyline": -140,
      "home_implied_probability": 58.33
    }
  ]
}
```

**Proposed extension (not to be implemented in this sprint):**
```json
{
  "odds": [ ... ],
  "totals": [
    {
      "sportsbook": "Bet365",
      "total_line": 8.5,
      "over_price": -111,
      "under_price": -111,
      "over_implied_probability": 52.61,
      "under_implied_probability": 52.61
    }
  ]
}
```

The `totals` key is additive. All existing API consumers receive the same `odds` array unchanged.

### 8.6 Moneyline APIs That Must Remain Unchanged

- `GET /odds/latest` — returns only Moneyline data. Must not change.
- `GET /odds/today` — returns only Moneyline data. Must not change.
- `GET /odds/movement` — Moneyline movement only. Must not change.
- `GET /odds/movement/summary` — Moneyline movement only. Must not change.
- `GET /research/today`, `GET /research/date/{date}`, `GET /research/game/{id}` — the `odds` key must remain unchanged. The `totals` key is additive.

### 8.7 New API Endpoints (Proposed, Not Implemented)

- `GET /totals/today` — latest Totals per game+sportsbook for today
- `GET /totals/movement` — opening vs. latest total line and over/under prices

These should parallel the existing `/odds/*` structure.

### 8.8 Error Handling

If Totals fetching fails, the existing pattern is: catch the exception, print a skip message, set `totals_records = []`. The transaction commits without Totals. This matches the existing behavior for injuries (`Skipping injuries: ...`) and weather failures.

---

## 9. Ingestion Design

### 9.1 Provider Request Strategy Options

**Option A: Combined `markets='ML,totals'` request**

One API call per game fetches both Moneyline and Totals. The existing `_get_odds_for_event()` function would gain a `markets` parameter.

- Pros: Halves API calls per game; stays within 100 requests/hour free tier more easily.
- Cons: If one market type is malformed, the entire request must be re-parsed. Partial-market failure handling is more complex. If Totals is temporarily unavailable, Moneyline ingestion is still blocked from separate retry.

**Option B: Separate requests — `markets='ML'` and `markets='totals'`**

Two API calls per game, processed independently.

- Pros: Failure isolation — Totals failure does not affect Moneyline. Each market can be retried independently. Cleaner parsing.
- Cons: Doubles API calls per game. At 15–18 games per day, this is 30–36 calls instead of 15–18, still within the 100/hour limit at 11 AM and 7 PM ingestion runs.

**Recommendation:** Option B (separate requests) for MVP. Quota impact is acceptable at current scale, and failure isolation is architecturally cleaner. This decision requires PM approval.

### 9.2 Parsing Sequence

Within `save_live_data.py::main()`:

```
1. Fetch games (MLB Stats API)
2. Fetch team records (MLB Stats API)
3. Fetch moneyline odds (OddsAPI.io — existing)
4. Fetch totals odds (OddsAPI.io — new, separate call)
5. Fetch injuries (ESPN)
6. Fetch bullpen context (MLB Stats API)
7. Fetch weather (Open-Meteo)
```

Totals fetch failure must not interrupt subsequent steps. Each fetcher is independent.

### 9.3 Validation Sequence

Within `save_totals()`:
1. Match to saved game (reject if no match)
2. Validate `total_line` is numeric and > 0
3. Validate `over_price_american` and `under_price_american` are non-null integers
4. Insert record

### 9.4 Transaction Boundaries

All data types (games, odds, totals, injuries, bullpen, weather) commit in a single `conn.commit()` call. This is the existing pattern and should be preserved for Totals. If Totals insertion fails (unexpected schema error), the entire transaction rolls back — which is preferable to committing a partially consistent state.

### 9.5 Idempotency

Like Moneyline, Totals uses snapshot-append (no ON CONFLICT). Re-running ingestion for the same timestamp produces duplicate rows. This is acceptable: "latest" queries use `DISTINCT ON ... ORDER BY recorded_at DESC`, which correctly handles duplicates.

### 9.6 Partial-Provider Failure

If Bet365 returns Totals but DraftKings does not, only Bet365 rows are stored. This is correct behavior — no special handling required.

### 9.7 Partial-Market Failure

If the Totals fetch succeeds for 10 games but fails for 5 (API error mid-loop), the 10 valid records are stored. The existing ingestion loop per game continues on exception (same as weather). Skipped records are counted and logged.

### 9.8 Logging

Existing log pattern in `main()`:
```
Fetching moneyline odds from OddsAPI.io...
  Found N odds records
```

Proposed additions:
```
Fetching totals odds from OddsAPI.io...
  Found N totals records
...
Saved N totals rows
```

### 9.9 Existing Batch Wrapper and Scheduler Compatibility

`backend/scripts/run_ingestion.bat` calls `save_live_data.py` directly. No changes to the batch wrapper or Task Scheduler are required at design time. When Totals ingestion is added to `save_live_data.py`, it will execute at the existing 11 AM and 7 PM scheduled times automatically.

### 9.10 Safe Rollout and Feature Gating

For initial implementation, Totals fetching can be gated behind a simple environment variable check (e.g., `ENABLE_TOTALS_INGESTION=true`) to allow controlled activation without a code deployment. This is a lightweight implementation detail, not a framework feature flag.

---

## 10. Research-Layer Requirements

### 10.1 Existing Reusable Game Context

All of the following are already available and relevant to Totals research:

| Data | Source | Totals Relevance |
|---|---|---|
| Starting pitchers (names only) | `starting_pitchers` | Pitching quality affects expected run totals — pitcher names provide research anchor |
| Bullpen context (innings last game, played yesterday) | `team_bullpen_context` | Bullpen-heavy games tend toward more scoring variance |
| Weather (temperature, wind speed/direction, precipitation) | `game_weather` | Wind blowing out = higher totals; domes are weather-neutral |
| Team records (wins/losses) | `team_records` | Team scoring context |
| Team form (last 10, run differential) | `services/team_form.py` | `last_10_run_diff` is directly relevant to over/under research |

### 10.2 Existing Moneyline-Specific Research

The following are Moneyline-specific and should not be co-opted as Totals research inputs:

| Data | Why Moneyline-Specific |
|---|---|
| `away_implied_probability`, `home_implied_probability` | Derived from ML prices; not relevant to total line |
| `formVsMarketDivergence` insight | Compares form win rate to ML pricing — win probability, not scoring volume |

### 10.3 New Totals-Specific Research Needs

**Available from existing data:**
- `last_10_run_diff` (already in form data): Teams with large positive run differentials over their last 10 games may be playing in high-scoring games.
- Wind data (`wind_speed`, `wind_direction`): Blowing-out context is a meaningful over signal; blowing-in context is a meaningful under signal. This data exists in `game_weather`.
- Pitcher names: No stats currently. Names alone are not sufficient for totals research but are useful for manual reference.
- `precipitation_chance`: Rain games tend to go under.

**Missing from existing data (not blockers for MVP, but relevant):**
- Pitcher quality metrics (ERA, K/9): Not available from any current fetcher. MLB Stats API does have pitcher statistics endpoints that are not currently used.
- Team run-scoring averages: Not stored as a separate metric. The `last_10_run_diff` is a proxy.
- Park factors: Not stored. Relevant for stadiums with known run-environment effects (Coors Field).
- Historical over/under rates: Not stored. No game outcome total (combined score) is recorded.

**Design rule:** Totals research at MVP should use existing data (run differential, weather, bullpen context, pitcher names) rather than requiring new data sources. The no-new-data constraint keeps Phase 15 Sprint 1 purely design, and subsequent implementation sprints constrained.

### 10.4 Data Quality Dependencies

The injury data mapping bug noted in `MARKET_RESEARCH_ARCHITECTURE.md` Section 1.8 (ESPN abbreviation mapping fails for most teams) affects all markets equally. This is a separate backlog item, not a Totals-specific blocker.

---

## 11. Market-Opportunity Generation Design

### 11.1 Market-Neutral Contract

The existing `MarketOpportunity` type requires no structural changes for Totals. All fields apply:

| Field | Totals Application |
|---|---|
| `id: string` | Unique per Totals generator, e.g., `"run-diff-totals"` |
| `gameId: string` | Same game_id as Moneyline |
| `marketType: MarketType` | `"FULL_GAME_TOTALS"` |
| `title: string` | Totals-specific headline, e.g., "Full-Game Totals Research Candidate" |
| `summary: string` | Totals research narrative |
| `reasons: string[]` | Supporting bullet points |
| `cautionNotes: string[]` | Same existing cautions apply; no EV, no recommendation |
| `sourceInsightIds: string[]` | IDs of insights that triggered this opportunity |
| `displayPriority?: number` | Optional sort hint |

### 11.2 Proposed Totals-Specific Opportunity Fields

The `MarketOpportunity` type does not include `direction` (over/under) intentionally — consistent with the principle that opportunities name a market but do not prescribe which side to choose. This is the same design as Moneyline (no "home" or "away" direction in the opportunity itself).

If future sprints warrant it, a `side` or `direction` field could be added. This requires PM approval and is not part of the MVP design.

### 11.3 Over/Under Side Representation

Not included in the opportunity object. The researcher reviews the supporting evidence and decides which side, if any, to act on.

### 11.4 Proposed Generator: `runDiffContextToTotals`

**Trigger condition:** `last_10_run_diff` for either team is notably positive (suggesting offensive form) or negative (suggesting pitching/defensive dominance), combined with an available Totals line.

**Proposed insight ID:** `"run-diff-totals-context"` (a new insight ID to be registered in `researchInsights.ts`)

**Proposed opportunity ID:** `"run-diff-totals"`

**Caution notes:** Same standard set as Moneyline opportunities.

**Implementation note:** This generator will only fire when `totals` data exists in the game object. If no Totals odds are present, the generator returns `[]`.

### 11.5 Deduplication

Each generator has a stable `id`. If a generator fires for the same game on multiple board loads, the same opportunity appears once (the board is rebuilt from fresh API data each load, not persisted).

### 11.6 Backward Compatibility

`FULL_GAME_MONEYLINE` generators are unaffected. Adding Totals generators to `OPPORTUNITY_GENERATORS` is purely additive. Existing `formDivergenceToMoneyline` continues to fire for games with Moneyline data, regardless of whether Totals data is present.

---

## 12. Frontend and UX Integration

### 12.1 TypeScript Type Extensions (Proposed, Not Implemented)

**New type:**
```typescript
type TotalsOdds = {
  sportsbook: string;
  total_line: number;
  over_price: number;
  under_price: number;
  over_implied_probability: number;
  under_implied_probability: number;
};
```

**Extension to existing Game/ResearchGame/GameDetail types:**
```typescript
// Add to existing type definitions (additive, optional)
totals?: TotalsOdds[];
```

Optional to maintain backward compatibility — pages load correctly even when the backend does not yet return `totals`.

### 12.2 Market Navigation

Current: The dashboard is monolith (all data for the selected date). No market tabs.

Proposed for Totals: The existing market type filter pattern in `MarketOpportunity.marketType` can be used to group board entries by market on the opportunities page. A simple tab or dropdown filter ("All markets / Moneyline / Totals") would separate entries without redesigning the board.

### 12.3 Market Research Board

- Totals opportunities will appear alongside Moneyline opportunities when the `FULL_GAME_TOTALS` generator is active.
- `marketType.replace(/_/g, " ")` already renders `"FULL GAME TOTALS"` correctly without code change.
- The `Available Odds` section currently renders `{sportsbook}: Away {ml} / Home {ml}`. For Totals entries, this section should render `{sportsbook}: {line} O {over_price} / U {under_price}`. A new rendering branch is required, gated on `marketType`.

### 12.4 Workspace

- Workspace currently stores `game_id: number` as the identity key.
- Totals entries are at the game level, not the market level — the workspace stores a game regardless of which markets the researcher is examining.
- No structural change to workspace storage is required for MVP.
- The workspace notes textarea allows the researcher to annotate which market and side they are considering.

**Identity consideration:** If a researcher wants to shortlist a game for Totals research separately from Moneyline research on the same game, the current single-game-per-workspace-entry model does not support this distinction. A future decision point: whether workspace entries should be `game_id + market_type` pairs. This is not required for MVP.

### 12.5 Comparison View

The current `ComparisonTable` component (`frontend/app/page.tsx:269`) shows side-by-side rows for Moneyline and line movement. Totals would require new section rows:

```
SECTION: Totals
  Row: Bet365 Total (O/U line): {a.total_line} / {b.total_line}
  Row: Bet365 Over Price: {a.over_price} / {b.over_price}
  Row: Bet365 Under Price: ...
  Row: DraftKings Total (O/U line): ...
```

These rows are additive. Existing Moneyline rows remain unchanged.

**Cross-market comparison rule:** Comparing a Moneyline opportunity against a Totals opportunity is out of scope. Comparison is game-level, not market-level.

### 12.6 Game Detail View

The existing "Current Odds" section (`frontend/app/game/[game_id]/page.tsx:444`) shows a table of Moneyline per sportsbook. A new "Totals" section should appear alongside (not replacing) the Moneyline section:

```
## Totals
| Sportsbook | Line  | Over  | Over Prob | Under | Under Prob |
| Bet365     | O/U 8.5 | -111 | 52.6%   | -111  | 52.6%      |
| DraftKings | O/U 8.5 | -111 | 52.6%   | -111  | 52.6%      |
```

Loading, empty, and error states follow the existing pattern: if `game.totals` is undefined or empty, show "No totals available" (same pattern as "No odds available").

### 12.7 Total-Line Formatting

Proposed: Display as `"O/U {line}"` (e.g., `"O/U 8.5"`). Over/under prices formatted with `formatMoneyline()` (existing function — no change needed).

### 12.8 Accessibility and Responsive Layout

No special requirements beyond what exists for Moneyline. The table-based layout currently used handles both markets without redesign.

---

## 13. Board, Workspace, Comparison, and Game-Detail Integration

### 13.1 Market Research Board

**Coexistence of Totals and Moneyline:** Entries are ordered by `displayPriority` then by registration order in `OPPORTUNITY_GENERATORS`. A market-type header chip (`"FULL GAME MONEYLINE"` / `"FULL GAME TOTALS"`) already renders via `marketType.replace(/_/g, " ")`.

**Filters:** A market-type filter dropdown (Moneyline / Totals / All) would allow the researcher to view each market independently. This is additive and does not require board restructuring.

**Columns:** Board cards are not tabular — they are cards with text sections. No column addition is needed.

**Avoiding ambiguity:** The `marketType` field on the opportunity card distinguishes which market the opportunity belongs to. The "Available Odds" rendering must branch by `marketType` to show the correct price format.

### 13.2 Workspace

**Saved representation:** `game_id` (integer) stored in `localStorage` under key `"mlb_workspace_ids"`. Market type is not part of the workspace identity. This is sufficient for MVP — the researcher can note in the textarea which market they are examining.

**Compatibility:** All existing Moneyline workspace entries are unaffected.

**Deduplication rule:** One entry per `game_id`. A game already in the workspace for Moneyline research does not need a second entry for Totals research.

### 13.3 Comparison View

**Valid comparison dimensions:** Two games of the same date, compared across all available research fields. Both Moneyline and Totals data can appear in the comparison if available.

**Cross-market comparison boundaries:** The comparison table is game-level. Comparing a game for Moneyline vs. Totals on the same card pair is out of scope.

**Totals rows:** Add a "Totals" section row with `total_line`, `over_price`, and `under_price` per sportsbook for each game. These rows are additive below the existing "Odds" section.

**Relevant files:** `frontend/app/page.tsx:269` (`ComparisonTable` component), specifically the `SectionRow` and data row pattern.

### 13.4 Game Detail

**Totals market section:** New section added below "Current Odds". File: `frontend/app/game/[game_id]/page.tsx`.

**Research parity requirements:** The same game context that informs Moneyline research (pitcher names, weather, bullpen, form) is already shown. Totals does not require new game-context sections for MVP — the researcher uses existing context.

**Supporting and contradicting evidence:** When Totals opportunities appear in `game.opportunities`, they display their `reasons` and `cautionNotes` in the existing opportunity card rendering. No new UI component is required.

**Multiple sportsbooks and lines:** The Totals table shows one row per sportsbook. If lines differ across books (e.g., Bet365 at 8.5, DraftKings at 9.0), both rows appear and the researcher can observe the discrepancy.

---

## 14. Testing Strategy and Acceptance Criteria

This section defines the future test plan. No tests are to be added in this sprint.

### 14.1 Provider Parser Unit Tests

File: `backend/tests/test_totals_parser.py` (future)

| Test | Criterion |
|---|---|
| Valid Totals market record | Returns one normalized totals_record with correct fields |
| Missing `hdp` | Returns empty list |
| Missing `over` | Returns empty list |
| Missing `under` | Returns empty list |
| `over` non-numeric string | Returns empty list; no exception raised |
| `hdp = 0` | Returns empty list |
| `hdp` as integer (e.g., 9) | Returns total_line = 9.0 (float) |
| Two sportsbooks in one response | Returns two records |
| Non-Totals market name (e.g., "Spreads") | Skipped; not included in output |
| Empty bookmakers dict | Returns empty list |

### 14.2 Normalization Tests

| Test | Criterion |
|---|---|
| `decimal_to_american('1.90')` | Returns −111 |
| `decimal_to_american('2.00')` | Returns +100 |
| `american_odds_to_implied_probability(-111)` | Returns ≈52.6 |
| Over and under normalized independently | Both fields present and correct |

### 14.3 Validation Tests

| Test | Criterion |
|---|---|
| Valid Totals record passes all rules | Accepted |
| Missing field triggers rejection | Not saved; skip counter incremented |
| Non-numeric `over` logs warning | Warning logged; record skipped |

### 14.4 Database Model and Migration Tests

| Test | Criterion |
|---|---|
| `CREATE TABLE totals_history` executes without error | Table exists |
| Insert valid row | Row count = 1 |
| Select DISTINCT ON (game_id, sportsbook) ORDER BY recorded_at DESC | Returns latest row only |
| Rollback validation (isolated non-production test database only — never the live database): after applying the migration in an isolated test environment, run `DROP TABLE totals_history` and confirm `odds_history` row count is unchanged and all existing Moneyline queries execute without error | `odds_history` unaffected; Moneyline application behavior intact |

### 14.5 Persistence Tests

| Test | Criterion |
|---|---|
| `save_totals()` with one matching record | Saved count = 1; skipped = 0 |
| `save_totals()` with no matching game | Saved count = 0; skipped = 1 |
| `save_totals()` with swapped home/away | Game matched correctly; total_line unchanged (not flipped) |
| Empty totals_records list | No insert; no error |

### 14.6 Service Tests

| Test | Criterion |
|---|---|
| `get_totals_for_date()` with data | Returns list of totals dicts per game |
| `get_totals_for_date()` with no Totals rows | Returns empty list or omits `totals` key |
| `get_totals_for_game()` | Returns correct sportsbook rows |

### 14.7 API Contract Tests

| Test | Criterion |
|---|---|
| `GET /research/today` response `odds` key unchanged | Existing Moneyline consumers unaffected |
| `GET /research/today` response includes `totals` key | New key present when data available |
| `GET /research/today` response `totals` key is empty list when no data | Graceful empty state |
| `GET /totals/today` | Returns correct shape |

### 14.8 Ingestion Tests

| Test | Criterion |
|---|---|
| Full `main()` with mocked Totals fetcher | Totals saved count logged correctly |
| Totals fetch raises exception | Ingestion continues; Totals count = 0 |
| Combined ingestion run saves both Moneyline and Totals | Both counts > 0 |

### 14.9 Frontend Unit/Component Tests

File: `frontend/lib/marketOpportunities.test.ts` (additions)

| Test | Criterion |
|---|---|
| Totals generator returns empty when no Totals odds | 0 opportunities |
| Totals generator fires when triggering insight and Totals odds present | 1 opportunity with `marketType = "FULL_GAME_TOTALS"` |
| Opportunity `cautionNotes` disclaim EV and betting recommendation | Pass (same as Moneyline test) |
| Opportunity `marketType` renders correctly in board UI | `"FULL GAME TOTALS"` |

### 14.10 Integration Tests

| Test | Criterion |
|---|---|
| End-to-end: ingestion → research API → board | Totals opportunity appears on board |
| Game detail page shows Totals section | Rendered when data available; empty state when not |
| Comparison table shows Totals rows | Two games with Totals data compared correctly |

### 14.11 Regression Tests for Moneyline

| Test | Criterion |
|---|---|
| All existing `test_research_endpoints.py` tests pass | Unchanged behavior |
| All existing `test_health_ingestion.py` tests pass | Unchanged |
| All existing `test_data_quality.py` tests pass | Unchanged |
| All existing `marketOpportunities.test.ts` tests pass | Unchanged |
| All existing `researchInsights.test.ts` tests pass | Unchanged |
| Dashboard Moneyline columns unaffected | No regressions |

### 14.12 Error and Partial-Data Cases

| Test | Criterion |
|---|---|
| One sportsbook has Totals; other does not | One row returned; no error |
| `totals` key absent from API response | Frontend renders "No totals available" |
| `total_line` is null in DB | Not possible with `NOT NULL`; constraint catches at insert |

### 14.13 Quota-Safe Provider Testing Approach

Do not run the full Totals diagnostic during automated test runs. Use pre-recorded API response fixtures (from the Phase 13 Sprint 4 diagnostic output) for unit and integration tests. Provider calls in CI must be mocked.

---

## 15. Backward Compatibility

### 15.1 Existing Moneyline Behavior

No Moneyline code path is modified. `_normalize_odds()` in `odds_api_io.py` retains its `name == "ML"` filter. `save_odds()` writes only to `odds_history`. Research router queries of `odds_history` are unchanged.

### 15.2 Existing Stored Moneyline Data

With Option B (separate `totals_history` table): `odds_history` is never touched. All existing rows are fully preserved.

### 15.3 Existing API Consumers

All existing endpoints return the same shapes. The `odds` key in research responses is unchanged. The `totals` key is additive and optional. Frontend code that does not reference `game.totals` will not be affected.

### 15.4 Existing Frontend Flows

Dashboard, game detail, comparison, and board all function identically for Moneyline. Totals additions are new sections alongside existing ones.

### 15.5 Existing Workspaces and Saved Selections

Workspace entries are `game_id` integers stored in `localStorage`. Adding Totals does not change the workspace storage schema. Existing saved games continue to load correctly.

### 15.6 Existing Scheduler Behavior

No scheduler changes. `save_live_data.py` is updated to add Totals fetching and persistence — the script file called by the existing Task Scheduler jobs.

### 15.7 Existing Batch Ingestion Behavior

`run_ingestion.bat` is unchanged. The additional Totals steps in `main()` execute transparently.

### 15.8 Existing Tests

All existing tests must pass without modification. Any new test failures in the existing suite are regressions that must be fixed before the Totals implementation sprint ships.

### 15.9 Potential Breaking Changes Requiring Explicit Approval

- Dropping `NOT NULL` from `odds_history.home_moneyline` or `odds_history.away_moneyline` (required by Option A) is a breaking schema change. This would need PM approval and explicit rollback plan.
- Adding a required (non-optional) `market_type` column to `odds_history` that defaults to `'moneyline'` is a breaking schema change for existing migration scripts. Requires PM approval.
- Changing `MarketType` from a string literal to an enum is a TypeScript breaking change. Not required for MVP.

---

## 16. API-Rate and Data-Integrity Risks

### 16.1 Increased Provider Requests

| Scenario | Current calls/day | After Totals (Option A combined) | After Totals (Option B separate) |
|---|---|---|---|
| Events list (1 per run) | 2 | 2 | 2 |
| Per-game odds requests | ~15–18 per run | ~15–18 per run (combined) | ~30–36 per run |
| Total per run | ~17–20 | ~17–20 | ~32–38 |
| Daily (2 runs) | ~34–40 | ~34–40 | ~64–76 |

Free tier: 100 requests/hour. Both options remain within limits at current scale.

**Mitigation:** Monitor the `X-Requests-Remaining` header (if provided by OddsAPI.io) and log it. Add a warning when remaining requests fall below 20.

### 16.2 Duplicate Ingestion

Snapshot-append design means re-running ingestion for the same game produces duplicate rows. The "latest" query pattern (`DISTINCT ON ... ORDER BY recorded_at DESC`) handles this correctly.

**Risk:** If ingestion runs more frequently than intended (e.g., scheduler misconfiguration), the database grows without bound. Mitigation: add a row count monitor to the health endpoint.

### 16.3 Partial Sportsbook Data

If Bet365 posts Totals but DraftKings does not, the research response will show only one book's Totals. This is correct behavior. No deduplication issue arises because rows are per-sportsbook.

### 16.4 Stale Prices

Totals odds may be posted hours before game time. If ingestion runs at 11 AM but the game is at 7 PM, the 11 AM line is captured but may not reflect the final pre-game line. The 7 PM ingestion run provides a later snapshot.

**Mitigation:** The `recorded_at` timestamp on every row allows the researcher to assess freshness. Display `recorded_at` (or `provider_updated_at` if stored) in the frontend.

### 16.5 Line Movement Tracking

The total line itself (`hdp`) may move between ingestion runs (e.g., from 8.5 to 9.0). The snapshot-append model captures this naturally. Line movement for Totals is computed the same way as Moneyline: first row vs. latest row per `game_id + sportsbook`.

### 16.6 Over/Under Line Mismatch

If the `total_line` differs between Bet365 and DraftKings for the same game (e.g., 8.5 vs. 9.0), both are stored as separate rows. The frontend should display both without attempting to merge them. This is a real provider scenario and is handled correctly by the per-sportsbook storage model.

### 16.7 Event Matching Failure

If `find_matching_game()` fails to match a Totals record (zero name overlap score), the record is skipped. Unlike Moneyline, Totals records do not have a "swapped" version — the total line is not directional. Matching failures should be logged with the unmatched event details for investigation.

### 16.8 Provider Payload Changes

OddsAPI.io may rename the `"Totals"` market, change the `hdp`/`over`/`under` field names, or restructure the bookmakers dict. The fetcher must log unrecognized market names as warnings rather than silently discarding them.

### 16.9 Null or Malformed Values

Handled by validation rules in Section 6. Records with any null or unparseable field are rejected at the normalization stage.

### 16.10 Transaction Failures

If the database INSERT for Totals fails (e.g., foreign key violation because `game_id` does not exist), the entire transaction rolls back — including all other data saved in that run. This is the existing behavior for Moneyline and is acceptable.

**Mitigation:** Save games before saving odds or totals (existing order in `main()` is correct). If `save_games()` succeeds, `game_id` references will be valid.

### 16.11 Historical Data Growth

Two ingestion runs per day × 15–18 games per day × two sportsbooks = 60–72 Totals rows per day. This is negligible at current scale.

---

## 17. Multi-Market Extensibility

### 17.1 Market-Neutral Contracts

The `MarketOpportunity` type is already market-neutral. The `MarketOpportunityGenerator` pattern with `supportedMarket` field allows each generator to declare which market it serves without any framework change.

**To add a future market (e.g., Run Line):**
1. Add `"FULL_GAME_RUN_LINE"` to the `MarketType` union.
2. Create a new table (e.g., `runline_history`) or extend the schema.
3. Add a fetcher function.
4. Add persistence.
5. Extend the research router.
6. Register generators in `OPPORTUNITY_GENERATORS`.

No existing code requires modification to support this pattern.

### 17.2 Market-Specific Strategies

The fetcher currently has one function (`get_moneyline_odds()`). A clean extensibility pattern is one function per market:

```python
get_moneyline_odds()   # existing
get_totals_odds()      # proposed
get_runline_odds()     # future
```

Each returns a list of market-specific dicts. `main()` calls each independently with isolated failure handling.

### 17.3 Typed Side/Outcome Representation

Moneyline: `side = "home"` or `"away"` (string, not an enum).

Totals: `side = "over"` or `"under"` (proposed string, same pattern).

A future `BetSide` type or enum could unify these, but this is premature until three or more markets exist.

### 17.4 Line-Bearing vs. Non-Line-Bearing Markets

Totals and Run Line are line-bearing markets (they have a numeric line in addition to prices). Moneyline is non-line-bearing. The `total_line` field in `totals_history` establishes the pattern for line-bearing markets. Future line-bearing markets would follow the same schema pattern.

### 17.5 Shared Research Context

Game-level context (weather, pitchers, injuries, bullpen, form) is shared across all markets. The research router already assembles this context once per game and can include it in both Moneyline and Totals responses without duplication.

### 17.6 Frontend Extensibility

`MarketType.replace(/_/g, " ")` renders any future market type correctly with no code change. The opportunity card and board rendering are market-neutral for title, summary, reasons, and cautions. Only the "Available Odds" section requires a market-type rendering branch.

### 17.7 Sport Boundaries

This architecture document is for MLB baseball only. No NBA or NHL design work is included. Future sport support would require separate provider configuration, separate team/game tables, and separate market types.

---

## 18. Recommended Later Implementation Sequence

This is a recommendation for Project Manager consideration. No sprint is authorized by this document. Future implementation phase and sprint numbering will be assigned only after explicit Project Manager approval.

### Proposed Database Foundation Stage

**Objective:** Create `totals_history` table.

**Dependencies:** PM approval of database design (Option B recommended).

**Expected affected layers:** `database/migrations/005_add_totals_history.sql`

**Required tests:** In an isolated non-production test database — migration runs without error; table accepts valid rows; destructive rollback testing (DROP TABLE) confirms `odds_history` row count and all existing Moneyline queries are unaffected. The live database must never be used for destructive rollback testing.

**Principal risks:** Schema migration must be applied to the live database; rollback plan must be confirmed and validated in an isolated non-production test environment before live execution.

**Non-goals:** No backend code changes; no data backfill.

---

### Proposed Provider Integration Stage

**Objective:** Add `get_totals_odds()` and `_normalize_totals()` to `backend/fetchers/odds_api_io.py`.

**Dependencies:** Database Foundation Stage complete (table exists to receive data).

**Expected affected layers:** `backend/fetchers/odds_api_io.py`

**Required tests:** Unit tests for parser (all cases from Section 14.1); normalization tests.

**Principal risks:** Provider response format changes; quota consumption increase.

**Non-goals:** No ingestion wiring; no research router changes.

---

### Proposed Ingestion Persistence Stage

**Objective:** Wire `get_totals_odds()` into `save_live_data.py::main()`. Add `save_totals()`. Add Totals log lines.

**Dependencies:** Provider Integration Stage complete.

**Expected affected layers:** `backend/scripts/save_live_data.py`

**Required tests:** Persistence tests; ingestion integration tests; regression against Moneyline ingestion.

**Principal risks:** Transaction failure if game matching is wrong; duplicate ingestion patterns.

**Non-goals:** No API changes; no frontend changes.

---

### Proposed Backend API Stage

**Objective:** Extend `_get_research_for_date()` and `_get_research_for_game()` in `research.py` to query `totals_history` and include a `totals` key in the response. Add `GET /totals/today` endpoint.

**Dependencies:** Ingestion Persistence Stage complete (data must exist in `totals_history`).

**Expected affected layers:** `backend/routers/research.py`, `backend/routers/odds.py` (new totals router or additions)

**Required tests:** API contract tests; regression against existing research endpoint shapes.

**Principal risks:** Research router performance (additional JOIN); existing tests must pass.

**Non-goals:** No frontend changes; no opportunity generation.

---

### Proposed Research Integration Stage

**Objective:** Add a Totals-specific insight generator to `researchInsights.ts` (e.g., run differential context). Extend `InsightableGame` to include `totals` field.

**Dependencies:** Backend API Stage complete (API returns `totals`).

**Expected affected layers:** `frontend/lib/researchInsights.ts`, `frontend/lib/researchInsights.test.ts`

**Required tests:** Unit tests for new generator; regression against all existing insight tests.

**Principal risks:** `InsightableGame` type extension must remain optional (backward-compatible with existing test helpers).

**Non-goals:** No opportunity generation; no UI changes.

---

### Proposed Opportunity Layer Stage

**Objective:** Add `"FULL_GAME_TOTALS"` to `MarketType`. Register a Totals opportunity generator in `marketOpportunities.ts`.

**Dependencies:** Research Integration Stage complete.

**Expected affected layers:** `frontend/lib/marketOpportunities.ts`, `frontend/lib/marketOpportunities.test.ts`

**Required tests:** Opportunity unit tests; regression against Moneyline opportunity tests.

**Principal risks:** Generator must not fire when no Totals data is present.

**Non-goals:** No board UI changes; no game detail UI changes.

---

### Proposed Frontend Integration Stage

**Objective:** Add Totals display to game detail page, dashboard table, comparison table, and board card. Add market filter to board.

**Dependencies:** Opportunity Layer Stage complete.

**Expected affected layers:** `frontend/app/page.tsx`, `frontend/app/game/[game_id]/page.tsx`, `frontend/app/opportunities/page.tsx`

**Required tests:** Board renders Totals opportunities; game detail Totals section appears; comparison table Totals rows appear; existing UI regression testing.

**Principal risks:** Type additions must be optional; empty state handling for games without Totals.

**Non-goals:** No workspace structural changes; no parlay builder work.

---

### Proposed Validation and Release Stage

**Objective:** Run full test suite. Verify end-to-end Totals flow. Verify all Moneyline regression tests pass. Document known limitations.

**Dependencies:** Frontend Integration Stage complete.

**Expected affected layers:** Documentation updates only.

**Required tests:** All backend pytest tests pass; all frontend vitest tests pass; manual end-to-end check.

**Principal risks:** Latent type mismatches between API shape and frontend type definitions.

**Non-goals:** No new features; no new markets.

---

## 19. Architecture Decisions and Open Questions

| # | Decision Topic | Verified Repository Evidence | Available Options | Recommended Option | Tradeoffs | PM Approval Required | Implementation Blocked |
|---|---|---|---|---|---|---|---|
| D1 | Database design for Totals odds storage | `odds_history` has `NOT NULL` on `home_moneyline`/`away_moneyline`; no market type column | A: Add columns to `odds_history`; B: New `totals_history` table | **Option B** | B: cleaner isolation, safe rollback, no Moneyline risk; A: one table, complex queries | Yes | Yes |
| D2 | Provider request strategy | `markets='ML,totals'` and `markets='totals'` both return HTTP 200; free tier allows 100 req/hour; 2 runs/day × ~18 games = well within limits for either option | A: Combined `markets='ML,totals'`; B: Separate requests | **Option B (separate)** | B: failure isolation; A: fewer API calls | Yes | No (either works) |
| D3 | MarketType representation | Currently `type MarketType = "FULL_GAME_MONEYLINE"` (TS string literal union) | Extend union vs. convert to enum | **Extend union** | Union is already in use; minimal change; enum more robust at scale | No | No |
| D4 | Workspace identity for Totals | Current workspace uses `game_id: number` only; no market type in identity | Keep game-only identity vs. add `game_id + market_type` identity | **Keep game-only for MVP** | Simpler; researcher uses notes textarea for market annotation | No (PM aware) | No |
| D5 | Totals opportunity side/direction | `MarketOpportunity` has no `direction` field currently | Keep market-level only vs. add `direction: "over" | "under"` | **Market-level only for MVP** (consistent with Moneyline) | No direction = researcher decides; adds direction = prescriptive risk | No (PM aware) | No |
| D6 | Research data requirements for Totals insights | `last_10_run_diff` and weather exist; pitcher stats do not | Use existing data only vs. add pitcher stats before insights | **Existing data only for MVP** | Pitcher stats require new sprint; run diff + weather sufficient for MVP insight | No | No |
| D7 | Totals line movement tracking | `odds_history` movement uses `DISTINCT ON ... ORDER BY recorded_at DESC` for first vs. latest | Same pattern on `totals_history` vs. separate line movement table | **Same pattern on `totals_history`** | Consistent; no new infrastructure needed | No | No |
| D8 | `provider_updated_at` storage | Provider returns `updatedAt` per market; not currently stored for Moneyline | Store `provider_updated_at` vs. `recorded_at` only | **Store `recorded_at` only for MVP** (consistent with Moneyline) | `provider_updated_at` useful for freshness monitoring; can add later | No | No |

---

## 20. File Impact Map

This map describes the likely future changes when implementation is authorized. It is planning only — nothing has been changed in this sprint.

### Files Likely to Be Modified Later

**Backend:**
- `backend/fetchers/odds_api_io.py` — add `get_totals_odds()`, `_normalize_totals()`
- `backend/scripts/save_live_data.py` — add `save_totals()`, wire into `main()`
- `backend/routers/research.py` — extend `_get_research_for_date()`, `_get_research_for_game()` to query `totals_history`

**Frontend:**
- `frontend/lib/marketOpportunities.ts` — add `"FULL_GAME_TOTALS"` to `MarketType`, add Totals generator, extend `OpportunityContext`
- `frontend/lib/researchInsights.ts` — extend `InsightableGame` with optional `totals` field, add Totals insight generator
- `frontend/app/page.tsx` — add `TotalsOdds` type, Totals table columns to game row, Totals rows to `ComparisonTable`
- `frontend/app/game/[game_id]/page.tsx` — add `totals?: TotalsOdds[]` to `GameDetail` type, add "Totals" section
- `frontend/app/opportunities/page.tsx` — add Totals odds rendering branch in board card

### Files Likely to Be Added Later

**Database:**
- `database/migrations/005_add_totals_history.sql` — `CREATE TABLE totals_history`

**Backend:**
- `backend/routers/totals.py` — `GET /totals/today`, `GET /totals/movement` (or added to `odds.py`)
- `backend/tests/test_totals_parser.py` — unit tests for `_normalize_totals()`
- `backend/tests/test_totals_persistence.py` — tests for `save_totals()`
- `backend/tests/test_totals_api.py` — API contract tests

**Frontend:**
- Additions to `frontend/lib/marketOpportunities.test.ts` — Totals opportunity tests
- Additions to `frontend/lib/researchInsights.test.ts` — Totals insight tests

### Files That Should Remain Unchanged

**Database:**
- `database/schema.sql` — base schema unchanged (migration adds new table)
- `database/migrations/002_add_game_weather.sql` through `004_add_team_injuries.sql` — unchanged

**Backend (Moneyline-specific — must not change):**
- `backend/routers/odds.py` — Moneyline-only; no Totals additions here
- `backend/services/team_form.py` — market-neutral; unchanged
- `backend/services/streak.py` — market-neutral; unchanged
- `backend/odds_math.py` — reused without modification
- `backend/db.py` — unchanged
- `backend/main.py` — unchanged (router registration unchanged at MVP)
- `backend/tests/test_research_endpoints.py` — must pass without modification
- `backend/tests/test_health_ingestion.py` — must pass without modification
- `backend/tests/test_data_quality.py` — must pass without modification

**Frontend (logic files not touched by Totals — must not change):**
- `frontend/lib/gameFilters.ts` — market-neutral; unchanged
- `frontend/lib/gameFlags.ts` — market-neutral; unchanged
- `frontend/lib/gameFlagSummary.ts` — unchanged
- `frontend/lib/marketResearchBoard.ts` — unchanged (board builds entries from existing generators)
- `frontend/components/ResearchFlags.tsx` — unchanged

**Documentation:**
- `docs/MARKET_RESEARCH_ARCHITECTURE.md` — update proposed (Section 6.2 and Section 2.2 describe Totals as BLOCKED; diagnostic has confirmed TOTALS AVAILABLE — update pending PM approval per Section 12 of earlier report)
- `docs/ORACLE_PAPER_BET_TRACKING_RULES.md` — unchanged
- `docs/PHASE_13_14_OPERATIONAL_DECISION_TREE.md` — unchanged
- `docs/ODDS_API_SETUP.md` — minor update proposed to reflect confirmed Totals availability

**Operations:**
- `backend/scripts/run_ingestion.bat` — unchanged
- `logs/` — unchanged (log files, not repository artifacts)
- `.claude/settings.local.json` — unchanged

---

*All file paths, type names, function names, field names, SQL schemas, and behavioral descriptions in this document are derived from direct inspection of repository files at commit `8c478926`. No assumptions have been introduced that are not supported by observed repository evidence. Provider behavior is based on the Phase 13 Sprint 4 controlled diagnostic output from 2026-07-17.*

*This document is a design artifact. No implementation has occurred. No commit or push has been made. No production code, tests, migrations, or configuration files have been modified.*
