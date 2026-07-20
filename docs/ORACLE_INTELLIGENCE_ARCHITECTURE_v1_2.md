# ORACLE INTELLIGENCE ARCHITECTURE v1.2 — FINAL CANDIDATE
**Edge Oracle / MLB Betting Edge**
**Status: Submitted for Project Manager Architecture Approval**
**Supersedes:** v1.2 Corrected (non-compliant); v1.1 (analytical layer only)
**Operational Freeze:** In effect. No implementation until PM authorization.

---

## DOCUMENT AUTHORITY

This document is an architecture and planning document. It does not constitute:
- Authorization to write code
- Authorization to modify the database schema
- Authorization to run schedulers
- Authorization to change governance documents
- A freeze of the architecture it describes

Only the Project Owner and Project Manager may approve and freeze this architecture.

---

## SECTION 1 — ARCHITECTURE OVERVIEW

### 1.1 Two-Layer Design

The Edge Oracle operates as a single unified system composed of two inseparable layers.

**Layer A — Intelligence Pipeline**
The analytical process that evaluates a game and market. Contains five sequential engines (PHIE, GSE, MVE, CE, LE) plus three supporting frameworks (ECF, ODG, SRL). Produces analytical verdicts that inform play decisions.

**Layer B — Automation and Orchestration**
The operational process that drives the system each day. Contains the Run Orchestrator, provider adapters, event model, conditional play management, settlement, and reporting. Layer B is not a deferred enhancement — it is a required component of the Oracle operating model from day one.

**Layer boundary:** The two layers are architecturally distinct (separate responsibilities, separate codebases) but operationally inseparable. Layer B drives Layer A and acts on Layer A's outputs. Neither layer is optional.

**What automation means here:** Automated paper-bet creation and management. Real-money wagering is explicitly outside scope and must never be proposed, designed, or implied.

### 1.2 Combined Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER B — AUTOMATION AND ORCHESTRATION                             │
│                                                                     │
│  Provider Adapters         Run Orchestrator        Event Store      │
│  ┌───────────────────┐    ┌─────────────────┐    ┌─────────────┐  │
│  │ ScheduleProvider  │    │  Stage Manager  │    │ oracle_play │  │
│  │ GameStatusProvider│───▶│  State Machine  │───▶│  _events    │  │
│  │ SPProvider        │    │  Retry Logic    │    │ (append-    │  │
│  │ LineupProvider    │    │  Kill Switch    │    │  only)      │  │
│  │ OddsProvider      │    └────────┬────────┘    └─────────────┘  │
│  │ WeatherProvider   │             │                               │
│  │ ResultsProvider   │    ┌────────▼────────┐                     │
│  │ [+ others below]  │    │ Identifier      │                     │
│  └───────────────────┘    │ Lifecycle Mgr   │                     │
│                           │ Eval/Candidate/ │                     │
│                           │ Play ID         │                     │
│                           └────────┬────────┘                     │
└────────────────────────────────────┼────────────────────────────────┘
                                     │  triggers
┌────────────────────────────────────▼────────────────────────────────┐
│  LAYER A — INTELLIGENCE PIPELINE                                    │
│                                                                     │
│  ECF ──────────────────────────────────────────────────────────┐   │
│                                                                 ▼   │
│  PHIE ──▶ GSE ──▶ MVE ──▶ CE ──▶ ODG ──▶ SRL ──▶ Play Decision  │
│                                            │                        │
│  LE (backward feedback only) ◀─────────────┘                       │
│                                                                     │
│  Recalculation: dependency-based, not ECF-threshold-gated          │
└─────────────────────────────────────────────────────────────────────┘
                                     │
                              ┌──────▼──────┐
                              │ Interactive │
                              │ Oracle Path │
                              │ (Custom GPT │
                              │  read-only) │
                              └─────────────┘
```

### 1.3 Two Access Paths

**Autonomous Execution Path:** Layer B drives the full daily lifecycle automatically. Run Orchestrator triggers all stages, polling all provider adapters on the configured schedule. No human input required for daily operation.

**Interactive Oracle Path:** Project Owner accesses current analytical state via the Custom GPT read interface. The GPT may ask questions; it may never trigger stages, write records, or activate plays.

---

## SECTION 2 — TECHNOLOGY STATUS REGISTRY

Every technology is labeled with its current status. No technology is described as existing without verified evidence from the repository.

| Technology | Status | Evidence / Notes |
|---|---|---|
| **PostgreSQL** | Existing and verified (technology integration) — operational instance status requires Project Owner verification | `backend/db.py` uses psycopg2; `save_live_data.py` writes to multiple tables; `backend/scripts/test_db_connection.py` tests connection; multiple routers query the database |
| **Python / FastAPI** | Existing and verified | `backend/main.py` is a running FastAPI application with five routers |
| **Next.js (React)** | Existing and verified | Frontend framework per CLAUDE.md; project structure confirmed |
| **MLB Stats API** | Existing and verified | `backend/fetchers/mlb_stats_api.py` confirmed; provides games, probable starting pitchers, team records, and bullpen innings (via boxscore endpoint); free, no API key required |
| **OddsAPI.io** | Existing and verified | `backend/fetchers/odds_api_io.py` confirmed; Bet365 + DraftKings locked sportsbook set; free tier; moneyline (ML) market only in current fetcher |
| **Bet365** | Existing and verified | Locked sportsbook on free OddsAPI.io tier; confirmed in `odds_api_io.py` line 48 |
| **DraftKings** | Existing and verified | Locked sportsbook on free OddsAPI.io tier; confirmed in `odds_api_io.py` line 48 |
| **Open-Meteo** | Existing and verified | `backend/fetchers/weather.py` confirmed; free, no API key required; provides temperature, wind speed, wind direction, and precipitation probability; STADIUM_COORDS covers all 30 MLB team home stadiums; integrated in `save_live_data.py`; `game_weather` table confirmed in production queries; five tests in `backend/tests/test_weather.py` |
| **ESPN unofficial MLB injury API** | Existing, operational stability requires verification | `backend/fetchers/injuries.py` confirmed; provides player_name, injury_status, and injury_description for all MLB teams; no API key required; unofficial endpoint at `https://site.api.espn.com` — not governed by a public SLA; integrated in `save_live_data.py`; writes to `team_injuries` table |
| **SportsDataIO** | Candidate provider — not selected | `backend/fetchers/sportsdataio.py` exists but is paused (docstring: "PAUSED. Not used right now."); no subscription authorized; must not be assumed as an existing provider for any Oracle adapter interface |
| **PyBaseball / Baseball Savant** | Requires authorization | PyBaseball wraps public Statcast data; required for PHIE Categories 2–4; no authorization or integration exists; PM authorization required before use |
| **APScheduler** | Recommended | Candidate job scheduler for Run Orchestrator; not installed or authorized |
| **Celery** | Alternative | Alternative distributed task queue; requires Redis; not installed or authorized |
| **Redis** | Recommended (if Celery selected) | Required dependency if Celery is chosen; not installed or authorized |
| **OpenAI API** | Requires PM authorization | Candidate LLM provider (PM Decision Point 1); not integrated into Oracle; no Oracle API key provisioned |
| **Anthropic API** | Requires PM authorization | Alternative LLM provider (PM Decision Point 1); claude-sonnet-4-6 available in current environment but not authorized for Oracle analytical calls |
| **Umpire provider** | Missing source | No programmatic source identified; ECF Category 4 umpire sub-component defaults to 0 points when unknown; known accepted limitation |

---

## SECTION 3 — PROVIDER ADAPTER ARCHITECTURE

### 3.1 Design Principle

The Oracle defines required adapter interfaces. It does not hard-code specific vendor implementations. The current implementation of each interface is recorded separately from the interface definition. Changing the provider for an interface does not require redesigning the consuming engine.

### 3.2 Required Adapter Interfaces

**Interface 1: ScheduleProvider**
- Purpose: Retrieve today's MLB game schedule with game identifiers, teams, start times, and venue
- Current implementation: MLB Stats API (existing and verified)
- Canonical game identifier: MLB Stats API `gamePk` stored as `external_game_id` — this is the current canonical game identifier for the Oracle. All inter-service references use this identifier format unless PM authorization establishes a different canonical mapping
- Fallback: cached prior-day schedule with staleness warning
- Missing capability: does not provide odds; does not provide confirmed lineup status
- Provider evaluation requirement: none; current implementation is verified

**Interface 2: GameStatusProvider**
- Purpose: Monitor live game status (scheduled, delayed, postponed, in-progress, final)
- Current implementation: MLB Stats API (existing and verified)
- Fallback: scheduled status assumed until update; staleness warning logged
- Missing capability: real-time delay notifications may lag
- Provider evaluation requirement: none; current implementation is verified

**Interface 3: StartingPitcherProvider**
- Purpose: Retrieve probable and confirmed starting pitchers for each game
- Current implementation: MLB Stats API (existing and verified) — `get_todays_games()` uses `hydrate=probablePitcher,team` and returns `home_pitcher: str or None` and `away_pitcher: str or None`; the current standard shape does not include a confirmation flag field; SP confirmation status must be inferred from non-null presence (probable pitcher listed) vs. null (no pitcher announced), which does not distinguish between "confirmed" and "probable"; Phase 2 must determine whether MLB Stats API exposes a pitcher confirmation field and, if so, add it to the fetcher standard shape
- Fallback: ECF SP Certainty category hard-capped at 0 points if both SPs unconfirmed; ECF total hard-capped at 50 if either SP unconfirmed
- Missing capability: Statcast arsenal data; historical SP vs. lineup splits; explicit SP confirmation flag in current standard shape
- Provider evaluation requirement: Statcast arsenal data requires PyBaseball authorization (PM Decision Point 4); SP confirmation field requires Phase 2 MLB Stats API endpoint evaluation

