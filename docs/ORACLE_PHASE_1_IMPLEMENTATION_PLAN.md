# ORACLE PHASE 1 IMPLEMENTATION PLAN
**Edge Oracle / MLB Betting Edge**
**Plan Status: Final — Awaiting PM Authorization to Begin Implementation**
**Architecture Reference:** ORACLE_INTELLIGENCE_ARCHITECTURE_v1_2.md (Final Candidate)
**Date Prepared:** 2026-07-20

---

## DOCUMENT PURPOSE

This document converts the Oracle Intelligence Architecture v1.2 Phase 1 scope into a concrete implementation roadmap. It is a planning document only.

**This document does not constitute:**
- Authorization to write code
- Authorization to create or modify database tables
- Authorization to run schedulers or background processes
- Authorization to modify the repository

No implementation work may begin until the PM explicitly authorizes Phase 1 per the prerequisites in Section 8.1.

---

## ARCHITECTURE CLARIFICATIONS REQUIRED

*This section records clarifications that were raised during planning and the PM decisions that resolved them. No open items remain.*

### ACR-1: Phase 1 Exit Criterion vs. Phase 1 Scope Boundary — RESOLVED

**Architecture reference:** Section 21 (Phase 1 scope), Section 20.1 (Phase 1 exit criteria)

**Clarification raised:** Section 21 excludes all provider integrations. Section 20.1 Exit Criterion 2 requires game analysis records to be created from schedule data using MLB Stats API `gamePk` values. The planning document identified an ambiguity in whether Phase 1 satisfies EC-2 via a live MLB Stats API call or via injected test fixtures.

**PM decision (2026-07-20):** Phase 1 SHALL use fixture-based game records for testing and validation. Phase 1 will not perform live provider integrations. The MLB Stats API integration will be implemented in a subsequent authorized phase.

**Resolution applied:** All Phase 1 work packages, acceptance criteria, tests, and phase gates are written against the fixture-based path. No live MLB Stats API call is made at any point in Phase 1. The `gamePk` field values in test fixtures are valid numeric strings in the MLB Stats API format, allowing Phase 2 integration to use them as real external game identifiers without schema changes.

---

## SECTION 1 — EXECUTIVE SUMMARY

### 1.1 Phase 1 Objective

Phase 1 builds the structural foundation of the Oracle automation layer. No analytical work happens in Phase 1. No providers are integrated. No engines run. Phase 1 exists solely to establish the data model, state machines, identifier lifecycle, immutability guarantees, and kill switch that every subsequent phase depends on.

At the end of Phase 1, the Oracle can:
- Create and track a daily slate run with a correctly formatted Slate Run ID
- Create and track per-game analysis records with correctly formatted Game Analysis Run IDs
- Enforce append-only behavior on the event store at the database level
- Halt all automated activity via a single environment variable
- Block the daily plays cap from being exceeded at the database level

At the end of Phase 1, the Oracle cannot yet:
- Fetch real data from any provider
- Run any analytical engine
- Activate or nominate any play
- Produce any analytical output

### 1.2 Success Criteria

Phase 1 is complete when all five exit criteria in Section 20.1 of the architecture pass:

1. Run Orchestrator creates a slate run record with correct Slate Run ID format (`ORACLE-YYYYMMDD-NNN`)
2. Game analysis records are created from fixture-based schedule data using MLB Stats API `gamePk`-formatted values as canonical `external_game_id`; no live provider call is made in Phase 1
3. UPDATE and DELETE on `oracle_play_events` raise exceptions and write to `oracle_immutability_audit`
4. Kill switch (`ORACLE_AUTONOMOUS_RUN_ENABLED = false` or absent) halts all stage triggers; read API continues
5. Database-level enforcement (CHECK constraint or equivalent) blocks `daily_plays_activated` exceeding 3

### 1.3 Phase 1 Deliverables

| Deliverable | Type | Architecture Section |
|---|---|---|
| `oracle_slate_runs` table | Database | Section 21 Phase 1 |
| `oracle_game_analyses` table | Database | Section 21 Phase 1 |
| `oracle_play_events` table (append-only) | Database | Sections 13, 21 |
| `oracle_plays` table | Database | Section 21 Phase 1 |
| `oracle_immutability_audit` table | Database | Sections 13.4, 21 |
| PostgreSQL trigger: block UPDATE/DELETE on `oracle_play_events` | Database | Section 13.3 |
| CHECK constraint: `daily_plays_activated <= 3` | Database | Section 7.1 Stage 8 |
| Slate-level state machine | Backend | Section 10.1 |
| Game-level state machine | Backend | Section 10.2 |
| Identifier Lifecycle Manager | Backend | Section 6 |
| Event Store Service (27 event types) | Backend | Section 13 |
| Run Orchestrator skeleton (no provider calls) | Backend | Section 12 |
| Kill switch enforcement | Backend | Section 12.2 |
| Phase 1 test suite | Tests | Section 20.1 |
| Migration file | Database | CLAUDE.md Rule 6 |

### 1.4 Dependencies and Prerequisites

**Before any implementation begins:**
- PM Decision Point 10 authorization (required per Section 21 Phase 1 prerequisites)
- PM confirmation of schema design per CLAUDE.md Rule 6 (required before any CREATE TABLE)

**External runtime dependencies (Phase 1):**
- PostgreSQL operational instance (PO-V1 verification)
- `ORACLE_AUTONOMOUS_RUN_ENABLED` environment variable support

**Provider integration:** Phase 1 makes no live calls to any external provider. All schedule and game data used in Phase 1 is supplied via test fixtures. MLB Stats API integration is deferred to Phase 2.

### 1.5 Phase 1 Risks Summary

| Risk | Severity | Mitigation |
|---|---|---|
| Schema design requires revision after PM review | High | Schema submitted for PM review before any CREATE TABLE |
| PostgreSQL instance not operational (PO-V1 unverified) | High | Verify PO-V1 before implementation begins |
| Immutability trigger incompatible with PostgreSQL version | Low | Verify PostgreSQL version before trigger implementation |

---

## SECTION 2 — WORK PACKAGE BREAKDOWN

Phase 1 is organized into six work packages. The order of execution is constrained by dependencies; the critical path is: **WP-1 → {WP-2 ∥ WP-3} → {WP-4 ∥ WP-5} → WP-6**.

---

### WP-1: Oracle Database Schema

**Purpose:** Create the five Phase 1 Oracle tables and all database-level constraints. Every other work package depends on this schema existing.

**Repo area:** `database/` (migration files); PM schema confirmation required before any SQL is written

**Dependencies:** None — first work package; but requires PM schema confirmation (CLAUDE.md Rule 6) before any CREATE TABLE is executed

**Execution order:** First; blocks all other work packages

**Tables in scope:**

| Table | Role |
|---|---|
| `oracle_slate_runs` | One record per daily run; carries Slate Run ID and slate-level state machine |
| `oracle_game_analyses` | One record per game per daily run; carries Game Analysis Run ID, external_game_id, and game-level state machine |
| `oracle_play_events` | Append-only event log; one row per event across all 27 event types |
| `oracle_plays` | Governed paper bet records; one row per Play ID assigned |
| `oracle_immutability_audit` | Audit log; records every rejected UPDATE/DELETE on `oracle_play_events` |

**Key schema requirements:**
- `oracle_slate_runs.slate_run_id`: VARCHAR, format `ORACLE-YYYYMMDD-NNN`, PRIMARY KEY
- `oracle_slate_runs.daily_plays_activated`: INTEGER, NOT NULL, DEFAULT 0; subject to CHECK constraint `daily_plays_activated <= 3`
- `oracle_slate_runs.run_status`: VARCHAR; valid values: `initializing | schedule_loaded | analysis_in_progress | activation_window_open | pregame_locked | settled | partial_void | analysis_failed | activation_failed | settlement_pending_retry`
- `oracle_game_analyses.game_run_id`: VARCHAR, format `{slate_run_id}-{game_identifier}`, PRIMARY KEY; FOREIGN KEY → `oracle_slate_runs.slate_run_id`
- `oracle_game_analyses.external_game_id`: VARCHAR NOT NULL; stores MLB Stats API `gamePk` value as canonical game identifier
- `oracle_game_analyses.game_status`: VARCHAR; valid values: `scheduled | preliminary_analysis | lineup_monitoring | final_analysis | activation_eligible | pregame_locked | settled | voided | postponed`
- `oracle_play_events.event_id`: BIGSERIAL PRIMARY KEY
- `oracle_play_events.event_type`: VARCHAR NOT NULL; must be one of the 27 defined event types (Section 13.2 of architecture)
- `oracle_play_events.event_timestamp`: TIMESTAMPTZ NOT NULL (all timestamps stored in UTC)
- `oracle_plays.play_id`: VARCHAR, format `EO-YYYY-NNN`, PRIMARY KEY
- `oracle_plays.pregame_locked_at`: TIMESTAMPTZ; NULL until lock; non-null means pregame fields are immutable at application layer
- `oracle_immutability_audit.violation_type`: VARCHAR NOT NULL; records attempted operation type (UPDATE or DELETE)
- `oracle_immutability_audit.rejected_at`: TIMESTAMPTZ NOT NULL

**Acceptance criteria:**
- All five tables created and verified in target database
- `daily_plays_activated <= 3` CHECK constraint verified (insert of 4 raises constraint violation)
- All foreign key relationships enforced
- All NOT NULL constraints enforced
- Migration file committed and reversible (DROP TABLE statements in rollback)

**Test requirement:** Schema-level validation tests; no application code required for WP-1 acceptance

---

### WP-2: Immutability Enforcement

**Purpose:** Implement the PostgreSQL trigger that makes `oracle_play_events` append-only. This is a database-layer guarantee — application code cannot bypass it.

**Repo area:** `database/` (trigger migration file)

**Dependencies:** WP-1 (table must exist before trigger can be attached)

**Execution order:** After WP-1; parallel with WP-3

**Trigger specification:**
- Trigger name: `enforce_play_events_append_only` (or equivalent)
- Attached to: `oracle_play_events`
- Fires on: BEFORE UPDATE, BEFORE DELETE
- Action: RAISE EXCEPTION with message identifying the violation; INSERT one record into `oracle_immutability_audit` with: `event_id` of the rejected operation, `violation_type` (UPDATE or DELETE), `rejected_at` (NOW()), `attempted_by` (current_user or session identifier)
- Does not fire on: INSERT (append is permitted)

**Acceptance criteria:**
- INSERT on `oracle_play_events` succeeds
- UPDATE on `oracle_play_events` raises EXCEPTION
- DELETE on `oracle_play_events` raises EXCEPTION
- Every rejected UPDATE writes one record to `oracle_immutability_audit`
- Every rejected DELETE writes one record to `oracle_immutability_audit`
- Trigger survives a PostgreSQL restart (persisted in migration, not a session-level construct)

**Test requirement:** Direct SQL tests against live database; cannot be satisfied by mocks

---

### WP-3: Identifier Lifecycle Manager

**Purpose:** Implement the Python module responsible for generating and validating all Oracle identifiers. This is the sole source of identifier generation in the codebase — no other module generates Oracle IDs.

**Repo area:** `backend/oracle/` (new module; exact path subject to PM authorization of file structure)

**Dependencies:** WP-1 (identifiers reference fields in the schema; generation logic must match schema constraints)

**Execution order:** After WP-1; parallel with WP-2

**Identifiers in scope:**

| Identifier | Format | Assigned When |
|---|---|---|
| Slate Run ID | `ORACLE-YYYYMMDD-NNN` | Stage 1 — Slate Initialization |
| Game Analysis Run ID | `{slate_run_id}-{game_identifier}` | Stage 2 — Schedule Retrieval |
| Evaluation ID | `EVAL-{game_run_id}-{market}-{version}` | Every time market analysis is performed |
| Candidate ID | `CAND-{game_run_id}-{market}` | When market clears preliminary screening |
| Play ID | `EO-YYYY-NNN` | Only at formal Oracle nomination (governed act) |