**Interface 4: LineupProvider**
- Purpose: Retrieve submitted and confirmed batting lineups
- Current implementation: MLB Stats API lineup endpoint — not yet implemented in current codebase. `mlb_stats_api.py` currently provides probable pitchers only (via `hydrate=probablePitcher,team` on the schedule endpoint). Confirmed batting lineup retrieval requires a separate MLB Stats API endpoint that has not yet been added to the fetcher. Phase 2 must implement this endpoint and confirm that the MLB Stats API provides confirmed starting lineups once submitted
- Fallback: ECF Lineup Certainty reduced; projected lineup noted in analysis with explicit "projected" flag; recalculation triggered immediately upon confirmation
- Missing capability: confirmed lineup retrieval — must be added in Phase 2 as a new function in `mlb_stats_api.py`; the lineup polling workflow (Section 7.2) depends on this endpoint being implemented before Phase 4 can operate
- Provider evaluation requirement: confirm that MLB Stats API provides confirmed batting lineups once submitted and identify the correct endpoint; this is a Phase 2 implementation dependency, not a provider selection decision

**Interface 5: PlayerStatusProvider**
- Purpose: Retrieve injury, roster, and availability status for players in submitted lineups
- Current implementation: ESPN unofficial injury API (existing; operational stability requires verification) — `backend/fetchers/injuries.py`; provides player_name, injury_status, and injury_description for all MLB teams; no API key required; unofficial endpoint at `https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries`; not governed by a public SLA; integrated in `save_live_data.py` and writes to `team_injuries` table
- Fallback: no injury data; ECF flagged; analysis proceeds without player status input
- Missing capability: intra-day scratch announcements may not appear immediately; does not distinguish between IL stints and day-to-day designations; no return-to-active timeline; stability of unofficial endpoint not guaranteed
- Provider evaluation requirement: stability of the ESPN unofficial endpoint should be evaluated before relying on it operationally; MLB Stats API does have transaction endpoints but none are currently implemented in the codebase

**Interface 6: StatisticsProvider**
- Purpose: Retrieve advanced player and pitcher statistics required by analytical engines
- Sub-interface A — Standard statistics: MLB Stats API (existing and verified) — career and season lines
- Sub-interface B — Statcast / arsenal / contact quality: PyBaseball wrapping Baseball Savant (requires authorization)
  - Without this: PHIE Categories 2 (Arsenal vs. Swing Profile), 3 (Plate Discipline), and 4 (Contact Quality) operate at projected tier only
  - ECF Statistical Data Quality category reduced accordingly
  - PM Decision Point 4 required before integration
- Fallback for Sub-interface B: degraded PHIE output with explicit "Statcast unavailable" flag; engines proceed with reduced confidence
- Provider evaluation requirement: PM authorization required for PyBaseball

**Interface 7: OddsProvider**
- Purpose: Retrieve current betting odds for authorized markets from the locked sportsbook set
- Current implementation: OddsAPI.io (existing and verified); Bet365 and DraftKings locked sportsbook set
- Cross-provider game identifier note: OddsAPI.io uses its own `event_id` which is separate from and incompatible with the MLB Stats API `external_game_id` (gamePk). Cross-provider game reconciliation currently uses fuzzy team-name and date matching implemented in `backend/scripts/save_live_data.py` (`find_matching_game()` function). Phase 2 must formalize this matching into the OddsProvider adapter contract to ensure correct game-to-odds association in the Oracle pipeline
- Authorized market coverage (verified):
  - Full-game moneyline: confirmed via live test call (Bet365 + DraftKings); current fetcher filters to market name "ML" only
  - Full-game totals: included per provider documentation; operational verification required (see `backend/scripts/diagnostics/check_oddsapi_totals.py`)
  - F5 moneyline: provider evaluation required; not operationally verified
  - F5 totals: provider evaluation required; not operationally verified
  - NRFI/YRFI: provider evaluation required; uncertain coverage
- Fallback: stale odds cache with age timestamp; MVE confidence degraded; candidate not activated with stale odds
- Provider evaluation requirement: F5, totals, NRFI/YRFI coverage requires verification before those markets are added to the autonomous pipeline

**Interface 8: WeatherProvider**
- Purpose: Retrieve pre-game weather forecast (temperature, wind speed/direction, precipitation probability) for outdoor stadiums
- Current implementation: Open-Meteo (existing and verified) — `backend/fetchers/weather.py`; free, no API key required; provides temperature, wind_speed, wind_direction, and precipitation_chance; `STADIUM_COORDS` maps all 30 MLB team abbreviations to home stadium latitude/longitude; integrated in `save_live_data.py`; writes to `game_weather` table; five tests in `backend/tests/test_weather.py`
- Fallback: if Open-Meteo is unreachable, ECF Environmental Certainty weather sub-component defaults to 0 points; explicitly flagged in ECF output
- Missing capability: Open-Meteo provides current conditions at time of ingestion, not a forward-projected game-time forecast; for games with first pitch several hours after ingestion runs, conditions at ingestion time may differ from game-time conditions (see PM Decision Point 5 — verification required); retroactive weather data not provided; indoor/retractable-roof stadiums receive weather data regardless of roof status
- Provider evaluation requirement: none for provider selection — Open-Meteo is already implemented; PM Decision Point 5 is a verification item, not a selection decision

**Interface 9: UmpireProvider**
- Purpose: Retrieve umpire assignment (home plate umpire) before game start
- Current implementation: none — no programmatic source identified
- Fallback: ECF Environmental Certainty umpire sub-component defaults to 0 points; explicitly flagged in ECF output
- Missing capability: no known free programmatic source; manual entry is the only current path
- Provider evaluation requirement: accept 0-point default as known limitation; revisit at 100-play LE milestone (PM Decision Point 6)

**Interface 10: ResultsProvider**
- Purpose: Retrieve final game scores, box scores, and line scores for settlement
- Current implementation: MLB Stats API (existing and verified) — provides final scores and box scores via the boxscore endpoint; same endpoint used by `get_bullpen_innings()` in current codebase
- Fallback: settlement deferred to next run cycle; settlement_status set to pending_retry
- Missing capability: does not provide closing-line odds for CLV calculation (see OddsProvider)
- Provider evaluation requirement: none for results; CLV requires OddsProvider closing-line capture (see timing config)

### 3.3 Provider Selection Rules

1. No provider may be added to any interface without PM authorization.
2. SportsDataIO may appear in provider evaluation documents as a candidate only. It is not a selected provider for any interface.
3. The locked sportsbook set (Bet365 and DraftKings) is established by the OddsAPI.io free tier account. It is not configurable by the Oracle.
4. The canonical game identifier is the MLB Stats API `gamePk` (stored as `external_game_id`) unless PM authorization explicitly establishes a different canonical mapping.

---

## SECTION 4 — MARKET STATUS REGISTRY

Every market is classified across five independent dimensions. No market may be labeled "Authorized" solely because it appears in analytical planning.

### 4.1 Dimension Definitions

| Dimension | What It Measures |
|---|---|
| **Playbook Status** | Is there a ratified Oracle Market Playbook? |
| **Data Availability Status** | Can the Oracle obtain the data required to analyze this market? |
| **Application Implementation Status** | Has the Oracle pipeline been built and tested for this market? |
| **Settlement Test Status** | Has settlement logic been validated end-to-end for this market? |
| **Autonomous Paper-Bet Authorization Status** | Is the Oracle authorized to autonomously create paper bets for this market? |

### 4.2 Market Classifications

**Full-Game Moneyline**

| Dimension | Status |
|---|---|
| Playbook Status | Ratified — MONEYLINE_PLAYBOOK.md v1.0 (2026-07-19) |
| Data Availability Status | Verified — OddsAPI.io confirmed via live test call (Bet365 + DraftKings); MLB Stats API for game and SP data |
| Application Implementation Status | Not built — architecture defined; no pipeline code exists yet |
| Settlement Test Status | Not tested — settlement logic designed; no end-to-end test performed |
| Autonomous Paper-Bet Authorization Status | Target market for Phase 4 — authorized once pipeline passes Phase 3 acceptance criteria |

**Full-Game Totals**

| Dimension | Status |
|---|---|
| Playbook Status | Ratified — TOTALS_PLAYBOOK.md v1.0 (2026-07-19) |
| Data Availability Status | Requires verification — OddsAPI.io documentation indicates totals coverage; operational verification required |
| Application Implementation Status | Not built |
| Settlement Test Status | Not tested |
| Autonomous Paper-Bet Authorization Status | Not authorized — requires data verification and pipeline implementation |

**F5 Moneyline**

| Dimension | Status |
|---|---|
| Playbook Status | Ratified — FIRST_FIVE_PLAYBOOK.md v1.0 (2026-07-19) |
| Data Availability Status | Requires verification — OddsAPI.io F5 market coverage unconfirmed on free tier |
| Application Implementation Status | Not built |
| Settlement Test Status | Not tested |
| Autonomous Paper-Bet Authorization Status | Not authorized — requires data verification and pipeline implementation |

**F5 Totals**