**Sequence management requirements:**
- Slate Run ID suffix (`NNN`): zero-padded to 3 digits; starts at 001 each day; increments if multiple runs occur on the same date; must query `oracle_slate_runs` to determine next sequence value — not generated from application-side counters
- Play ID suffix (`NNN`): zero-padded to 3 digits; sequential within calendar year; must query `oracle_plays` to determine next sequence value — not generated from application-side counters
- Play ID assigned ONLY by a governed nomination path; no other code path may generate `EO-YYYY-NNN` identifiers

**Validation functions:**
- `is_valid_slate_run_id(value: str) -> bool`
- `is_valid_game_run_id(value: str) -> bool`
- `is_valid_evaluation_id(value: str) -> bool`
- `is_valid_candidate_id(value: str) -> bool`
- `is_valid_play_id(value: str) -> bool`

**Acceptance criteria:**
- Generated Slate Run ID matches format `ORACLE-YYYYMMDD-NNN` for the current date
- Sequence suffix increments correctly across multiple same-day calls
- Validation functions reject malformed identifiers
- Play ID generation raises an error if called from any code path that is not the governed nomination function
- All identifiers are deterministically reproducible from their inputs (same date + same sequence number → same ID)

**Test requirement:** Unit tests with fixed date injection; no database dependency for generation logic; sequence tests require database

---

### WP-4: Run Orchestrator Core

**Purpose:** Implement the Run Orchestrator skeleton — the component that owns the slate-level and game-level state machines, enforces the kill switch, and provides the stage-trigger structure that future phases will populate with real provider calls and engine invocations.

**Repo area:** `backend/oracle/` (new module)

**Dependencies:** WP-2 (immutability enforcement must be in place before the Orchestrator writes events), WP-3 (Orchestrator calls Identifier Lifecycle Manager for all ID generation)

**Execution order:** After WP-2 and WP-3; parallel with WP-5

**Kill switch specification:**
- Environment variable: `ORACLE_AUTONOMOUS_RUN_ENABLED`
- Read at: Orchestrator startup and before each stage trigger
- Behavior when false or absent: All stage triggers halt immediately; no new stages are triggered; the Orchestrator logs the kill switch state and exits cleanly; the read API (if any exists at this phase) continues unaffected
- Behavior when true: Normal operation
- The kill switch does not delete records, roll back in-progress stages, or corrupt state. It is a clean stop gate.

**Slate-level state machine (Phase 1 skeleton):**

| State | Valid Transitions | Phase 1 Behavior |
|---|---|---|
| `initializing` | → `schedule_loaded` \| `analysis_failed` | Orchestrator creates slate run record; assigns Slate Run ID |
| `schedule_loaded` | → `analysis_in_progress` | Stub: log transition; create game analysis records |
| `analysis_in_progress` | → `activation_window_open` \| `analysis_failed` | Stub: log transition; no engines called in Phase 1 |
| `activation_window_open` | → `pregame_locked` \| `activation_failed` | Stub: log transition; no activations in Phase 1 |
| `pregame_locked` | → `settled` \| `partial_void` | Stub: log transition |
| `settled` | Terminal | Terminal |
| `partial_void` | → `settled` | Stub: log transition |
| `analysis_failed` | Terminal (error) | Alert logged |
| `activation_failed` | Terminal (error) | Alert logged |
| `settlement_pending_retry` | → `settled` | Stub: log transition |

**Game-level state machine (Phase 1 skeleton):**

| State | Valid Transitions |
|---|---|
| `scheduled` | → `preliminary_analysis` |
| `preliminary_analysis` | → `lineup_monitoring` \| `analysis_failed` |
| `lineup_monitoring` | → `final_analysis` |
| `final_analysis` | → `activation_eligible` \| `analysis_failed` |
| `activation_eligible` | → `pregame_locked` |
| `pregame_locked` | → `settled` \| `voided` \| `postponed` |
| `settled` | Terminal |
| `voided` | Terminal |
| `postponed` | Terminal |

**Phase 1 stage execution (stubs):**
In Phase 1, all stages including and beyond Schedule Retrieval are stubs. They do not call any external provider. Schedule and game data is supplied via injected test fixtures. Stage 2 creates `oracle_game_analyses` records from fixture data — not from a live MLB Stats API call. All stages log their invocation, write the appropriate event type to `oracle_play_events`, and transition state. No provider or engine is invoked.

**Acceptance criteria:**
- Kill switch (`ORACLE_AUTONOMOUS_RUN_ENABLED = false`) halts Orchestrator before Stage 2; no records written beyond the kill switch check
- Kill switch (`ORACLE_AUTONOMOUS_RUN_ENABLED = true`) allows Orchestrator to proceed
- Slate run record created with correct Slate Run ID format
- Slate-level state machine transitions are enforced (invalid transitions raise errors, not silent no-ops)
- Game-level state machine transitions are enforced
- All state transitions write the appropriate event to `oracle_play_events`
- `daily_plays_activated` increments atomically; database CHECK constraint prevents value exceeding 3

**Test requirement:** Unit tests for kill switch logic and state machine transitions; integration test for end-to-end run (see WP-6)

---

### WP-5: Event Store Service

**Purpose:** Implement the application-layer service responsible for writing events to `oracle_play_events`. All event writes in the Oracle go through this service — no component writes directly to the events table.

**Repo area:** `backend/oracle/` (new module)

**Dependencies:** WP-2 (immutability trigger must be in place), WP-3 (event records carry Oracle identifiers)

**Execution order:** After WP-2 and WP-3; parallel with WP-4

**27 defined event types (from Section 13.2 of architecture):**