| Dimension | Status |
|---|---|
| Playbook Status | Ratified — TOTALS_PLAYBOOK.md v1.0 covers F5 totals |
| Data Availability Status | Requires verification |
| Application Implementation Status | Not built |
| Settlement Test Status | Not tested |
| Autonomous Paper-Bet Authorization Status | Not authorized |

**NRFI / YRFI**

| Dimension | Status |
|---|---|
| Playbook Status | Ratified — NRFI_YRFI_PLAYBOOK.md v1.0 (2026-07-19) |
| Data Availability Status | Requires verification — OddsAPI.io NRFI/YRFI coverage uncertain on free tier |
| Application Implementation Status | Not built |
| Settlement Test Status | Not tested |
| Autonomous Paper-Bet Authorization Status | Not authorized |

**Hitter Props**

| Dimension | Status |
|---|---|
| Playbook Status | Not authorized — no ratified playbook |
| Data Availability Status | Requires evaluation |
| Application Implementation Status | Not built |
| Settlement Test Status | Not tested |
| Autonomous Paper-Bet Authorization Status | Not authorized |

**Pitcher Props**

| Dimension | Status |
|---|---|
| Playbook Status | Not authorized — no ratified playbook |
| Data Availability Status | Requires evaluation |
| Application Implementation Status | Not built |
| Settlement Test Status | Not tested |
| Autonomous Paper-Bet Authorization Status | Not authorized |

**Parlays**

| Dimension | Status |
|---|---|
| Playbook Status | Not authorized — no ratified playbook |
| Data Availability Status | Not applicable until authorized |
| Application Implementation Status | Not built |
| Settlement Test Status | Not tested |
| Autonomous Paper-Bet Authorization Status | Not authorized |

---

## SECTION 5 — DAILY LIFECYCLE CONFIGURATION

### 5.1 Configurable Timing Parameters

All daily timing values are configurable. None are frozen architecture constants. The values below are proposed initial defaults that have not been tested. PM authorization is required before these values are used in production.

| Parameter | Proposed Default | Basis |
|---|---|---|
| `preliminary_run_time` | 10:00 ET | Provides full morning context before early lineup submits |
| `lineup_monitor_window_open` | `first_pitch_time - 3h` | Opens monitoring before typical lineup submission window |
| `lineup_poll_interval` | 15 minutes | Balances freshness against MLB Stats API rate considerations |
| `final_analysis_deadline` | `first_pitch_time - 90m` | Provides time for recalculation before activation deadline |
| `candidate_activation_deadline` | `first_pitch_time - 45m` | Provides buffer for conditional resolution before lock |
| `immutable_lock_deadline` | `first_pitch_time - 3m` | Final pregame lock; no play may activate after official first pitch under any circumstance |
| `closing_line_capture_offset` | `first_pitch_time - 1m` | Captures closing line for CLV calculation |
| `odds_refresh_interval` | 30 minutes | Balances line-movement capture against OddsAPI.io rate limits |
| `game_status_poll_interval` | 10 minutes during game window | Monitors for delays, postponements, cancellations |

**Hard rule that cannot be configured away:** No play may activate at or after official first pitch. `immutable_lock_deadline` may be set earlier than `first_pitch_time - 3m` but never later.

**Timezone:** All scheduling uses America/Toronto (Eastern Time, IANA). All stored timestamps are UTC.

### 5.2 Configuration Storage

All timing values are stored as environment variables or a configuration table, not as hardcoded constants. Changes to defaults require PM authorization and documentation before taking effect.

---

## SECTION 6 — IDENTIFIER LIFECYCLE

Three distinct identifiers govern Oracle records. They are not interchangeable.

### 6.1 Evaluation ID

**Format:** `EVAL-{game_run_id}-{market}-{version}` (e.g., `EVAL-ORACLE-20260719-001-BOS-NYY-ML-v1`)
**Assigned when:** Every time any market analysis is performed — including preliminary screens, full analytical runs, and re-evaluations
**Scope:** One Evaluation ID per analysis version per market per game
**Retained:** Indefinitely; never deleted or overwritten
**Relationship to other IDs:** Multiple Evaluation IDs may exist for the same market (one per version); one Evaluation ID may produce a Candidate ID if it clears preliminary screening

### 6.2 Candidate ID

**Format:** `CAND-{game_run_id}-{market}` (e.g., `CAND-ORACLE-20260719-001-BOS-NYY-ML`)
**Assigned when:** A market clears preliminary screening and remains under active consideration for the current slate
**Scope:** One Candidate ID per market per game per daily slate. The Candidate ID is stable across re-evaluations; new evaluation versions update the candidate's `current_evaluation_version` field
**Retained:** Indefinitely; terminal state recorded
**Does not become:** A Play ID. Candidates that never reach governed nomination status terminate as candidates and are recorded as such

### 6.3 Play ID

**Format:** `EO-YYYY-NNN` (e.g., EO-2026-001)
**Assigned when:** The Oracle formally nominates a market as a governed Conditional Play or Activated Play under the Oracle Paper Bet Tracking Rules. This is a deliberate governance act, not an automatic label
**Scope:** One Play ID per governed play. Sequential within the calendar year
**Retention rules:**
- A governed Conditional Play that subsequently fails its condition retains its Play ID; mock P/L = 0; status = Expired or Voided
- A governed Conditional Play whose price ceiling is breached before activation retains its Play ID; mock P/L = 0; status = Price Breach No-Play
- A play that expires at the activation deadline retains its Play ID; mock P/L = 0; status = Expired
- A play that cannot be settled (game cancelled, no market available) retains its Play ID; status = Void

**What does not receive a Play ID:**
- Preliminary candidates that fail initial screening
- Candidates that reach no_edge verdict before governed nomination
- Candidates that produce a Pass verdict without formal nomination
- Failed re-evaluations of pre-nomination candidates

### 6.4 Identifier Lifecycle Table

```
Market enters preliminary screen
         │
         ▼
EVAL-...-v1 created
         │
    ┌────▼─────┐
    │ Fails    │──▶ Evaluation closed; no Candidate ID; no Play ID
    │ screen   │
    └────┬─────┘
         │ Clears screen
         ▼
CAND-... created
         │
    ┌────▼──────┐
    │  no_edge  │──▶ EVAL-...-v1 records no_edge; CAND status = no_edge
    │  verdict  │    (re-entry eligible if new evidence arrives before
    └───────────┘     activation deadline — see Section 8)
         │ Qualifies
         ▼
Oracle formal nomination ──▶ EO-YYYY-NNN assigned (Play ID)
         │
    ┌────▼────────────┐
    │ Conditional     │──▶ EO-YYYY-NNN retained through all outcomes
    │ or Activated    │    (condition fail, price breach, expiry, void,
    └─────────────────┘     win, loss, push)
```

---

## SECTION 7 — DAILY LIFECYCLE STAGES

### 7.1 Ten-Stage Daily Lifecycle

**Stage 1 — Slate Initialization**
- Trigger: Run Orchestrator fires at configured `preliminary_run_time`
- Inputs: None; Orchestrator starts fresh daily run
- Actions: Create `oracle_slate_runs` record; assign Slate Run ID (`ORACLE-YYYYMMDD-NNN`); initialize `daily_plays_activated = 0`; initialize `run_status = initializing`
- Failure behavior: Log failure; retry up to 3 times; alert PM if all retries fail; no games proceed without successful slate initialization
- Downstream: Stage 2

**Stage 2 — Schedule Retrieval**
- Trigger: Immediately after Stage 1
- Provider: ScheduleProvider (MLB Stats API)
- Inputs: Today's date in ET
- Actions: Retrieve all MLB games scheduled today; create `oracle_game_analyses` records; assign Game Analysis Run IDs; record MLB Stats API `gamePk` values as canonical `external_game_id`; record first pitch times in UTC
- Failure behavior: Retry 3 times with 15s/60s/300s backoff; alert PM if schedule unavailable; slate may not proceed without at least one game record
- Downstream: Stage 3 for each game

**Stage 3 — Preliminary Data Gather**
- Trigger: Per game, after Schedule Retrieval
- Providers: StartingPitcherProvider, LineupProvider, OddsProvider (for authorized markets with verified coverage), WeatherProvider, UmpireProvider (if available)
- Actions: Retrieve all available data for each game; record data age and source timestamp; flag missing data explicitly; create Evaluation IDs for each market under consideration
- Failure behavior: Missing data sources flagged; engines proceed with degraded inputs; ECF scores reduced accordingly; candidates flagged as data-incomplete
- Downstream: Stage 4

**Stage 4 — ECF Calculation (Preliminary)**
- Trigger: After Stage 3 data gather per game
- Engine: Evidence Confidence Framework (coded logic)
- Actions: Calculate preliminary ECF score (0–100) across six categories; apply SP hard ceiling (ECF cannot exceed 50 if either SP unconfirmed); store ECF score in game analysis record
- Failure behavior: ECF calculation is coded logic; failure indicates system error; alert and halt game analysis; do not proceed with analytical engines on failed ECF
- Downstream: Stage 5

**Stage 5 — Full Intelligence Pipeline (Preliminary Run)**
- Trigger: Per game, after Stage 4
- Engines: PHIE → GSE → MVE → CE → ODG → SRL (sequential); ECF score from Stage 4 is an explicit input used across all engine calls in this pipeline
- Actions: Run all five engines in sequence; LLM calls where required; create initial Candidate IDs for markets clearing preliminary screen; record all engine outputs; record evaluation version (v1) on each Evaluation ID
- LLM execution: Temperature = 0; structured JSON output; Pydantic validation; retry 2× on schema failure; retry 3× on API error (15s/60s/300s); halt game if LLM calls exceed daily token budget
- Failure behavior: Per-engine failure logged; downstream engines not invoked on upstream failure; game marked analysis_incomplete; PM alert
- Downstream: Stage 6 (lineup monitoring opens)

**Stage 6 — Lineup Monitoring and Polling**
(Full workflow in Section 7.2)
- Trigger: Per game, after Stage 5; opens at configured `lineup_monitor_window_open` relative to that game's first pitch
- Actions: Poll LineupProvider at configured `lineup_poll_interval`; detect material changes; trigger dependency-based recalculation; record all observations
- Ends when: Both lineups confirmed, OR activation deadline reached
- Downstream: Stage 7 (final analysis) when lineup resolved or deadline reached

**Stage 7 — Final Analysis and Recalculation**
- Trigger: Both lineups confirmed, OR `final_analysis_deadline` reached (whichever comes first per game)
- Actions: Run full recalculation per dependency rules (Section 9); update all Evaluation IDs to final version; update ECF; update all engine outputs; run ODG and SRL with final inputs
- Failure behavior: Stage 7 failure means no play may activate for this game; candidate expires; PM alert
- Downstream: Stage 8 (activation window)

**Stage 8 — Candidate Activation Window**
- Trigger: After Stage 7; window closes at `candidate_activation_deadline`
- Actions: For each qualifying candidate: verify ODG verdict = Activate (not Conditional Activate if condition unresolved); verify SRL tier = Top Tier; verify `daily_plays_activated < 3`; verify price is within authorized ceiling; assign Play ID (EO-YYYY-NNN) and record paper bet; increment `daily_plays_activated` atomically; set `pregame_locked_at`
- Hard constraints: No play after `immutable_lock_deadline`; database-level enforcement (CHECK constraint or equivalent mechanism) prevents `daily_plays_activated` from exceeding 3; all Play ID assignments are database-atomic operations
- Conditional plays: If ODG verdict = Conditional Activate and condition is unresolved at Stage 8, play is recorded as Conditional; monitoring continues to `immutable_lock_deadline`
- Failure behavior: Activation failure logged as immutability audit event; candidate expires; no partial play records
- Downstream: Stage 9 (pregame lock)

**Stage 9 — Pregame Lock**
- Trigger: `immutable_lock_deadline` for each game
- Actions: Set `pregame_locked_at` timestamp; application-layer and database-trigger immutability enforced; closing line captured from OddsProvider at `closing_line_capture_offset`; all pregame fields become read-only
- Failure behavior: Lock failure halts all activation; alert PM immediately; any attempt to write pregame fields after lock failure is blocked and audited
- Downstream: Stage 10 (settlement) after game completes

**Stage 10 — Settlement and CLV Calculation**
- Trigger: ResultsProvider reports final game status; poll at configured `game_status_poll_interval`
- Actions: Retrieve final score; apply market-specific settlement logic; record mock P/L (paper bets only); calculate CLV against captured closing line; record settlement timestamp; record settlement source
- Manual review trigger: `settlement_status = manual_required` when edge case not covered by stored settlement rules (see Section 14)
- Failure behavior: Settlement retried up to 3 times; PM notification on persistent failure; play remains in pending_settlement status
- Downstream: Learning Engine milestone detection

---

### 7.2 Lineup Polling Workflow (Stage 6 Detail)

The Oracle does not rely on a single lineup check at a fixed time before first pitch. The following workflow governs lineup monitoring from window open to deadline.

**Step 1 — Open lineup monitoring window**
When the configured `lineup_monitor_window_open` offset from a game's first pitch time is reached, the Run Orchestrator opens a monitoring sub-process for that game. The opening is recorded with a timestamp and the initial lineup status (both unconfirmed, one confirmed, both confirmed) from the Stage 3 data gather.

**Step 2 — Poll approved lineup sources at bounded interval**
The LineupProvider (MLB Stats API lineup endpoint — to be implemented in Phase 2) is polled at the configured `lineup_poll_interval`. The poll interval must not exceed the provider's documented rate limits. The Orchestrator enforces the rate limit; it does not rely on the provider to reject over-limit requests.

**Step 3 — Record every observation with source timestamp**
Every poll response is stored with: poll timestamp (UTC), source name, lineup status at time of poll, any changes detected since the prior poll. Records are append-only. Prior observations are never overwritten.

**Step 4 — Stop polling when both lineups are confirmed**
When both lineups have reached confirmed status, the monitoring sub-process closes for that game. A confirmation event is appended to the event store. Stage 7 (Final Analysis) is triggered immediately.

**Step 5 — Trigger dependency-aware recalculation on material change**
A material change is defined as: a player appearing in the lineup who was not in the prior submission, a player removed from the lineup, or the top-of-lineup batting order changing by two or more positions. On detection of a material change, recalculation is triggered immediately for all affected markets following the dependency rules in Section 9. The recalculation does not wait for the next scheduled poll.

**Step 6 — Continue polling unresolved games until activation deadline**
If one or both lineups remain unconfirmed, polling continues at the configured interval through the `candidate_activation_deadline`. Candidates remain in monitoring status; they are not expired while polling continues.

**Step 7 — Expire unresolved candidates at activation deadline**
When the `candidate_activation_deadline` is reached and one or both lineups are still unconfirmed, candidates dependent on the unresolved lineup(s) expire. The expiry is recorded as an event. If a Conditional Play had been nominated and its condition was lineup confirmation, the play is recorded with status = Expired, mock P/L = 0; the Play ID is retained.

**Step 8 — Respect provider rate limits and retry policies**
If a poll fails (network error, API error), the Orchestrator waits one configured `lineup_poll_interval` before retrying — it does not retry immediately. After three consecutive poll failures, PM alert is triggered. Polling continues for the game unless the activation deadline has passed.

---

## SECTION 8 — VERSIONED CANDIDATE RE-ENTRY

A pre-lock candidate that receives a no_edge verdict in one evaluation version is not permanently barred from re-entry. The following rules govern re-evaluation.

### 8.1 Re-Entry Fields

Every Candidate record carries:

| Field | Description |
|---|---|
| `evaluation_version` | Integer; increments on each full re-evaluation; starts at 1 |
| `prior_status` | The status recorded in the most recent prior evaluation version |
| `new_evidence_trigger` | What materially changed to justify re-evaluation (odds movement, SP change, lineup confirmation, weather update) |
| `reanalysis_timestamp` | When the re-evaluation was initiated |
| `re_entry_eligibility` | Boolean; true if candidate is pre-lock, pre-activation-deadline, and evidence change is material |
| `terminal_status` | Populated when candidate reaches a state that prohibits re-entry (see below) |

### 8.2 Required Behavior

1. The prior no_edge evaluation version is preserved in full. It is never overwritten.
2. If materially new odds or evidence arrive before `candidate_activation_deadline`, a new Evaluation ID (with version incremented) is created for the same Candidate ID.
3. Every analytical component affected by the new evidence is re-run. The scope of re-runs is determined by the dependency rules in Section 9, not by a fixed policy.
4. ODG and SRL must clear the new evaluation independently. A no_edge that becomes Clear Value in v2 must pass all six ODG questions under the v2 inputs before activation.
5. When the new evaluation qualifies the candidate, it may proceed to activation through Stage 8 if the activation deadline has not passed.
6. Multiple re-entry cycles are permitted within a single day before the activation deadline.

### 8.3 Terminal Statuses (Re-Entry Prohibited)

| Terminal Status | Description |
|---|---|
| `pregame_locked` | Play has been locked at `immutable_lock_deadline`; no further evaluation |
| `settled` | Game result recorded; settlement complete |
| `void` | Game cancelled, postponed, or market unavailable |
| `activation_deadline_expired` | Activation deadline passed without qualification; no further evaluation for this slate |
| `daily_cap_reached` | Three plays already activated on this slate; no additional candidates may activate |

### 8.4 What Immutability Means in This Context

Immutability prohibits altering pregame records after `pregame_locked_at`. It does not prohibit legitimate pre-lock re-evaluation. Creating a new evaluation version before lock is not a violation of immutability — it is the correct behavior for a system that responds to live data.

---

## SECTION 9 — DEPENDENCY-BASED RECALCULATION

Recalculation is governed by the material input that changed and the engines affected by that input. No numerical ECF-change threshold suppresses required recalculation.

### 9.1 Recalculation Chains by Trigger Type

**Starting pitcher change (one or both SPs changed or withdrawn)**
Full chain required for all markets in this game:
`PHIE → ECF → GSE → MVE → CE → ODG → SRL`

Rationale: SP change affects PHIE directly (new pitcher matchup profile), ECF SP Certainty, game script expectation, market value versus prior expectation, correlations, gate verdict, and slate ranking.

**Confirmed lineup or material lineup change**
Chain required for market-relevant engines:
`PHIE → ECF → GSE (where market-relevant) → MVE → CE → ODG → SRL`

Market relevance: PHIE must re-run when lineup changes because batter-pitcher matchups change. GSE re-runs for all markets with lineup-dependent scripts. ECF Lineup Certainty recalculates. MVE recalculates with updated PHIE/GSE inputs.

**Odds change (material movement in an authorized market)**
Chain for the affected market:
`MVE → CE (where CE assessment affected by this market's value change) → ODG → SRL`

Rationale: PHIE and GSE do not change because odds moved. MVE recalculates fair probability vs. new market price. CE may recalculate if the value change affects a correlated pair. ODG and SRL must re-run with new MVE output.