```
slate_initialized           schedule_retrieved          game_analysis_started
ecf_calculated              phie_completed              gse_completed
mve_completed               ce_completed                odg_completed
srl_completed               candidate_created           candidate_reentered
evaluation_version_created  recalculation_triggered     lineup_observation_recorded
lineup_confirmed            lineup_change_detected      play_id_assigned
play_activated              play_locked                 conditional_play_nominated
conditional_resolved        conditional_expired         settlement_completed
settlement_manual_required  le_milestone_detected       le_report_stored
immutability_violation_rejected
```

**Event record structure:**
- `event_id`: auto-assigned by database (BIGSERIAL)
- `event_type`: VARCHAR; must be one of the 27 types above; rejected if unknown
- `slate_run_id`: VARCHAR; FOREIGN KEY → `oracle_slate_runs.slate_run_id`; NOT NULL
- `game_run_id`: VARCHAR; FOREIGN KEY → `oracle_game_analyses.game_run_id`; nullable (slate-level events have no game context)
- `play_id`: VARCHAR; nullable; populated only for play-level events
- `event_timestamp`: TIMESTAMPTZ; always stored in UTC; never inferred — always passed explicitly
- `event_payload`: JSONB; structured data specific to the event type; schema defined per event type in Phase 3+

**Service contract:**
- `record_event(event_type, slate_run_id, event_timestamp, game_run_id=None, play_id=None, payload=None) -> event_id`
- Raises `ValueError` if `event_type` is not one of the 27 defined types
- Raises `ValueError` if `slate_run_id` is not a valid Slate Run ID format
- Attempts INSERT; does not attempt UPDATE or DELETE
- Returns the `event_id` assigned by the database

**Acceptance criteria:**
- All 27 event types accepted without error
- Unknown event type raises `ValueError` before any database call
- Events are retrievable in insertion order by `event_timestamp`
- Service cannot UPDATE or DELETE records (no UPDATE/DELETE code paths exist in the service)
- Database trigger rejects any accidental UPDATE/DELETE and writes to audit table (verified via WP-2)

**Test requirement:** Unit tests for all 27 event types; rejection test for unknown event types; integration test confirming events are written to the table and retrieval order is correct

---

### WP-6: Phase 1 Integration Verification

**Purpose:** End-to-end verification that all Phase 1 work packages produce a system that satisfies all five Phase 1 exit criteria together. This work package does not build anything — it verifies that what was built is correct.

**Repo area:** `backend/tests/oracle/` (new test directory)

**Dependencies:** WP-1, WP-2, WP-3, WP-4, WP-5 all complete and passing their individual acceptance criteria

**Execution order:** Last; nothing is parallel

**Verification tests (mapped to Phase 1 exit criteria):**

| Exit Criterion | Verification Method |
|---|---|
| EC-1: Orchestrator creates slate run with correct ID format | Run Orchestrator; query `oracle_slate_runs`; assert ID matches `ORACLE-YYYYMMDD-NNN` regex |
| EC-2: Game analysis records created with `gamePk`-formatted `external_game_id` | Inject fixture schedule data containing valid `gamePk` values; run Orchestrator Stage 2; query `oracle_game_analyses`; assert `external_game_id` is populated from fixture; no live API call made |
| EC-3: UPDATE and DELETE on `oracle_play_events` raise exceptions and write to audit table | Attempt direct UPDATE and DELETE on `oracle_play_events`; assert exception raised; query `oracle_immutability_audit`; assert one audit record per rejected operation |
| EC-4: Kill switch halts all stage triggers; read API continues | Set `ORACLE_AUTONOMOUS_RUN_ENABLED=false`; invoke Orchestrator; assert no stage progression beyond kill switch check; assert read-path queries succeed |
| EC-5: CHECK constraint blocks `daily_plays_activated` exceeding 3 | Insert slate run with `daily_plays_activated=3`; attempt UPDATE to 4; assert constraint violation raised |

**Acceptance criteria:**
- All five exit criteria pass without manual intervention
- Tests are repeatable (idempotent: run N times, same result)
- Tests do not depend on pre-existing data in the database beyond what they seed themselves
- Tests clean up after themselves (teardown removes seeded records)

---

## SECTION 3 — DEPENDENCY GRAPH

```
[PM Authorization + Schema Confirmation]
             │
             ▼
          ┌─────┐
          │ WP-1 │  Oracle Database Schema (5 tables + constraints)
          └──┬──┘
             │ unblocks
    ┌────────┴────────┐
    ▼                 ▼
 ┌─────┐           ┌─────┐
 │ WP-2 │           │ WP-3 │
 │Immu- │           │ ID   │
 │tabil-│           │Life- │
 │ity   │           │cycle │
 └──┬──┘           └──┬──┘
    │   both must     │
    └────────┬────────┘
             │ unblocks
    ┌────────┴────────┐
    ▼                 ▼
 ┌─────┐           ┌─────┐
 │ WP-4 │           │ WP-5 │
 │Orch- │           │Event │
 │estr- │           │Store │
 │ator  │           │Svc   │
 └──┬──┘           └──┬──┘
    │   both must     │
    └────────┬────────┘
             │ unblocks
             ▼
          ┌─────┐
          │ WP-6 │  Phase 1 Integration Verification
          └─────┘
```

**Critical path:** WP-1 → WP-2 → WP-4 → WP-6 (or equivalently, WP-1 → WP-3 → WP-4 → WP-6)

**Parallelizable pairs:**
- WP-2 and WP-3 may be built in parallel after WP-1
- WP-4 and WP-5 may be built in parallel after WP-2 and WP-3

**Cannot be parallelized:**
- WP-6 cannot begin until all of WP-1 through WP-5 are individually passing
- WP-2 cannot begin until WP-1 schema is in place (trigger requires the target table)
- WP-3 cannot begin until WP-1 schema is in place (sequence generation queries the database)

**External blockers that cannot be parallelized with any WP:**
- PM schema confirmation (CLAUDE.md Rule 6) must precede WP-1
- PO-V1 (PostgreSQL operational status) must be confirmed before any WP begins