**Weather change (material update — wind shift, precipitation alert)**
Chain for weather-sensitive markets (outdoor stadiums only):
`ECF → GSE → MVE → CE (where applicable) → ODG → SRL`

Rationale: Weather affects ECF Environmental Certainty. GSE script themes shift with significant wind or precipitation changes. MVE must reflect updated game environment. PHIE does not re-run unless weather change also causes a lineup change.

**Bullpen change (material bullpen unavailability — key reliever scratched or heavily used prior day)**
Chain for affected markets:
`ECF → GSE → MVE → CE → ODG → SRL`

Rationale: Bullpen availability affects ECF Bullpen Certainty, GSE script themes (particularly Bullpen-Driven script), and late-inning market value. PHIE does not re-run unless the change also affects the SP.

**Umpire confirmation (plate umpire identity confirmed before game)**
Chain where material to the specific market:
`ECF → GSE and downstream market analysis`

Rationale: Known umpire zone tendencies may shift GSE run environment expectations for totals and NRFI markets. PHIE does not re-run for umpire data. Materiality is engine-assessed; recalculation is not mandatory for markets where umpire data has no defined impact.

### 9.2 Recalculation Record Requirements

Every recalculation creates a new evaluation version. The trigger, the scope of re-run engines, and the prior version's output are preserved. The Orchestrator records a recalculation event with: trigger type, trigger source, engines re-run, timestamp, and result.

---

## SECTION 10 — RUN ORCHESTRATOR SPECIFICATION

### 10.1 Responsibilities

The Run Orchestrator is the central coordination service for Layer B. It owns all state, scheduling, and checkpoint management. No other component may trigger Oracle stages.

**What the Orchestrator does:**
- Fires the daily slate initialization at `preliminary_run_time`
- Triggers each stage when its preconditions are met
- Opens and closes lineup monitoring windows per game
- Triggers recalculation when change events are detected
- Enforces the daily 3-play maximum (reads counter before each activation call)
- Manages the emergency kill switch
- Logs all orchestration events with timestamps

**What the Orchestrator does not do:**
- Execute analytical engines (it calls the engine layer, which executes them)
- Make play decisions (it routes ODG/SRL output to activation logic)
- Write pregame records after lock (blocked by immutability enforcement)
- Trigger real-money activity of any kind

### 10.2 Kill Switch

Environment variable: `ORACLE_AUTONOMOUS_RUN_ENABLED`

When set to `false` or absent:
- All automated stage triggers are halted immediately
- Stages in progress complete their current atomic operation and stop
- The Custom GPT read API continues to serve existing records
- No new paper bets may be created
- Manual PM authorization required to re-enable

The kill switch does not delete records, roll back state, or affect records already written. It is a halt on new automated activity, not a data operation.

### 10.3 State Machine (Slate Level)

```
initializing
     │ schedule retrieved
     ▼
schedule_loaded
     │ per-game analysis begun
     ▼
analysis_in_progress
     │ all games at final_analysis_deadline
     ▼
activation_window_open
     │ at immutable_lock_deadline for last game
     ▼
pregame_locked
     │ all activated plays settled; no postponed games
     ▼
settled

partial_void: reached from pregame_locked when one or more games are
postponed or cancelled after pregame lock while at least one game on
the slate proceeds to settlement. Full-slate postponement before any
game reaches pregame_locked produces activation_deadline_expired for
all candidates, not partial_void.

Error states: analysis_failed | activation_failed | settlement_pending_retry
```

### 10.4 State Machine (Game Analysis Level)

```
scheduled
     │ preliminary data gathered
     ▼
preliminary_analysis
     │ ECF and pipeline complete
     ▼
lineup_monitoring
     │ both lineups confirmed OR deadline reached
     ▼
final_analysis
     │ analysis complete
     ▼
activation_eligible  ──▶  [activation_deadline_expired]
     │ play activated OR no play
     ▼
pregame_locked
     │ game result available
     ▼
settled  (or voided | postponed)
```

---

## SECTION 11 — MULTI-WINDOW SLATE POLICY

### 11.1 The Risk

A daily slate may contain games with first pitch times spread across multiple time windows (e.g., 1:10 PM, 4:10 PM, 7:10 PM ET). The Oracle's three-play daily maximum creates a sequencing risk:

Early-window games that qualify under SRL may be activated before later-window games have been fully analyzed. If early activations consume all three available slots, later-window games cannot be activated regardless of their analytical quality — even if they would have ranked higher on the full slate.

This is not a flaw in the three-play maximum. The three-play maximum is a governance rule and is mandatory. The question is how available slots should be managed across time windows.

### 11.2 Architecture-Compatible Options

The following options are architecture-compatible. No option is selected. PM authorization is required before one is adopted.

**Option A — Immediate Activation by Window**
Activate any qualifying Top Tier candidate in the current window as soon as the window's activation deadline arrives. Earlier windows do not reserve slots for later windows. Earlier-window activations are final. If three plays are activated before later windows reach their activation deadlines, later windows produce zero plays.

- Advantage: Simple; maximizes use of available information at each decision point; consistent with "play when qualified" discipline
- Risk: Early-window plays may exhaust capacity before stronger late-window opportunities emerge

**Option B — Reserved Capacity for Later Windows**
Reserve a defined number of slots (e.g., one slot) for games whose first pitch is more than a defined number of hours away. Reserved slots may only be consumed by games in later windows; they cannot be claimed by early-window games regardless of quality.

- Advantage: Guarantees at least one late-window opportunity is available
- Risk: Artificially constrains early-window activations; a reserved slot may go unused if no late-window game qualifies

**Option C — Full-Slate Provisional Ranking with Window-Specific Deadlines**
SRL runs across all games at the `preliminary_run_time` to produce a provisional full-slate ranking. Activation slots are tentatively allocated by provisional rank. Each game's activation deadline is respected. If a higher-ranked late-window game overtakes a lower-ranked early-window game in the provisional ranking, the earlier activation remains final — the later game inherits the next available slot.

- Advantage: Produces a global ranking signal early; reduces pure first-come-first-served dynamics
- Risk: Provisional rankings may change materially as data arrives (lineups, odds); early provisional ranking may be a poor predictor of final ranking

**Option D — Governance-Defined Hybrid**
PM defines a specific hybrid policy in writing, covering: slot reservation thresholds, provisional ranking weight, window definitions, and override procedures. The hybrid is implemented as configured policy in the Orchestrator, not as hard-coded logic.

- Advantage: Can be precisely tuned to the actual slate distribution
- Risk: Adds governance complexity; requires explicit testing of the policy logic

### 11.3 What Remains Mandatory Under Every Option

- The database-level enforcement (CHECK constraint or equivalent) of three plays per slate is mandatory. No policy option may circumvent this.
- No play may activate after `immutable_lock_deadline` for that game.
- Every activation must clear ODG and SRL independently, regardless of provisional ranking or reservation status.
- The No Forced Plays rule applies within every window. If no game qualifies in a given window, zero plays are a correct outcome.

**PM Decision Point 10 (updated):** PM selects one of Options A–D, or defines a Governance-Defined Hybrid specification, before Phase 4 implementation begins. This is a mandatory pre-Phase-4 authorization item.

---

## SECTION 12 — CONDITIONAL PLAY LIFECYCLE

### 12.1 Outcome Codes

| Outcome Code | Description | Play ID Retained | Mock P/L |
|---|---|---|---|
| `activated` | Condition resolved; play locked at confirmed price | Yes | Calculated at settlement |
| `condition_unmet` | Required condition did not resolve before deadline | Yes | 0 |
| `price_breach` | Odds moved past authorized ceiling before activation | Yes | 0 |
| `lineup_unresolved` | Lineup condition could not be confirmed | Yes | 0 |
| `deadline_expired` | Activation deadline passed without resolution | Yes | 0 |
| `game_cancelled` | Game cancelled before first pitch | Yes | 0; play Voided |
| `market_unavailable` | Required market not available at activation time | Yes | 0 |

### 12.2 Monitoring Rules

- All conditional play monitoring obeys `immutable_lock_deadline`
- Monitoring events are appended to `oracle_play_events`; no prior events are altered
- When a conditional play resolves to activated, it receives `pregame_locked_at` at that moment
- When a conditional play reaches any non-activated outcome code, the event is recorded with a reason

---

## SECTION 13 — IMMUTABLE EVENT MODEL

### 13.1 oracle_play_events Table

**Design:** Append-only. Every state change in a play's lifecycle is a new INSERT row. No UPDATE or DELETE is permitted on this table after the initial write.

**Enforcement (three layers):**
1. Application layer: activation logic checks current state before writing; rejects writes to locked records
2. Database trigger: PostgreSQL trigger on UPDATE and DELETE that raises exception and logs to `oracle_immutability_audit`
3. Audit table: `oracle_immutability_audit` records every rejected write attempt with: timestamp, attempting process, table, record ID, attempted operation, and reason for rejection

### 13.2 Defined Event Types

`slate_initialized` | `schedule_retrieved` | `game_analysis_started` | `ecf_calculated` | `phie_completed` | `gse_completed` | `mve_completed` | `ce_completed` | `odg_completed` | `srl_completed` | `candidate_created` | `candidate_reentered` | `evaluation_version_created` | `recalculation_triggered` | `lineup_observation_recorded` | `lineup_confirmed` | `lineup_change_detected` | `play_id_assigned` | `play_activated` | `play_locked` | `conditional_play_nominated` | `conditional_resolved` | `conditional_expired` | `settlement_completed` | `settlement_manual_required` | `le_milestone_detected` | `le_report_stored` | `immutability_violation_rejected`

### 13.3 Pregame Lock

`pregame_locked_at` is set at `immutable_lock_deadline` for each game. After this timestamp, no engine output, thesis, risk factor, or grade may be modified for any record associated with that game. The application layer enforces this; the database trigger provides a second enforcement layer.

---

## SECTION 14 — SETTLEMENT ARCHITECTURE

### 14.1 Market-Specific Settlement Logic

**Full-Game Moneyline:** Win = team selected wins the game. Loss = team selected loses. Push = tie (extremely rare in MLB). Void = game not completed per sportsbook rules.

**Full-Game Totals:** Win = final combined score clears the total in the predicted direction. Loss = opposite. Push = final score exactly equals total line. Void = game not completed.

**F5 Moneyline:** Win = team selected leads after exactly five complete innings (subject to book-specific rules on rain-shortened games — see override table). Loss = opposite. Push = tied after five innings (book-specific rules apply). Void = fewer than five innings completed.

**F5 Totals:** Win = combined score after five complete innings clears the F5 total line. Push = exact total. Void = fewer than five innings completed.

**NRFI:** Win = no run scored in the first inning (top and bottom complete). Void = first inning not completed. Book-specific rules for partial first innings stored in override table.

**YRFI:** Win = at least one run scored in the first inning. Void = first inning not completed.

### 14.2 Book-Specific Rule Storage

`settlement_rule_overrides` table keyed by `(book_name, market_type, rule_type)`.

Currently authorized books: Bet365, DraftKings.

When settlement logic encounters an edge case (rain-shortened game, book-specific push rules, suspended game continuation) not covered by stored rules: `settlement_status = manual_required`; PM notification triggered; play remains unsettled until manual review is completed.

### 14.3 CLV Calculation

CLV (Closing Line Value) requires the closing line captured at `closing_line_capture_offset`. CLV = (activation odds — closing odds) in American odds, converted to probability terms. CLV is a postgame field; it cannot be written before `pregame_locked_at` is set.

---

## SECTION 15 — MODEL EXECUTION ARCHITECTURE

### 15.1 LLM Provider Adapter

The Oracle defines a pluggable LLM provider adapter. Provider selection is controlled by environment variable: `ORACLE_LLM_PROVIDER`.

Current candidates: `openai` (GPT-4o) or `anthropic` (claude-sonnet-4-6).

**No LLM provider is currently authorized for Oracle analytical calls.** PM Decision Point 1 is required before integration. The adapter architecture is designed now so that the implementation can accommodate either provider without redesign.

### 15.2 Execution Rules

- Temperature: 0 for all analytical calls (deterministic output)
- Output format: Structured JSON via schema enforcement (OpenAI `response_format` or Anthropic tool-use pattern)
- Validation: Pydantic schema validation of every LLM response before acceptance
- Retry on schema failure: retry 2× with clarifying prompt before logging error and halting game analysis
- Retry on API error: retry 3× with 15s/60s/300s backoff
- Token budget: `ORACLE_DAILY_TOKEN_BUDGET` environment variable; alert when budget reached; halt new engine calls when exceeded; in-progress calls complete

### 15.3 Versioning and Audit

- System instructions stored in `oracle_system_instructions` table with version tags
- Changes to system instructions require PM authorization before taking effect
- Every LLM call logged: engine name, evaluation ID, model version, prompt hash, response hash, token count, latency, timestamp
- API keys are never logged
- Model version changes require shadow test period and 2-week parallel run before cutover

---

## SECTION 16 — LEARNING ENGINE EXECUTION

### 16.1 Automated LE Workflow (at Approved Milestones)

The Learning Engine analysis is automated. The LE never autonomously modifies the Oracle methodology. These two statements are not in tension.

At each milestone (7-day, 30-play, 100-play), the automation performs the following eight steps:

**Step 1 — Detect milestone**
The Run Orchestrator, as part of Stage 10 settlement processing, checks whether the just-completed settlement crosses a milestone threshold. Milestone detection is coded logic applied against the `oracle_plays` record count and the date of the earliest record.

**Step 2 — Assemble LE evidence package**
The Orchestrator assembles the full evidence package: all settled play records since the last LE report (or since inception for first milestone), all evaluation version records, all ECF scores, all engine outputs, all CLV calculations. Package is stored as a structured JSON document in `oracle_le_evidence_packages`.

**Step 3 — Execute approved LE analysis**
The LE engine is invoked with the evidence package. The LE engine runs its five defined analysis levels: PHIE category accuracy, GSE script accuracy, MVE CLV calibration, CE correlation accuracy, systematic bias detection. LLM calls follow the same execution rules as analytical engines.

**Step 4 — Produce structured observations**
The LE records factual observations for each analysis level: what happened versus what was predicted, at what frequency, across what sample. Observations are stored in `oracle_le_observations`.

**Step 5 — Produce findings**
Where observations meet a materiality threshold, the LE produces named findings: the pattern observed, the sample supporting it, the engine or category affected. Findings are stored in `oracle_le_findings`.

**Step 6 — Produce calibration recommendations**
For each material finding, the LE produces a written calibration recommendation: what the finding suggests should change and why. Recommendations are explicitly advisory. They are NOT changes. They are NOT implemented. They are stored in `oracle_le_recommendations`.

**Step 7 — Store complete LE report**
All observations, findings, and recommendations are assembled into a complete LE milestone report, assigned a report ID, and stored in `oracle_le_reports`. The report is immutable once written.

**Step 8 — Notify Project Owner and Project Manager**
Alert is sent to the configured notification channel: milestone reached, report ID, number of findings, number of recommendations. PM and Project Owner must retrieve and review the report.

### 16.2 What Automation Must Never Do

The LE automation must never, under any circumstances:
- Alter category weights (PHIE, ECF, SRL, or any other)
- Alter score thresholds (ECF ceiling, ODG question thresholds, SRL tier criteria)
- Alter playbook pass conditions
- Change any engine logic or decision rule
- Modify any code
- Deploy any change
- Modify any governance document

All methodology changes require the Constitutional Amendment Procedure (Article VI of the Oracle Constitution). The LE report provides the evidence package that may initiate Stage 1 of that procedure. It does not itself constitute approval or authorization for any change.

---

## SECTION 17 — CUSTOM GPT INTERFACE

### 17.1 Design

The Custom GPT is a read-only interface for the Project Owner. It serves current and historical Oracle data via a GPT Action (HTTP requests to the Oracle API). It has no write access and no ability to trigger any Oracle stage.

### 17.2 Authorized Endpoints (Read-Only)

1. Current paper bets for today's slate
2. Conditional plays and their current status
3. Game analysis records (by game or date)
4. PHIE output for a specific game
5. ECF score and category breakdown for a specific game
6. GSE script theme and confidence for a specific game
7. MVE value verdict and probability comparison for a specific game
8. CE correlation assessments for today's slate
9. ODG verdict and question responses for a specific game
10. SRL ranking for today's slate
11. Historical play records (by date range, market, outcome)
12. LE milestone reports
13. Audit report access
14. Provider health status (which adapters are currently operational)
15. Oracle run status for the current slate

### 17.3 Explicit Prohibitions

The Custom GPT interface may never:
- Write any record
- Trigger any stage
- Activate any play
- Modify any conditional play status
- Run any analytical engine
- Modify configuration values
- Modify governance documents

### 17.4 Authentication

Bearer API key. Rate limit: 60 requests/minute. Keys provisioned separately from Oracle analytical LLM keys. API keys are never returned in API responses.

---

## SECTION 18 — FAILURE AND RECOVERY

### 18.1 Failure Mode Reference

| Failure Mode | Detection | Recovery |
|---|---|---|
| Schedule unavailable at Stage 2 | ScheduleProvider returns error or empty | Retry 3×; PM alert; no slate proceeds |
| SP confirmation missing at deadline | SPProvider shows unconfirmed at final_analysis_deadline | ECF SP ceiling applied; candidate may proceed at degraded confidence |
| Lineup unconfirmed at activation deadline | LineupProvider shows unconfirmed at candidate_activation_deadline | Conditional expired; Play ID retained if assigned; mock P/L = 0 |
| Odds unavailable for an authorized market | OddsProvider returns no data for market | MVE cannot run for that market; candidate does not activate; market flagged data_unavailable |
| LLM API error (analytical call) | HTTP error or timeout | Retry 3× with backoff; if all fail, game marked analysis_incomplete; PM alert |
| LLM schema validation failure | Pydantic validation error | Retry 2× with clarifying prompt; if all fail, game marked analysis_incomplete |
| Token budget exceeded | Running token count exceeds ORACLE_DAILY_TOKEN_BUDGET | Alert PM; halt new LLM engine calls; in-progress calls complete; coded engines continue |
| Immutability violation attempt | Database trigger fires | Write rejected; immutability_audit record created; PM alert |
| 4th activation attempt | Database CHECK constraint or equivalent | INSERT blocked at DB level; application-layer logging; PM alert |
| Settlement data unavailable | ResultsProvider returns no final score | Retry 3×; settlement_status = pending_retry; PM notification |
| Book-specific settlement edge case | Settlement rule not in override table | settlement_status = manual_required; PM notification |
| LE milestone detection error | Exception in milestone check | Logged as warning; next settlement cycle re-checks; PM alert if persistent |
| Run Orchestrator crash | Health check or process monitor | Alert PM; no automatic restart without PM authorization; kill switch is safe state |
| Kill switch activated | ORACLE_AUTONOMOUS_RUN_ENABLED = false | All stage triggers halt; read API continues; manual PM re-enable required |
| Weather provider unavailable | Open-Meteo request fails or times out | ECF Environmental Certainty weather sub-component defaults to 0 points for affected game; flagged in ECF output; analysis proceeds at reduced confidence |