---

## SECTION 4 — DATABASE PLANNING

*No SQL is written in this section. Column definitions, data types, and constraints are described in prose for PM schema confirmation. No CREATE TABLE statement may be written until PM confirms the schema.*

### 4.1 `oracle_slate_runs`

**Purpose:** One record per daily Oracle run. Tracks the daily state machine, daily play count, and run-level metadata.

**Key columns:**
- `slate_run_id` — primary key; format `ORACLE-YYYYMMDD-NNN`; generated by Identifier Lifecycle Manager
- `run_date` — the calendar date this slate covers (ET); DATE type; NOT NULL
- `run_status` — current state machine state; VARCHAR; one of the 10 defined states
- `daily_plays_activated` — count of plays activated on this slate; INTEGER; DEFAULT 0; subject to CHECK `<= 3`; incremented atomically at play activation
- `run_started_at` — when Stage 1 began; TIMESTAMPTZ; UTC; NOT NULL
- `run_completed_at` — when settlement completed; TIMESTAMPTZ; UTC; nullable until complete
- `created_at` — record creation timestamp; TIMESTAMPTZ; UTC; DEFAULT NOW()

**Constraints:**
- PRIMARY KEY on `slate_run_id`
- CHECK: `daily_plays_activated >= 0 AND daily_plays_activated <= 3`
- CHECK: `run_date` is a valid date (enforced by DATE type)

**Migration priority:** First (other tables reference this table via foreign key)

**Rollback:** DROP TABLE `oracle_slate_runs` (cascades to dependent tables in rollback order)

---

### 4.2 `oracle_game_analyses`

**Purpose:** One record per game per daily slate run. Tracks the game-level state machine and the canonical game identifier.

**Key columns:**
- `game_run_id` — primary key; format `{slate_run_id}-{game_identifier}`; generated by Identifier Lifecycle Manager
- `slate_run_id` — FOREIGN KEY → `oracle_slate_runs.slate_run_id`; NOT NULL
- `external_game_id` — MLB Stats API `gamePk` value (stored as string); VARCHAR; NOT NULL; this is the canonical Oracle game identifier
- `home_team` — team abbreviation; VARCHAR; NOT NULL
- `away_team` — team abbreviation; VARCHAR; NOT NULL
- `first_pitch_time` — scheduled first pitch; TIMESTAMPTZ; UTC; NOT NULL
- `game_status` — current game-level state; VARCHAR; one of the 9 defined game states
- `venue` — stadium name; VARCHAR; nullable
- `created_at` — record creation timestamp; TIMESTAMPTZ; UTC; DEFAULT NOW()

**Constraints:**
- PRIMARY KEY on `game_run_id`
- FOREIGN KEY `slate_run_id` → `oracle_slate_runs.slate_run_id`
- NOT NULL on `external_game_id`, `home_team`, `away_team`, `first_pitch_time`

**Migration priority:** Second (requires `oracle_slate_runs`)

**Rollback:** DROP TABLE `oracle_game_analyses`

---

### 4.3 `oracle_play_events`

**Purpose:** Append-only event log. One record per event across all Oracle activity. No record is ever modified or deleted after insertion. The PostgreSQL trigger (WP-2) enforces this at the database level.

**Key columns:**
- `event_id` — primary key; BIGSERIAL (auto-increment); not application-generated
- `event_type` — one of the 27 defined event types; VARCHAR; NOT NULL
- `slate_run_id` — FOREIGN KEY → `oracle_slate_runs.slate_run_id`; NOT NULL
- `game_run_id` — FOREIGN KEY → `oracle_game_analyses.game_run_id`; nullable (slate-level events have no game context)
- `play_id` — FOREIGN KEY → `oracle_plays.play_id`; nullable (populated only for play-level events)
- `event_timestamp` — when the event occurred; TIMESTAMPTZ; UTC; NOT NULL; always passed explicitly, never defaulted
- `event_payload` — event-specific structured data; JSONB; nullable in Phase 1 (payload schemas defined in Phase 3+)
- `recorded_at` — when this row was inserted; TIMESTAMPTZ; UTC; DEFAULT NOW()

**Constraints:**
- PRIMARY KEY on `event_id`
- FOREIGN KEY `slate_run_id` → `oracle_slate_runs.slate_run_id`
- FOREIGN KEY `game_run_id` → `oracle_game_analyses.game_run_id` (nullable)
- NOT NULL on `event_type`, `slate_run_id`, `event_timestamp`
- Append-only enforced by PostgreSQL trigger (see WP-2); no application-layer CHECK can substitute for this

**Migration priority:** Third (requires `oracle_slate_runs` and `oracle_game_analyses`; trigger added in WP-2 migration)

**Rollback:** DROP TRIGGER `enforce_play_events_append_only`; DROP TABLE `oracle_play_events`

---

### 4.4 `oracle_plays`

**Purpose:** One record per governed paper bet (Play ID assigned). This table represents the Oracle's formal play record. Records are append-only post-lock at the application layer (`pregame_locked_at` non-null means pregame fields are read-only in application code; the database trigger on `oracle_play_events` is the database-layer guarantee).