---

## SECTION 19 — MONITORING AND ALERTING

### 19.1 Alert Severity

| Severity | Examples | Action |
|---|---|---|
| Critical | Run Orchestrator crash, immutability violation, 4th activation attempt, all LLM retries exhausted | Immediate PM notification; halt automated activity |
| High | Schedule unavailable, settlement persistent failure, LLM token budget exceeded | PM notification within run cycle; automated retry in progress |
| Medium | SP unconfirmed at final_analysis_deadline, lineup unconfirmed at activation deadline, LE milestone report ready | PM notification at end of run cycle |
| Low | Odds data stale (below threshold age), single poll failure (retrying), weather source temporarily unavailable | Log only; PM review at next daily report |

### 19.2 Daily Completion Report

At the end of each settlement cycle, the Orchestrator generates a daily completion report containing: slate run ID, games analyzed, candidates created, plays activated (by market), conditional plays pending, settlements completed, settlements manual-required, provider health summary, and any alerts raised during the run. Report is stored and available via Custom GPT endpoint 15.

---

## SECTION 20 — TESTING STRATEGY

### 20.1 Phase 1 Exit Criteria
- Run Orchestrator creates a slate run record with correct ID format
- Game analysis records are created from schedule data using MLB Stats API `gamePk` values as canonical `external_game_id`
- Append-only event model: UPDATE and DELETE on `oracle_play_events` raise exceptions and write to audit table
- Kill switch halts all stage triggers; read API continues
- Database-level enforcement (CHECK constraint or equivalent) blocks `daily_plays_activated` exceeding 3

### 20.2 Phase 2 Exit Criteria
- All ten provider interfaces return data in correct contract format
- MLB Stats API schedule retrieval returns games with correct identifier format
- OddsAPI.io moneyline retrieval returns Bet365 and DraftKings odds in correct format
- Open-Meteo weather retrieval returns temperature, wind speed, wind direction, and precipitation probability for each game's home stadium
- ESPN injury retrieval returns player injury records for both teams in each game
- MLB Stats API lineup endpoint implemented and returning confirmed lineup data (Phase 2 implementation dependency — see Interface 4)
- Missing provider (UmpireProvider) triggers correct degraded-mode behavior and ECF flag
- Lineup polling loop operates at configured interval; observations are recorded; material changes detected
- Cross-provider game ID reconciliation (OddsAPI.io event_id → MLB Stats API external_game_id) correctly associates odds records to game records
- Rate limit enforcement prevents over-limit requests

### 20.3 Phase 3 Exit Criteria
- Full PHIE → ECF → GSE → MVE → CE → ODG → SRL pipeline executes end-to-end for a test game
- LLM calls return valid Pydantic-validated JSON at temperature 0
- Retry logic triggers correctly on simulated schema failure and API error
- Dependency-based recalculation produces correct engine chain for each trigger type
- Versioned re-entry creates new evaluation versions without overwriting prior versions

### 20.4 Phase 4 Exit Criteria (Shadow Mode — minimum duration per PM Decision Point 9)
- Full autonomous daily run completes without PM intervention for the PM-defined shadow duration
- Play IDs assigned only at governed nomination, not at preliminary screening
- Three-play daily maximum enforced in all tested scenarios including simultaneous activation attempts
- No play activates at or after first pitch in any test scenario
- Conditional play lifecycle produces correct outcome codes and Play ID retention
- Closing line captured within configured offset
- CLV calculation correct for verified test cases
- Paper bet records match expected contract format
- LE milestone detection operates correctly at simulated thresholds

### 20.5 Phase 5 Exit Criteria
- Settlement logic correct for full-game moneyline across verified result scenarios (win, loss, push, void)
- Settlement manual_required triggered correctly on edge cases
- CLV recorded in postgame fields; not accessible before `pregame_locked_at`
- Daily completion report generated and available via Custom GPT endpoint

### 20.6 Phase 6 Exit Criteria
- Each additional market (totals, F5, NRFI/YRFI) passes Data Availability verification before being added to autonomous pipeline
- Settlement logic correct for each additional market
- ODG playbook pass condition sweep updated for each additional market's playbook

### 20.7 Phase 7 Exit Criteria
- All fifteen Custom GPT endpoints return correct data in documented format
- Authentication enforced; unauthenticated requests rejected
- Rate limit enforced; over-limit requests return 429
- No endpoint permits write operations; all write attempts return 405 or 403
- No endpoint triggers any Oracle stage

### 20.8 Phase 8 Exit Criteria
- LE detects 30-play milestone correctly
- LE assembles evidence package with correct data scope
- LE report stored in `oracle_le_reports`; PM notification sent
- Calibration recommendations stored as advisory records; no automated change applied

---

## SECTION 21 — IMPLEMENTATION ROADMAP

### Phase 1 — Automation Foundation and Run-State Model
**Scope:** Oracle database tables, Run Orchestrator skeleton, immutability enforcement, kill switch, identifier lifecycle management
**Prerequisites:** PM Decision Point 10 (authorization to begin Phase 1); PM confirmation of schema design per CLAUDE.md Rule 6
**Excludes:** All provider integrations; all analytical engines; all LLM calls
**Key deliverables:** `oracle_slate_runs`, `oracle_game_analyses`, `oracle_play_events`, `oracle_plays`, `oracle_immutability_audit` tables; Orchestrator service; kill switch; event model enforcement; CHECK constraint on daily plays maximum
**Exit criteria:** Phase 1 exit criteria (Section 20.1)
**Risk:** Schema design must be confirmed with PM before any CREATE TABLE statement is executed

### Phase 2 — Data Contracts and Provider Adapters
**Scope:** All ten provider adapter interfaces; polling loop; configuration table; timing parameters; MLB Stats API lineup endpoint implementation; cross-provider game ID reconciliation
**Prerequisites:** Phase 1 complete; PM Decision Points 2 (schedule/SP provider audit), 3 (odds coverage verification), 5 (Open-Meteo adequacy verification), 6 (umpire default acceptance), 7 (price ceiling definition)
**Excludes:** Analytical engine calls; LLM integration
**Key deliverables:** All ten provider adapters; Open-Meteo WeatherProvider integration (wrapping existing `backend/fetchers/weather.py`); ESPN PlayerStatusProvider integration (wrapping existing `backend/fetchers/injuries.py`); MLB Stats API lineup endpoint (new function in `mlb_stats_api.py`); lineup polling workflow; configuration table; cross-provider game ID reconciliation contract
**Exit criteria:** Phase 2 exit criteria (Section 20.2)
**Risk:** MLB Stats API lineup endpoint must be evaluated and implemented before Phase 4 can operate; OddsAPI.io coverage for totals, F5, NRFI/YRFI must be verified before those markets' adapters are built

### Phase 3 — Oracle Model Execution Interface
**Scope:** LLM provider adapter; all five analytical engines; ECF; ODG; SRL; recalculation logic; versioned candidate re-entry
**Prerequisites:** Phase 2 complete; PM Decision Point 1 (LLM provider selection); PM Decision Point 4 (PyBaseball authorization, or explicit acceptance of degraded PHIE)
**Excludes:** Full automated daily run; settlement
**Key deliverables:** LLM adapter; PHIE, GSE, MVE, CE, LE engine integrations; ECF, ODG, SRL coded logic; dependency-based recalculation; versioned evaluation records
**Exit criteria:** Phase 3 exit criteria (Section 20.3)

### Phase 4 — Automated Full-Game Moneyline Paper-Bet Workflow
**Scope:** Full daily autonomous run for full-game moneyline only; play activation; conditional play management; closing line capture; shadow mode testing
**Prerequisites:** Phase 3 complete; PM Decision Point 8 (alerting channel); PM Decision Point 9 (shadow mode duration); PM Decision Point 10 (multi-window slot policy)
**Excludes:** All other markets; CLV settlement; LE milestones
**Key deliverables:** Complete daily lifecycle for full-game moneyline; conditional play lifecycle; closing line capture; daily completion report; shadow mode run log
**Exit criteria:** Phase 4 exit criteria (Section 20.4); minimum duration per PM Decision Point 9

### Phase 5 — Settlement, CLV, and Audit Records
**Scope:** Full settlement for full-game moneyline; CLV calculation; book-specific rule storage; settlement manual_required workflow; LE report storage
**Prerequisites:** Phase 4 complete with satisfactory shadow mode results
**Key deliverables:** Settlement logic; CLV records; `oracle_le_reports` table; PM notification on manual_required
**Exit criteria:** Phase 5 exit criteria (Section 20.5)

### Phase 6 — Additional Markets
**Scope:** Add additional authorized markets (totals, F5 moneyline, F5 totals, NRFI/YRFI) as their data availability is verified
**Prerequisites:** Phase 5 complete; Data Availability Status = Verified for each market; Autonomous Paper-Bet Authorization Status approved for each market
**Each market added separately:** Each market requires its own data verification, pipeline test, and settlement test before being added to the autonomous pipeline
**Key deliverables:** Per-market pipeline and settlement additions
**Exit criteria:** Per-market Phase 6 exit criteria (Section 20.6)