**Key columns:**
- `play_id` — primary key; format `EO-YYYY-NNN`; generated by Identifier Lifecycle Manager ONLY at governed nomination
- `candidate_id` — the Candidate ID this play originated from; VARCHAR; NOT NULL
- `slate_run_id` — FOREIGN KEY → `oracle_slate_runs.slate_run_id`; NOT NULL
- `game_run_id` — FOREIGN KEY → `oracle_game_analyses.game_run_id`; NOT NULL
- `market` — market type (e.g., `ML`); VARCHAR; NOT NULL
- `selected_side` — which side the Oracle nominated; VARCHAR; NOT NULL (e.g., `home`, `away`, `over`, `under`)
- `odds_at_nomination` — American odds at time of nomination; INTEGER; NOT NULL
- `stake_units` — paper bet stake in units; NUMERIC; DEFAULT 1.0 (flat stake per architecture)
- `nomination_timestamp` — when Play ID was assigned; TIMESTAMPTZ; UTC; NOT NULL
- `pregame_locked_at` — when the pregame lock was applied; TIMESTAMPTZ; UTC; nullable until lock; non-null = pregame fields immutable at application layer
- `play_status` — current status; VARCHAR; one of: `nominated | conditional | activated | locked | settled | expired | voided | price_breach_no_play`
- `settlement_result` — outcome after game; VARCHAR; nullable until settled; one of: `win | loss | push | void`
- `mock_pnl` — paper P/L in units; NUMERIC; nullable until settled
- `closing_odds` — odds at closing line capture; INTEGER; nullable until capture
- `clv` — closing line value; NUMERIC; nullable until calculated
- `settled_at` — settlement timestamp; TIMESTAMPTZ; UTC; nullable until settled
- `created_at` — record creation timestamp; TIMESTAMPTZ; UTC; DEFAULT NOW()

**Constraints:**
- PRIMARY KEY on `play_id`
- FOREIGN KEY `slate_run_id` → `oracle_slate_runs.slate_run_id`
- FOREIGN KEY `game_run_id` → `oracle_game_analyses.game_run_id`
- NOT NULL on `candidate_id`, `slate_run_id`, `game_run_id`, `market`, `selected_side`, `odds_at_nomination`, `nomination_timestamp`

**Migration priority:** Fourth (requires `oracle_slate_runs` and `oracle_game_analyses`)

**Rollback:** DROP TABLE `oracle_plays`

---

### 4.5 `oracle_immutability_audit`

**Purpose:** Records every rejected write attempt on `oracle_play_events`. Populated exclusively by the PostgreSQL trigger (WP-2); no application code writes to this table directly.

**Key columns:**
- `audit_id` — primary key; BIGSERIAL
- `rejected_event_id` — the `event_id` of the row that a violation attempted to target; BIGINT; nullable (DELETE may not have a specific row target in all cases)
- `violation_type` — `UPDATE` or `DELETE`; VARCHAR; NOT NULL
- `rejected_at` — when the violation was rejected; TIMESTAMPTZ; UTC; DEFAULT NOW()
- `attempted_by` — PostgreSQL session user or role; VARCHAR; NOT NULL
- `detail` — additional context captured by the trigger; TEXT; nullable

**Constraints:**
- PRIMARY KEY on `audit_id`
- NOT NULL on `violation_type`, `rejected_at`, `attempted_by`

**Migration priority:** Fifth (standalone; no foreign keys to Oracle tables required, but logically follows the events table it audits)

**Rollback:** DROP TABLE `oracle_immutability_audit` (drop before trigger in rollback sequence)

---

### 4.6 Migration Order and Rollback Sequence

**Forward migration order:**
1. `oracle_slate_runs`
2. `oracle_game_analyses`
3. `oracle_plays`
4. `oracle_play_events`
5. `oracle_immutability_audit`
6. Trigger: `enforce_play_events_append_only` on `oracle_play_events`
7. CHECK constraint: `daily_plays_activated <= 3` on `oracle_slate_runs`

**Rollback order (reverse):**
1. Drop trigger: `enforce_play_events_append_only`
2. Drop table: `oracle_immutability_audit`
3. Drop table: `oracle_play_events`
4. Drop table: `oracle_plays`
5. Drop table: `oracle_game_analyses`
6. Drop table: `oracle_slate_runs`

All migrations are delivered as files in `database/` with sequential naming. No migration is applied without PM authorization per CLAUDE.md Rule 6.

---

## SECTION 5 — BACKEND PLANNING

### 5.1 New Module Structure

Phase 1 introduces an `oracle` module under `backend/`. The exact file structure is subject to PM authorization. The following describes component responsibilities only.

**`backend/oracle/`** — new package

| Component | Responsibility |
|---|---|
| `identifier_manager` | Generate and validate all Oracle identifiers (Slate Run ID, Game Analysis Run ID, Evaluation ID, Candidate ID, Play ID). Single source of truth for all Oracle ID generation. |
| `event_store` | Write events to `oracle_play_events`. Validates event type against the 27 defined types. Does not read from or modify existing event records. |
| `orchestrator` | Owns slate-level and game-level state machines. Enforces kill switch at startup and before each stage. Coordinates stage execution. Calls Identifier Manager for all ID generation. Calls Event Store for all event writes. |
| `state_machines` | Defines valid state transitions for both state machines. Raises error on invalid transition attempt. |
| `kill_switch` | Reads `ORACLE_AUTONOMOUS_RUN_ENABLED` environment variable. Returns boolean. Called by Orchestrator before each stage trigger. |

### 5.2 Kill Switch Integration Points

The kill switch is checked at these points:
1. Orchestrator startup — before any record is created
2. Before each stage transition — Stages 1 through 10
3. Before each polling loop iteration (Stage 6) — checked per poll cycle

The kill switch does not interrupt an in-progress atomic database operation. It prevents the next stage from beginning.

### 5.3 Timezone Handling

- All scheduling and offset calculations use `America/Toronto` (Eastern Time, IANA)
- All timestamps stored in the database are UTC
- First pitch times in Phase 1 test fixtures are supplied in UTC; the fixture format matches what the MLB Stats API will provide in Phase 2 so that no schema changes are required when live data replaces fixtures
- No timezone-naive timestamps are stored

### 5.4 Phase 1 Exclusions (Backend)

These components are explicitly out of scope for Phase 1:

| Component | Deferral Phase |
|---|---|
| All live provider calls (including MLB Stats API) | Phase 2 |
| Provider adapter implementations | Phase 2 |
| Lineup polling loop | Phase 2 |
| Configuration table | Phase 2 |
| All analytical engines (PHIE, GSE, MVE, CE, LE) | Phase 3 |
| ECF, ODG, SRL | Phase 3 |
| LLM adapter | Phase 3 |
| Play activation logic | Phase 4 |
| Settlement logic | Phase 5 |
| Custom GPT endpoints | Phase 7 |
| LE milestone automation | Phase 8 |

---

## SECTION 6 — TESTING STRATEGY

### 6.1 WP-1 (Database Schema) Tests

| Test | Type | Requirement |
|---|---|---|
| All 5 tables created successfully | Schema validation | Must pass against target database |
| `daily_plays_activated = 4` INSERT rejected | Constraint test | Must raise constraint violation |
| `daily_plays_activated = 3` INSERT accepted | Constraint test | Must succeed |
| Foreign key: game_run_id references valid slate_run_id | FK test | Orphan record rejected |
| NOT NULL constraints | Schema validation | NULL inserts rejected on required columns |

### 6.2 WP-2 (Immutability) Tests

| Test | Type | Requirement |
|---|---|---|
| INSERT on `oracle_play_events` accepted | Positive test | Must succeed |
| UPDATE on `oracle_play_events` raises EXCEPTION | Negative test | Must raise; no partial update |
| DELETE on `oracle_play_events` raises EXCEPTION | Negative test | Must raise; record intact |
| UPDATE violation writes audit record | Audit verification | One audit record per rejected UPDATE |
| DELETE violation writes audit record | Audit verification | One audit record per rejected DELETE |
| Trigger persists after PostgreSQL restart | Persistence test | Trigger must be in migration, not session |

**Note:** These tests cannot use mocks. They must run against a live PostgreSQL instance.

### 6.3 WP-3 (Identifier Manager) Tests

| Test | Type | Requirement |
|---|---|---|
| Slate Run ID format: `ORACLE-20260720-001` | Unit test | Fixed date injection |
| Sequence increments on same-day second call | Unit + DB test | Second call returns `...-002` |
| Evaluation ID includes correct market and version | Unit test | Format verified |
| Play ID only generated by governed nomination path | Unit test | Other call sites raise error |
| All validation functions reject malformed IDs | Unit tests | One test per format |

### 6.4 WP-4 (Orchestrator) Tests

| Test | Type | Requirement |
|---|---|---|
| Kill switch OFF: no stage proceeds | Unit test | Orchestrator exits at kill switch check |
| Kill switch ON: Stage 1 creates slate run record | Integration test | Record in database |
| Invalid state transition raises error | Unit test | e.g., `initializing → settled` rejected |
| Valid state transitions accepted | Unit tests | All defined transitions verified |
| Slate run ID in created record matches format | Integration test | Query database, assert format |

### 6.5 WP-5 (Event Store) Tests

| Test | Type | Requirement |
|---|---|---|
| All 27 event types accepted | Unit tests | One insert per type |
| Unknown event type raises ValueError | Unit test | No database call made |
| Events retrievable in timestamp order | Integration test | Insert 3 events; retrieve; assert order |
| Service has no UPDATE or DELETE code paths | Code inspection | Static verification |

### 6.6 WP-6 (Integration Verification) Tests

These are the Phase 1 exit criteria tests. See Section 2 WP-6 for full specifications.

| Exit Criterion | Test |
|---|---|
| EC-1 | End-to-end Orchestrator run; assert Slate Run ID format in database |
| EC-2 | Inject fixture schedule data; run Stage 2; assert `external_game_id` populated from fixture; no live API call |
| EC-3 | Attempt UPDATE/DELETE on events table; assert exception + audit record |
| EC-4 | Kill switch OFF; run Orchestrator; assert no progression |
| EC-5 | Attempt `daily_plays_activated = 4`; assert constraint violation |

### 6.7 Testing Constraints

- WP-2 and WP-6 (EC-3) tests must run against a live PostgreSQL instance — triggers cannot be mocked
- WP-1 constraint tests must run against a live database
- All tests must be idempotent and self-cleaning
- Phase 1 makes no live calls to any external provider; all schedule and game data in tests is fixture-based

---

## SECTION 7 — RISK REGISTER

### Risk 1: PostgreSQL Operational Status Unverified (PO-V1)

| Attribute | Detail |
|---|---|
| **Probability** | Medium — PostgreSQL integration is verified in `backend/db.py` but live instance status is unconfirmed |
| **Impact** | High — all database work packages fail if the PostgreSQL instance is not running |
| **Mitigation** | Complete PO-V1 verification before any implementation begins; confirm connection via `backend/scripts/test_db_connection.py` |
| **Verification** | `test_db_connection.py` succeeds against target database before WP-1 begins |

---

### Risk 2: Schema Revision After PM Review (CLAUDE.md Rule 6)

| Attribute | Detail |
|---|---|
| **Probability** | Medium — schema is planned but not yet reviewed by PM |
| **Impact** | High — late schema changes affect WP-2 trigger, WP-3 ID formats, WP-4 Orchestrator, and WP-5 Event Store |
| **Mitigation** | Schema submitted for PM review and confirmed before any migration is written; no partial implementation of schema |
| **Verification** | PM explicitly confirms schema in writing before WP-1 begins |

---

### Risk 3: PostgreSQL Trigger Incompatibility

| Attribute | Detail |
|---|---|
| **Probability** | Low — standard PostgreSQL trigger syntax is stable across versions |
| **Impact** | Medium — immutability enforcement is a Phase 1 exit criterion |
| **Mitigation** | Verify PostgreSQL version in use before writing trigger; trigger syntax targeted to that version |
| **Verification** | WP-2 acceptance test passes on the target PostgreSQL instance |

---

### Risk 4: Sequence Management Race Condition (Identifier Manager)

| Attribute | Detail |
|---|---|
| **Probability** | Low in current single-process architecture; increases if concurrent Orchestrator processes are ever introduced |
| **Impact** | Medium — duplicate Slate Run IDs would violate PRIMARY KEY constraint |
| **Mitigation** | Use database-level sequence or SELECT + lock when determining next sequence value; do not rely on application-side counters or in-memory state |
| **Verification** | Concurrent insertion test under WP-3 acceptance criteria |

---