### Phase 7 — Custom GPT Action Integration
**Scope:** All fifteen read-only endpoints; authentication; rate limiting; GPT Action configuration
**Prerequisites:** Phase 5 complete (data is in a state worth reading)
**Key deliverables:** Fifteen API endpoints; bearer auth; rate limiter; GPT Action JSON definition
**Exit criteria:** Phase 7 exit criteria (Section 20.7)

### Phase 8 — Learning Engine Milestone Automation
**Scope:** Automated LE workflow (all eight steps); milestone detection; report storage; PM notification
**Prerequisites:** Phase 5 complete; minimum 30 settled plays in the database
**Key deliverables:** LE automation; `oracle_le_evidence_packages`, `oracle_le_observations`, `oracle_le_findings`, `oracle_le_recommendations`, `oracle_le_reports` tables; milestone notification
**Exit criteria:** Phase 8 exit criteria (Section 20.8)

---

## SECTION 22 — PROJECT MANAGER DECISION POINTS

All decision points require explicit PM authorization before the corresponding phase or activity begins. Decision points are not formalities.

**Decision Point 1 — LLM Provider Selection**
Select OpenAI GPT-4o or Anthropic claude-sonnet-4-6 as Oracle analytical LLM provider. Required before Phase 3. Both are candidates; neither is authorized.

**Decision Point 2 — MLB Stats API Endpoint Audit**
Confirm which MLB Stats API endpoints are available and sufficient for: schedule, game status, confirmed SPs, submitted lineups (new endpoint required — see Interface 4), player status, results. Required before Phase 2.

**Decision Point 3 — OddsAPI.io Market Coverage Verification**
Confirm actual OddsAPI.io free-tier coverage for: full-game totals, F5 markets, NRFI/YRFI. Full-game moneyline is already verified. The diagnostic script `backend/scripts/diagnostics/check_oddsapi_totals.py` must be run on a day with confirmed odds data before this decision point can be closed. Required before any additional market is added to Phase 2 adapter scope.

**Decision Point 4 — PyBaseball Integration Authorization**
Authorize or decline PyBaseball integration for Statcast data. If declined, explicitly accept that PHIE Categories 2, 3, and 4 will operate at projected tier with reduced ECF Statistical Data Quality score. Required before Phase 3.

**Decision Point 5 — Open-Meteo Integration Adequacy Verification**
Open-Meteo is currently implemented in `backend/fetchers/weather.py`. PM must verify: (a) whether the data set (temperature, wind speed, wind direction, precipitation probability) is sufficient for ECF Category 4 Environmental Certainty scoring as defined in the v1.1 engine specification; (b) whether indoor/retractable-roof stadium handling is required — the current implementation provides weather data for all stadiums regardless of roof type; (c) whether current-conditions data at ingestion run time is adequate for pre-game analysis, or whether a game-time forecast endpoint is required. This is a verification item, not a provider selection decision. Required before Phase 2.

**Decision Point 6 — Umpire Data Acceptance**
Explicitly accept the 0-point default for ECF Category 4 umpire sub-component as a known limitation to be revisited at the 100-play LE milestone. Required before Phase 2.

**Decision Point 7 — Price Ceiling Definition**
Define the maximum acceptable activation odds (in American odds format) for each authorized market. Candidates exceeding this ceiling produce a price_breach outcome code and are not activated. Required before Phase 4.

**Decision Point 8 — Alerting Channel Selection**
Select the notification channel for Oracle alerts (email, Slack webhook, other). Required before Phase 4. Alerting must be operational before shadow mode begins.

**Decision Point 9 — Phase 4 Shadow Mode Duration**
Define the minimum shadow mode duration before Phase 4 is considered validated. Recommended minimum: 7 consecutive operational days. PM may extend this. Required before Phase 4 begins.

**Decision Point 10 — Multi-Window Slot Management Policy**
Select Option A, B, C, or D from Section 11 of this document, or define a Governance-Defined Hybrid specification. Required before Phase 4. This is a governance decision that affects which plays are activated on multi-window slates and must be authorized explicitly.

---

## SECTION 23 — IDENTIFIED BLOCKERS

| Blocker | Impact if Unresolved | Resolution Path |
|---|---|---|
| LLM provider not authorized | Phase 3 cannot begin | PM Decision Point 1 |
| MLB Stats API endpoint audit incomplete | Provider adapter may be built for unsupported endpoints; lineup endpoint existence unconfirmed | PM Decision Point 2 |
| OddsAPI.io market coverage unverified for totals/F5/NRFI | Those markets cannot be added to pipeline | PM Decision Point 3 |
| PyBaseball not authorized | PHIE Categories 2–4 degraded; ECF reduced | PM Decision Point 4 |
| Open-Meteo adequacy for ECF Category 4 not verified | Weather sub-component scoring rules may not match implementation capabilities | PM Decision Point 5 |
| Umpire data source nonexistent | ECF Category 4 umpire component = 0 permanently until source found | PM Decision Point 6; accept known limitation |
| Price ceiling not defined | Activation cannot complete without ceiling check | PM Decision Point 7 |
| Alerting channel not selected | Shadow mode cannot begin safely | PM Decision Point 8 |
| Schema change approval required | No tables can be created until PM confirms schema | Per CLAUDE.md Rule 6 |
| Multi-window slot policy not selected | Orchestrator activation logic cannot be finalized | PM Decision Point 10 |

---

## SECTION 24 — PRE-PHASE-1 PROJECT OWNER VERIFICATION ITEMS

The following items cannot be confirmed from static repository evidence. Project Owner must verify before Phase 1 implementation begins. These items do not block architecture approval but do block the first implementation phase.

| Item | What to Verify |
|---|---|
| PO-V1: PostgreSQL operational status | Confirm that the local PostgreSQL instance is running, accessible, and that a suitable namespace/schema exists or will be created for Oracle tables alongside the existing application tables |
| PO-V2: Open-Meteo game-time accuracy | Confirm whether ingestion run timing provides weather data close enough to game time to be analytically useful; identify any gaps between ingestion time and first pitch time |
| PO-V3: OddsAPI.io totals diagnostic result | Run `backend/scripts/diagnostics/check_oddsapi_totals.py` on a day where ingestion logs show "Found N odds records" with N > 0; report result to PM |
| PO-V4: MLB Stats API lineup endpoint | Evaluate whether `statsapi.mlb.com` provides confirmed batting lineups once submitted; identify the correct endpoint and response format |
| PO-V5: ESPN injury API stability | Confirm whether the ESPN unofficial injury endpoint has been operationally stable in production use and whether it is acceptable as a primary player status source |
| PO-V6: Existing database table definitions | Confirm where the schema definitions for existing tables (`games`, `teams`, `starting_pitchers`, `team_records`, `odds_history`, `team_injuries`, `team_bullpen_context`, `game_weather`) are stored, and that those tables exist in the operational database instance |

---

## CONCLUSION

**A. VERIFIED — Ready for Project Manager Architecture Approval**

All five blocking factual errors identified in the verification audit have been corrected:

1. WeatherProvider corrected: Open-Meteo (`backend/fetchers/weather.py`) is existing and verified. Section 2, Section 3.2 Interface 8, Section 22 blockers, and PM Decision Point 5 have all been updated to reflect this accurately.

2. PlayerStatusProvider source corrected: Current implementation is the ESPN unofficial injury API (`backend/fetchers/injuries.py`), not MLB Stats API.

3. ESPN unofficial injury API added to Section 2 (Technology Status Registry) with accurate status label.

4. LineupProvider capability corrected: No lineup endpoint currently exists in the codebase. The current fetcher provides probable pitchers only. Phase 2 must implement this endpoint.

5. StartingPitcherProvider confirmation flag removed: The current standard shape contains no confirmation flag field. The text now accurately describes what the fetcher returns.

All five minor corrections have been applied:
- B1: Cross-provider game ID reconciliation note added to Interface 7
- B2: Bullpen innings added to MLB Stats API capabilities in Section 2
- B3: Stage 5 description references ECF score from Stage 4 as an explicit input
- B4: `partial_void` trigger condition defined in Section 10.3
- B5: "Unique constraint" replaced with "CHECK constraint or equivalent mechanism" in Section 7.1 Stage 8, Section 11.3, and Section 18.1

**What has not changed:**
- All analytical engine specifications (PHIE, GSE, MVE, CE, LE)
- ECF, ODG, SRL specifications
- Daily lifecycle stages and workflows
- Lineup polling workflow
- Versioned candidate re-entry
- Identifier lifecycle
- Dependency-based recalculation rules
- Run Orchestrator specification
- Multi-window slate policy
- Conditional play lifecycle
- Immutable event model
- Settlement architecture
- Model execution architecture
- Learning Engine execution boundaries
- Custom GPT interface
- Failure and recovery model
- Testing strategy
- Implementation roadmap
- Governance compliance
- Operational freeze status

**Remaining pre-implementation items:**
- Nine PM Decision Points require explicit authorization before their corresponding phases begin
- Six Project Owner verification items (Section 24) must be resolved before Phase 1 begins; they do not block architecture approval

**Architecture is submitted for Project Manager approval. It is not approved. It is not frozen. These statuses may only be granted by the Project Manager and Project Owner.**

---

*Oracle Intelligence Architecture v1.2 Final Candidate*
*Edge Oracle / MLB Betting Edge*
*Prepared: 2026-07-19*