### Risk 5: State Machine Transition Gaps

| Attribute | Detail |
|---|---|
| **Probability** | Low — transitions are fully specified in the architecture |
| **Impact** | Low in Phase 1 (no providers or engines); High in Phase 4+ (incorrect transitions could corrupt run state) |
| **Mitigation** | Implement transitions as an explicit allowlist; any transition not in the allowlist raises an error rather than silently failing |
| **Verification** | All invalid transition tests in WP-4 test suite pass |

---

## SECTION 8 — PHASE GATES

### 8.1 Pre-Implementation Gate

No implementation begins until all of the following are confirmed:

| Item | Source | Status at Plan Date |
|---|---|---|
| PM Decision Point 10 authorization to begin Phase 1 | Section 22 of architecture | Pending PM authorization |
| PM schema confirmation (CLAUDE.md Rule 6) | CLAUDE.md | Pending PM review of Section 4 of this document |
| PO-V1: PostgreSQL operational instance confirmed | Pre-Phase-1 verification items | Pending Project Owner verification |

### 8.2 WP-1 Gate

| Criterion | Verified By |
|---|---|
| All 5 tables created in target database | Direct database query |
| CHECK constraint on `daily_plays_activated` working | Constraint test (value = 4 rejected) |
| Foreign keys enforced | FK violation test |
| Migration file exists in `database/` | File inspection |

### 8.3 WP-2 Gate

| Criterion | Verified By |
|---|---|
| INSERT on `oracle_play_events` accepted | Direct SQL test |
| UPDATE on `oracle_play_events` raises EXCEPTION | Direct SQL test |
| DELETE on `oracle_play_events` raises EXCEPTION | Direct SQL test |
| Rejected writes appear in `oracle_immutability_audit` | Direct query of audit table |

### 8.4 WP-3 Gate

| Criterion | Verified By |
|---|---|
| Slate Run ID generation correct format | Unit test with fixed date |
| Sequence increments correctly | Unit + DB test |
| Play ID generation restricted to governed path | Unit test |
| All validation functions working | Unit tests |

### 8.5 WP-4 Gate

| Criterion | Verified By |
|---|---|
| Kill switch OFF: Orchestrator halts before Stage 1 | Unit test |
| Kill switch ON: Slate run record created with correct ID | Integration test |
| Invalid state transitions raise errors | Unit tests |
| Slate-level and game-level machines enforce all defined transitions | Unit tests |

### 8.6 WP-5 Gate

| Criterion | Verified By |
|---|---|
| All 27 event types accepted | Unit tests |
| Unknown event type raises ValueError | Unit test |
| Events retrievable in order | Integration test |

### 8.7 Phase 1 Exit Gate (EC-1 through EC-5)

| Exit Criterion | Verified By |
|---|---|
| EC-1: Slate Run ID format correct | WP-6 integration test |
| EC-2: `external_game_id` populated from fixture data in `gamePk` format | WP-6 integration test (fixture-based; no live provider call) |
| EC-3: UPDATE/DELETE raise exceptions + audit record | WP-6 integration test |
| EC-4: Kill switch halts stage triggers | WP-6 integration test |
| EC-5: `daily_plays_activated > 3` rejected | WP-6 integration test |

**Phase 1 is complete when all five exit criteria pass in WP-6 integration verification.**

---

## SECTION 9 — TRACEABILITY MATRIX

### 9.1 Work Package to Architecture Section

| Work Package | Primary Architecture Sections |
|---|---|
| WP-1: Oracle Database Schema | Section 21 Phase 1 (deliverables), Section 7.1 (stage actions), Section 10 (state machines), Section 13 (event model) |
| WP-2: Immutability Enforcement | Section 13.3 (trigger specification), Section 13.4 (audit table), Section 20.1 EC-3 |
| WP-3: Identifier Lifecycle Manager | Section 6 (full identifier lifecycle), Section 7.1 Stage 1 and Stage 2 (ID assignment points) |
| WP-4: Run Orchestrator Core | Section 12 (Run Orchestrator), Section 10.1 (slate state machine), Section 10.2 (game state machine), Section 12.2 (kill switch), Section 20.1 EC-1, EC-4 |
| WP-5: Event Store Service | Section 13.1 (event model principles), Section 13.2 (27 event types), Section 13.3 (append-only enforcement) |
| WP-6: Integration Verification | Section 20.1 (all five Phase 1 exit criteria) |

### 9.2 Exit Criteria to Work Package

| Exit Criterion | Implemented By | Tested By |
|---|---|---|
| EC-1: Slate Run ID format | WP-3 (ID generation) + WP-4 (Orchestrator Stage 1) | WP-6 |
| EC-2: `external_game_id` = `gamePk` | WP-4 (Orchestrator Stage 2) | WP-6 |
| EC-3: Immutability violations logged | WP-2 (trigger) | WP-6 |
| EC-4: Kill switch halts triggers | WP-4 (kill switch in Orchestrator) | WP-6 |
| EC-5: Daily cap enforced | WP-1 (CHECK constraint) | WP-6 |

### 9.3 PM Decision Points Affecting Phase 1

| Decision Point | Phase 1 Impact | Status |
|---|---|---|
| DP-10: Multi-window slot policy | Required as Phase 1 prerequisite per Section 21 | Pending PM authorization |

### 9.4 Pre-Phase-1 Verification Items Affecting Phase 1

| Verification Item | Phase 1 Impact |
|---|---|
| PO-V1: PostgreSQL operational status | Blocks all WPs; no database work possible without confirmed instance |
| PO-V6: Existing database table definitions | Required to confirm no naming conflicts between existing tables and the 5 new Oracle tables |

---

*ORACLE PHASE 1 IMPLEMENTATION PLAN — Edge Oracle, MLB Betting Edge Project*
*Architecture Reference: ORACLE_INTELLIGENCE_ARCHITECTURE_v1_2.md Final Candidate*
*Plan Status: Final — Awaiting PM Authorization to Begin Implementation*
