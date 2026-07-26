# ORACLE PHASE 1 IMPLEMENTATION BACKLOG
**Edge Oracle / MLB Betting Edge**
**Status: Awaiting PM Authorization to Begin Implementation**
**Plan Reference:** ORACLE_PHASE_1_IMPLEMENTATION_PLAN.md (Final)
**Architecture Reference:** ORACLE_INTELLIGENCE_ARCHITECTURE_v1_2.md (Final Candidate)
**Date Prepared:** 2026-07-20

---

## DOCUMENT PURPOSE

This backlog decomposes every approved Phase 1 work package into individual, independently verifiable implementation tasks. It is the master execution checklist for Phase 1 once PM authorization is received.

**This document does not constitute:**
- Authorization to write code
- Authorization to create or modify database tables
- Authorization to run schedulers or background processes
- Authorization to modify governance or architecture

All tasks in this backlog are planning artifacts. No task may be started until Phase 1 is formally authorized.

---

## READING THIS DOCUMENT

**Task ID format:** `P1-WP{work-package-number}-T{task-number}` (e.g., `P1-WP1-T03`)

**Execution order:** Tasks must be executed in dependency order. The approved critical path is:

```
WP-1 → {WP-2 ∥ WP-3} → {WP-4 ∥ WP-5} → WP-6
```

Within the WP-4/WP-5 parallel window, an internal dependency exists: WP-4 tasks that write events (T05 onward) require WP-5-T02 (the Event Store write function) to be complete. WP-4-T01 through T04 and WP-5-T01 through T02 may proceed in parallel.

**Complexity scale:**
- **S** — Small: straightforward, few moving parts, low integration surface
- **M** — Medium: multiple components, moderate integration, meaningful test surface
- **L** — Large: several sub-components, broad integration, full test matrix required

**Statuses used:** `Not Started` | `In Progress` | `Complete` | `Blocked`

---

## PRE-BACKLOG GATE

The following items must be confirmed by the PM and Project Owner before the first task begins. None of these are implementation tasks — they are authorization and verification items from the Phase 1 Plan (Section 8.1).

| Item | Source | Required Before |
|---|---|---|
| PM Decision Point 10: authorization to begin Phase 1 | Architecture Section 22 | Any task |
| PM schema confirmation (CLAUDE.md Rule 6) | CLAUDE.md | P1-WP1-T03 |
| PO-V1: PostgreSQL operational instance confirmed | Pre-Phase-1 verification items | P1-WP1-T01 |
| PO-V6: Existing database table definitions reviewed for naming conflicts | Pre-Phase-1 verification items | P1-WP1-T02 |

---

## WP-1: ORACLE DATABASE SCHEMA

**Work Package Purpose:** Create the five Phase 1 Oracle tables and all database-level constraints. Every subsequent work package depends on this schema.

**Repo area:** `database/`

**WP-1 dependency:** PM schema confirmation required before any migration is written (CLAUDE.md Rule 6).

---

### P1-WP1-T01 — Verify PostgreSQL Instance and Confirm No Table Name Conflicts

| Field | Detail |
|---|---|
| **Task ID** | P1-WP1-T01 |
| **Parent WP** | WP-1: Oracle Database Schema |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Confirm that the target PostgreSQL instance is operational and that none of the five new Oracle table names conflict with existing tables in the database. This task gates all schema work — no migration may be written until this verification is complete.

The five names to check: `oracle_slate_runs`, `oracle_game_analyses`, `oracle_play_events`, `oracle_plays`, `oracle_immutability_audit`.

**Dependencies:** PO-V1 (PostgreSQL instance accessible); PO-V6 (existing table list available)

**Repository areas affected:** None — read-only verification against live database

**Acceptance criteria:**
- PostgreSQL instance accepts a connection via the configured `DATABASE_URL`
- `backend/scripts/test_db_connection.py` completes without error
- None of the five Oracle table names already exist in the database
- Result of the verification is documented and provided to PM before schema work begins

**Required tests:** Manual — run `test_db_connection.py`; query `information_schema.tables` for each of the five table names

**Expected deliverable:** Verification confirmation (written note to PM); no files created or modified

---

### P1-WP1-T02 — Define Migration File Structure and Naming Convention

| Field | Detail |
|---|---|
| **Task ID** | P1-WP1-T02 |
| **Parent WP** | WP-1: Oracle Database Schema |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Establish the naming convention and sequencing approach for all Phase 1 migration files before any migration is written. Confirm whether the `database/` directory already uses a sequential numbering scheme; if so, determine the next available sequence numbers. Establish the forward/rollback file naming pattern that will be used for all Phase 1 migrations.

**Dependencies:** P1-WP1-T01 (instance verified); PM schema confirmation must be received before the first migration is written

**Repository areas affected:** `database/` (read-only review)

**Acceptance criteria:**
- Migration file naming convention documented and agreed with PM
- Next available sequence number identified
- Rollback file convention established (either a separate down-migration file or a rollback block within each migration file, per existing project convention)

**Required tests:** None — planning artifact

**Expected deliverable:** Short written convention note (may be in a comment at the top of the first migration file once writing begins); no files created until PM schema confirmation received

---

### P1-WP1-T03 — Create `oracle_slate_runs` Table Migration

| Field | Detail |
|---|---|
| **Task ID** | P1-WP1-T03 |
| **Parent WP** | WP-1: Oracle Database Schema |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Write the forward migration for `oracle_slate_runs`. This is the first table in the migration order because all other Oracle tables reference it via foreign key. The CHECK constraint on `daily_plays_activated` is part of this migration.

Columns per plan Section 4.1: `slate_run_id` (VARCHAR PK, format `ORACLE-YYYYMMDD-NNN`), `run_date` (DATE NOT NULL), `run_status` (VARCHAR), `daily_plays_activated` (INTEGER NOT NULL DEFAULT 0), `run_started_at` (TIMESTAMPTZ UTC NOT NULL), `run_completed_at` (TIMESTAMPTZ UTC nullable), `created_at` (TIMESTAMPTZ UTC DEFAULT NOW()).

Constraints per plan Section 4.1: PRIMARY KEY on `slate_run_id`; CHECK `daily_plays_activated >= 0 AND daily_plays_activated <= 3`.

**Dependencies:** P1-WP1-T02 (naming convention established); PM schema confirmation received

**Repository areas affected:** `database/` (new migration file)

**Acceptance criteria:**
- Migration file created with correct sequential name
- `oracle_slate_runs` table created in target database when migration is applied
- CHECK constraint `daily_plays_activated <= 3` present and enforced
- Rollback block drops the table cleanly

**Required tests:** Apply migration; verify table exists; insert record with `daily_plays_activated = 3` (succeeds); insert record with `daily_plays_activated = 4` (raises constraint violation); rollback migration; verify table is gone

**Expected deliverable:** Migration file in `database/`

---

### P1-WP1-T04 — Create `oracle_game_analyses` Table Migration

| Field | Detail |
|---|---|
| **Task ID** | P1-WP1-T04 |
| **Parent WP** | WP-1: Oracle Database Schema |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Write the forward migration for `oracle_game_analyses`. This table references `oracle_slate_runs` via foreign key and must be created after it.

Columns per plan Section 4.2: `game_run_id` (VARCHAR PK, format `{slate_run_id}-{game_identifier}`), `slate_run_id` (VARCHAR NOT NULL FK → `oracle_slate_runs.slate_run_id`), `external_game_id` (VARCHAR NOT NULL — stores MLB Stats API `gamePk`), `home_team` (VARCHAR NOT NULL), `away_team` (VARCHAR NOT NULL), `first_pitch_time` (TIMESTAMPTZ UTC NOT NULL), `game_status` (VARCHAR), `venue` (VARCHAR nullable), `created_at` (TIMESTAMPTZ UTC DEFAULT NOW()).

**Dependencies:** P1-WP1-T03 (`oracle_slate_runs` migration applied and verified)

**Repository areas affected:** `database/` (new migration file)

**Acceptance criteria:**
- `oracle_game_analyses` table created in target database when migration is applied
- Foreign key to `oracle_slate_runs` enforced (inserting a record with a non-existent `slate_run_id` raises FK violation)
- NOT NULL constraints on `external_game_id`, `home_team`, `away_team`, `first_pitch_time` enforced
- Rollback block drops the table cleanly

**Required tests:** Apply migration; FK violation test; NOT NULL violation tests; rollback test

**Expected deliverable:** Migration file in `database/`

---

### P1-WP1-T05 — Create `oracle_plays` Table Migration

| Field | Detail |
|---|---|
| **Task ID** | P1-WP1-T05 |
| **Parent WP** | WP-1: Oracle Database Schema |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Write the forward migration for `oracle_plays`. This table references both `oracle_slate_runs` and `oracle_game_analyses` and must be created after both. It is created before `oracle_play_events` because the events table carries a nullable FK to `oracle_plays.play_id`.

Columns per plan Section 4.4: `play_id` (VARCHAR PK, format `EO-YYYY-NNN`), `candidate_id` (VARCHAR NOT NULL), `slate_run_id` (VARCHAR NOT NULL FK → `oracle_slate_runs.slate_run_id`), `game_run_id` (VARCHAR NOT NULL FK → `oracle_game_analyses.game_run_id`), `market` (VARCHAR NOT NULL), `selected_side` (VARCHAR NOT NULL), `odds_at_nomination` (INTEGER NOT NULL), `stake_units` (NUMERIC DEFAULT 1.0), `nomination_timestamp` (TIMESTAMPTZ UTC NOT NULL), `pregame_locked_at` (TIMESTAMPTZ UTC nullable), `play_status` (VARCHAR), `settlement_result` (VARCHAR nullable), `mock_pnl` (NUMERIC nullable), `closing_odds` (INTEGER nullable), `clv` (NUMERIC nullable), `settled_at` (TIMESTAMPTZ UTC nullable), `created_at` (TIMESTAMPTZ UTC DEFAULT NOW()).

**Dependencies:** P1-WP1-T04 (`oracle_game_analyses` migration applied and verified)

**Repository areas affected:** `database/` (new migration file)

**Acceptance criteria:**
- `oracle_plays` table created in target database when migration is applied
- Foreign keys to `oracle_slate_runs` and `oracle_game_analyses` enforced
- NOT NULL constraints on required columns enforced
- Rollback block drops the table cleanly

**Required tests:** Apply migration; FK violation tests (both FKs); NOT NULL violation tests; rollback test

**Expected deliverable:** Migration file in `database/`

---

### P1-WP1-T06 — Create `oracle_play_events` Table Migration

| Field | Detail |
|---|---|
| **Task ID** | P1-WP1-T06 |
| **Parent WP** | WP-1: Oracle Database Schema |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Write the forward migration for `oracle_play_events`. This is the append-only event log. The table structure is created here; the PostgreSQL trigger that enforces append-only behavior is added in WP-2.

Columns per plan Section 4.3: `event_id` (BIGSERIAL PK, auto-assigned by database), `event_type` (VARCHAR NOT NULL), `slate_run_id` (VARCHAR NOT NULL FK → `oracle_slate_runs.slate_run_id`), `game_run_id` (VARCHAR nullable FK → `oracle_game_analyses.game_run_id`), `play_id` (VARCHAR nullable FK → `oracle_plays.play_id`), `event_timestamp` (TIMESTAMPTZ UTC NOT NULL), `event_payload` (JSONB nullable), `recorded_at` (TIMESTAMPTZ UTC DEFAULT NOW()).

**Dependencies:** P1-WP1-T05 (`oracle_plays` migration applied and verified)

**Repository areas affected:** `database/` (new migration file)

**Acceptance criteria:**
- `oracle_play_events` table created in target database when migration is applied
- Foreign key to `oracle_slate_runs` enforced
- Nullable FKs to `oracle_game_analyses` and `oracle_plays` defined correctly (null values accepted; non-null non-existent values rejected)
- NOT NULL constraints on `event_type`, `slate_run_id`, `event_timestamp` enforced
- `event_id` is auto-assigned by the database (BIGSERIAL); application code never sets it
- Rollback block drops the table cleanly

**Required tests:** Apply migration; FK and NOT NULL constraint tests; verify `event_id` is auto-assigned; rollback test

**Expected deliverable:** Migration file in `database/`

---

### P1-WP1-T07 — Create `oracle_immutability_audit` Table Migration

| Field | Detail |
|---|---|
| **Task ID** | P1-WP1-T07 |
| **Parent WP** | WP-1: Oracle Database Schema |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Write the forward migration for `oracle_immutability_audit`. This table is populated exclusively by the PostgreSQL trigger (WP-2) — no application code writes to it directly. It has no foreign keys to other Oracle tables.

Columns per plan Section 4.5: `audit_id` (BIGSERIAL PK), `rejected_event_id` (BIGINT nullable), `violation_type` (VARCHAR NOT NULL — `UPDATE` or `DELETE`), `rejected_at` (TIMESTAMPTZ UTC DEFAULT NOW()), `attempted_by` (VARCHAR NOT NULL), `detail` (TEXT nullable).

**Dependencies:** P1-WP1-T06 (`oracle_play_events` must exist before this table's trigger, added in WP-2, can reference it)

**Repository areas affected:** `database/` (new migration file)

**Acceptance criteria:**
- `oracle_immutability_audit` table created in target database when migration is applied
- NOT NULL constraints on `violation_type`, `attempted_by` enforced
- `audit_id` is auto-assigned by the database (BIGSERIAL)
- Rollback block drops the table cleanly

**Required tests:** Apply migration; NOT NULL constraint test; verify `audit_id` auto-assigns; rollback test

**Expected deliverable:** Migration file in `database/`

---

### P1-WP1-T08 — WP-1 Schema Validation Tests

| Field | Detail |
|---|---|
| **Task ID** | P1-WP1-T08 |
| **Parent WP** | WP-1: Oracle Database Schema |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Execute the complete set of WP-1 acceptance tests against the target database with all five migrations applied. This is the WP-1 gate; all tests must pass before WP-2 or WP-3 work may begin.

Tests per plan Section 6.1:
1. All five tables exist in target database (query `information_schema.tables`)
2. `daily_plays_activated = 3` INSERT succeeds in `oracle_slate_runs`
3. `daily_plays_activated = 4` INSERT raises constraint violation
4. Orphan game record (non-existent `slate_run_id`) raises FK violation
5. NULL insert on each NOT NULL column raises NOT NULL violation

**Dependencies:** P1-WP1-T07 (all five migrations applied)

**Repository areas affected:** `database/` (read-only verification against applied migrations)

**Acceptance criteria:**
- All five tests listed above pass against the live database
- No manual intervention required to pass any test
- Results documented and provided to PM as WP-1 gate evidence

**Required tests:** As enumerated in Description; must run against live PostgreSQL instance — cannot be mocked

**Expected deliverable:** Written test results (pass/fail for each of the five tests)

---

## WP-2: IMMUTABILITY ENFORCEMENT

**Work Package Purpose:** Implement the PostgreSQL trigger that makes `oracle_play_events` append-only. This is a database-layer guarantee that application code cannot bypass.

**Repo area:** `database/`

**WP-2 dependency:** WP-1 complete (P1-WP1-T08 passed). Trigger cannot be created until `oracle_play_events` and `oracle_immutability_audit` tables exist.

**Execution order:** Parallel with WP-3 after WP-1.

---

### P1-WP2-T01 — Write Trigger Migration: `enforce_play_events_append_only`

| Field | Detail |
|---|---|
| **Task ID** | P1-WP2-T01 |
| **Parent WP** | WP-2: Immutability Enforcement |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Write the forward migration that creates the `enforce_play_events_append_only` trigger (or equivalent name) on `oracle_play_events`. The trigger fires BEFORE UPDATE and BEFORE DELETE. When fired, it must: (a) raise an exception with a message identifying the attempted operation and the event record targeted; (b) insert one record into `oracle_immutability_audit` capturing the `violation_type`, `rejected_at`, and `attempted_by` (current PostgreSQL session user).

The trigger must NOT fire on INSERT — appending new events must succeed normally.

This is the sole database-layer enforcement of Oracle Constitutional Rule 4 (No Rewriting History) and the immutability model described in architecture Section 13.3.

Verify PostgreSQL version before writing — trigger syntax is version-stable but version should be confirmed.

**Dependencies:** P1-WP1-T08 (WP-1 gate passed; `oracle_play_events` and `oracle_immutability_audit` tables exist in target database)

**Repository areas affected:** `database/` (new migration file)

**Acceptance criteria:**
- Trigger created and attached to `oracle_play_events` in target database
- INSERT on `oracle_play_events` succeeds without triggering the function
- UPDATE on any row in `oracle_play_events` raises EXCEPTION
- DELETE on any row in `oracle_play_events` raises EXCEPTION
- Each rejected UPDATE inserts exactly one record into `oracle_immutability_audit` with `violation_type = 'UPDATE'`
- Each rejected DELETE inserts exactly one record into `oracle_immutability_audit` with `violation_type = 'DELETE'`
- `attempted_by` in the audit record reflects the database session user at time of violation
- Trigger is defined in a migration file and persists after a PostgreSQL process restart (not a session-level definition)

**Required tests:** Direct SQL tests against live database; see P1-WP2-T03

**Expected deliverable:** Migration file in `database/`

---

### P1-WP2-T02 — Write Trigger Rollback Migration

| Field | Detail |
|---|---|
| **Task ID** | P1-WP2-T02 |
| **Parent WP** | WP-2: Immutability Enforcement |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Write the rollback migration that drops the `enforce_play_events_append_only` trigger. The rollback migration must be written alongside the forward migration (not deferred). The drop must occur before any table drops in the rollback sequence.

Per plan Section 4.6 rollback order: trigger is dropped first, before `oracle_immutability_audit`, before `oracle_play_events`.

**Dependencies:** P1-WP2-T01 (trigger migration written)

**Repository areas affected:** `database/` (rollback migration file or rollback block within trigger migration)

**Acceptance criteria:**
- Rollback migration drops the trigger cleanly without error
- After rollback: UPDATE and DELETE on `oracle_play_events` succeed (trigger no longer blocks them)
- Rollback does not affect the `oracle_immutability_audit` table structure (only the trigger is removed)

**Required tests:** Apply forward migration; apply rollback migration; verify UPDATE succeeds after rollback

**Expected deliverable:** Rollback migration file or rollback block in `database/`

---

### P1-WP2-T03 — Immutability Enforcement Tests

| Field | Detail |
|---|---|
| **Task ID** | P1-WP2-T03 |
| **Parent WP** | WP-2: Immutability Enforcement |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Execute the complete set of WP-2 acceptance tests. These tests cannot use mocks — they must run against the live PostgreSQL database with the trigger applied. This is the WP-2 gate.

Tests per plan Section 6.2:
1. INSERT on `oracle_play_events` with valid data succeeds
2. UPDATE on a row in `oracle_play_events` raises EXCEPTION (test with a direct SQL UPDATE)
3. DELETE on a row in `oracle_play_events` raises EXCEPTION (test with a direct SQL DELETE)
4. Rejected UPDATE results in exactly one new record in `oracle_immutability_audit` with `violation_type = 'UPDATE'`
5. Rejected DELETE results in exactly one new record in `oracle_immutability_audit` with `violation_type = 'DELETE'`
6. Trigger is still active after PostgreSQL process restart (persistence test)

**Dependencies:** P1-WP2-T01 (trigger migration applied); P1-WP2-T02 (rollback migration present and tested separately)

**Repository areas affected:** None — verification against live database

**Acceptance criteria:**
- All six tests pass against the live database
- No manual intervention required
- Results documented as WP-2 gate evidence

**Required tests:** Direct SQL tests as enumerated; cannot be mocked

**Expected deliverable:** Written test results (pass/fail for each of the six tests)

---

## WP-3: IDENTIFIER LIFECYCLE MANAGER

**Work Package Purpose:** Implement the single Python module responsible for generating and validating all Oracle identifiers. No other module in Phase 1 generates Oracle IDs.

**Repo area:** `backend/oracle/`

**WP-3 dependency:** WP-1 complete (P1-WP1-T08 passed). Sequence generation logic queries the database; schema must exist.

**Execution order:** Parallel with WP-2 after WP-1.

---

### P1-WP3-T01 — Create `backend/oracle/` Package Scaffold

| Field | Detail |
|---|---|
| **Task ID** | P1-WP3-T01 |
| **Parent WP** | WP-3: Identifier Lifecycle Manager |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Create the `backend/oracle/` Python package directory. This directory houses all Phase 1 Oracle backend components — the Identifier Lifecycle Manager (WP-3), the Event Store Service (WP-5), the Run Orchestrator (WP-4), state machines, kill switch reader, and fixture loader.

The package scaffold is created once here; all subsequent WP-3, WP-4, and WP-5 tasks add modules within this package.

**Dependencies:** P1-WP1-T08 (WP-1 gate passed)

**Repository areas affected:** `backend/oracle/` (new directory)

**Acceptance criteria:**
- `backend/oracle/` directory exists
- `backend/oracle/__init__.py` is present and importable
- Package can be imported from the existing FastAPI application without errors
- No other modules are created in this task

**Required tests:** Import the `oracle` package from a Python shell; confirm no import errors

**Expected deliverable:** `backend/oracle/__init__.py`

---

### P1-WP3-T02 — Implement Slate Run ID Generator

| Field | Detail |
|---|---|
| **Task ID** | P1-WP3-T02 |
| **Parent WP** | WP-3: Identifier Lifecycle Manager |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Implement the Slate Run ID generation function within `backend/oracle/identifier_manager.py` (or equivalent module name). The function must:
- Accept the current date (in ET, as a `datetime.date` object) as a parameter — never derive it internally, to allow deterministic testing with fixed dates
- Query `oracle_slate_runs` to count existing runs for the same date and determine the next sequence number
- Return a string of format `ORACLE-YYYYMMDD-NNN` where NNN is zero-padded to 3 digits (e.g., `ORACLE-20260720-001`)
- Never use application-side counters or in-memory state for sequence tracking — always query the database

**Dependencies:** P1-WP3-T01 (package scaffold exists); WP-1 complete (database schema in place for sequence query)

**Repository areas affected:** `backend/oracle/identifier_manager.py` (new file)

**Acceptance criteria:**
- With zero existing runs for the test date, generates `ORACLE-{YYYYMMDD}-001`
- With one existing run for the test date, generates `ORACLE-{YYYYMMDD}-002`
- Sequence suffix is always three digits zero-padded
- Date portion uses the supplied date parameter (not `datetime.now()` or system clock)
- Format matches `ORACLE-\d{8}-\d{3}` regex exactly

**Required tests:** Unit test with fixed date injection and zero prior runs (expects `001`); unit test with fixed date and one prior run in database (expects `002`); regex format validation test

**Expected deliverable:** `backend/oracle/identifier_manager.py` (Slate Run ID function)

---

### P1-WP3-T03 — Implement Game Analysis Run ID Generator

| Field | Detail |
|---|---|
| **Task ID** | P1-WP3-T03 |
| **Parent WP** | WP-3: Identifier Lifecycle Manager |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Implement the Game Analysis Run ID generation function. Format: `{slate_run_id}-{game_identifier}` where `game_identifier` is derived from the game context (e.g., `BOS-NYY` from home and away team abbreviations). This function is deterministic from its inputs and does not query the database.

The game identifier component must be consistent with how `external_game_id` values are stored in `oracle_game_analyses`; it identifies the game uniquely within the slate.

**Dependencies:** P1-WP3-T02 (Slate Run ID generator implemented in same module)

**Repository areas affected:** `backend/oracle/identifier_manager.py`

**Acceptance criteria:**
- Given `slate_run_id = "ORACLE-20260720-001"` and game identifier context, returns a correctly formatted game run ID
- Output is deterministic: same inputs always produce the same ID
- No database query performed

**Required tests:** Unit test with known input → known output; format validation test

**Expected deliverable:** Game Analysis Run ID function added to `backend/oracle/identifier_manager.py`

---

### P1-WP3-T04 — Implement Evaluation ID Generator

| Field | Detail |
|---|---|
| **Task ID** | P1-WP3-T04 |
| **Parent WP** | WP-3: Identifier Lifecycle Manager |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Implement the Evaluation ID generation function. Format: `EVAL-{game_run_id}-{market}-{version}` (e.g., `EVAL-ORACLE-20260720-001-BOS-NYY-ML-v1`). This function is deterministic from its inputs; no database query is required. The `version` parameter is an integer; the generator formats it with the `v` prefix.

**Dependencies:** P1-WP3-T03 (same module)

**Repository areas affected:** `backend/oracle/identifier_manager.py`

**Acceptance criteria:**
- Returns correctly formatted Evaluation ID for given game run ID, market, and version number
- Version 1 produces `...v1`; version 2 produces `...v2`
- Deterministic from inputs

**Required tests:** Unit test with known inputs → known output; version increment test

**Expected deliverable:** Evaluation ID function added to `backend/oracle/identifier_manager.py`

---

### P1-WP3-T05 — Implement Candidate ID Generator

| Field | Detail |
|---|---|
| **Task ID** | P1-WP3-T05 |
| **Parent WP** | WP-3: Identifier Lifecycle Manager |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Implement the Candidate ID generation function. Format: `CAND-{game_run_id}-{market}` (e.g., `CAND-ORACLE-20260720-001-BOS-NYY-ML`). One Candidate ID per market per game per daily slate. Deterministic from inputs; no database query required.

**Dependencies:** P1-WP3-T03 (same module)

**Repository areas affected:** `backend/oracle/identifier_manager.py`

**Acceptance criteria:**
- Returns correctly formatted Candidate ID for given game run ID and market
- Deterministic from inputs
- Format distinct from Evaluation ID (prefix `CAND-` vs. `EVAL-`)

**Required tests:** Unit test with known inputs → known output; format distinction test vs. Evaluation ID

**Expected deliverable:** Candidate ID function added to `backend/oracle/identifier_manager.py`

---

### P1-WP3-T06 — Implement Play ID Generator with Governed-Path Restriction

| Field | Detail |
|---|---|
| **Task ID** | P1-WP3-T06 |
| **Parent WP** | WP-3: Identifier Lifecycle Manager |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Implement the Play ID generation function. Format: `EO-YYYY-NNN` (e.g., `EO-2026-001`). The sequence is per calendar year, sourced from a database query on `oracle_plays`.

This function is architecturally distinct from the others because of the governed-path restriction: it must be callable **only** from the designated nomination function within the Orchestrator. All other call sites must receive an error. This restriction is enforced in the implementation — not just in documentation.

The mechanism for enforcement (a flag, a caller check, a module-private function, or another approach) is an implementation decision, but the outcome must be: any invocation of Play ID generation from outside the governed nomination path raises an error before any database call is made.

Per architecture Section 6.3: Play ID is never assigned at preliminary candidate creation.

**Dependencies:** P1-WP3-T01 (package scaffold); WP-1 complete (database schema in place for sequence query on `oracle_plays`)

**Repository areas affected:** `backend/oracle/identifier_manager.py`

**Acceptance criteria:**
- Called from the governed nomination path: returns `EO-YYYY-NNN` with correct year and zero-padded sequence
- Called from any other path: raises an error before any database call is made
- With zero existing plays in the current year, generates `EO-{YYYY}-001`
- With one existing play in the current year, generates `EO-{YYYY}-002`
- Sequence resets at the calendar year boundary

**Required tests:** Unit test: governed path generates correct format; unit test: unauthorized path raises error; DB sequence test: second call generates `...-002`; year-boundary test

**Expected deliverable:** Play ID function added to `backend/oracle/identifier_manager.py` with governed-path restriction

---

### P1-WP3-T07 — Implement Identifier Validation Functions

| Field | Detail |
|---|---|
| **Task ID** | P1-WP3-T07 |
| **Parent WP** | WP-3: Identifier Lifecycle Manager |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Implement the five identifier validation functions. Each accepts a string and returns a boolean. No database queries — pure format validation against the defined regex patterns.

Functions per plan Section 2 WP-3:
- `is_valid_slate_run_id(value: str) -> bool` — matches `ORACLE-\d{8}-\d{3}`
- `is_valid_game_run_id(value: str) -> bool` — matches `ORACLE-\d{8}-\d{3}-.+`
- `is_valid_evaluation_id(value: str) -> bool` — matches `EVAL-ORACLE-\d{8}-\d{3}-.+-v\d+`
- `is_valid_candidate_id(value: str) -> bool` — matches `CAND-ORACLE-\d{8}-\d{3}-.+`
- `is_valid_play_id(value: str) -> bool` — matches `EO-\d{4}-\d{3}`

**Dependencies:** P1-WP3-T02 through T06 (all generators implemented in same module)

**Repository areas affected:** `backend/oracle/identifier_manager.py`

**Acceptance criteria:**
- Each valid format returns `True`
- Empty string returns `False` for all five functions
- Swapped prefix (e.g., `CAND-` fed to Slate Run ID validator) returns `False`
- Malformed sequence suffix (e.g., `ORACLE-20260720-01` — only 2 digits) returns `False`

**Required tests:** One positive and two negative test cases per function (10 tests minimum)

**Expected deliverable:** Five validation functions added to `backend/oracle/identifier_manager.py`

---

### P1-WP3-T08 — Identifier Manager Full Test Suite

| Field | Detail |
|---|---|
| **Task ID** | P1-WP3-T08 |
| **Parent WP** | WP-3: Identifier Lifecycle Manager |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Execute the complete WP-3 test suite and confirm all acceptance criteria pass. This is the WP-3 gate. Includes both the unit tests written during T02–T07 and any integration tests requiring a live database connection (sequence generation tests).

Tests per plan Section 6.3:
1. Slate Run ID format correct with fixed date injection
2. Slate Run ID sequence increments correctly on same-day second call
3. Evaluation ID includes correct market and version
4. Play ID generates only from governed nomination path (unauthorized path raises error)
5. All five validation functions reject malformed identifiers

**Dependencies:** P1-WP3-T07 (all identifier functions implemented)

**Repository areas affected:** `backend/tests/` or `backend/oracle/tests/` (test files)

**Acceptance criteria:**
- All tests in the WP-3 test suite pass
- Sequence tests require the live database and pass against it
- No test relies on system clock for date — fixed date injection used throughout

**Required tests:** As enumerated in plan Section 6.3; sequence and sequence-increment tests require live database

**Expected deliverable:** Passing WP-3 test suite; written gate evidence for PM

---

## WP-4: RUN ORCHESTRATOR CORE

**Work Package Purpose:** Implement the Run Orchestrator skeleton — the state machines, kill switch, stage triggers (all as stubs in Phase 1), and fixture data injection interface.

**Repo area:** `backend/oracle/`

**WP-4 dependency:** WP-2 and WP-3 complete. Within WP-4/WP-5 parallel execution: T01–T04 may proceed in parallel with WP-5 T01–T02; T05 onward requires WP-5-T02 (Event Store write function).

**Execution order:** Parallel with WP-5 after WP-2 and WP-3.

---

### P1-WP4-T01 — Implement Kill Switch Reader

| Field | Detail |
|---|---|
| **Task ID** | P1-WP4-T01 |
| **Parent WP** | WP-4: Run Orchestrator Core |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Implement the kill switch reader module within the `backend/oracle/` package. The kill switch reads the `ORACLE_AUTONOMOUS_RUN_ENABLED` environment variable and returns a boolean. The Orchestrator calls this function at startup and before each stage trigger.

Behavior per plan Section 5.2:
- Variable absent or set to any value other than a recognized truthy string: returns `False` (kill switch active — halt)
- Variable set to a recognized truthy value: returns `True` (kill switch inactive — proceed)
- The kill switch never deletes records, rolls back stages, or corrupts state — it is a clean stop gate

**Dependencies:** P1-WP3-T01 (package scaffold exists)

**Repository areas affected:** `backend/oracle/kill_switch.py` (new file)

**Acceptance criteria:**
- Returns `False` when `ORACLE_AUTONOMOUS_RUN_ENABLED` is absent from environment
- Returns `False` when `ORACLE_AUTONOMOUS_RUN_ENABLED` is set to `"false"`, `"0"`, or `""`
- Returns `True` when `ORACLE_AUTONOMOUS_RUN_ENABLED` is set to `"true"` or `"1"`
- Function is pure: no side effects, no database calls, no logging

**Required tests:** Unit tests for each case above (4 tests minimum)

**Expected deliverable:** `backend/oracle/kill_switch.py`

---

### P1-WP4-T02 — Implement Slate-Level State Machine

| Field | Detail |
|---|---|
| **Task ID** | P1-WP4-T02 |
| **Parent WP** | WP-4: Run Orchestrator Core |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Implement the slate-level state machine as defined in architecture Section 10.1 and the plan WP-4 specification. The state machine must be implemented as an explicit allowlist of valid transitions; any transition not in the allowlist raises an error immediately — no silent no-ops.

10 slate states: `initializing | schedule_loaded | analysis_in_progress | activation_window_open | pregame_locked | settled | partial_void | analysis_failed | activation_failed | settlement_pending_retry`

Valid transitions per plan:
- `initializing` → `schedule_loaded` | `analysis_failed`
- `schedule_loaded` → `analysis_in_progress`
- `analysis_in_progress` → `activation_window_open` | `analysis_failed`
- `activation_window_open` → `pregame_locked` | `activation_failed`
- `pregame_locked` → `settled` | `partial_void`
- `partial_void` → `settled`
- `settlement_pending_retry` → `settled`
- `settled`, `analysis_failed`, `activation_failed`: terminal — no outbound transitions

**Dependencies:** P1-WP4-T01 (same package)

**Repository areas affected:** `backend/oracle/state_machines.py` (new file)

**Acceptance criteria:**
- All valid transitions succeed and return the new state
- Invalid transitions (e.g., `initializing → settled`) raise an error with a descriptive message
- Terminal states (`settled`, `analysis_failed`, `activation_failed`) raise errors on any attempted outbound transition
- State machine is stateless: it validates a transition from current → next and returns the result; it does not store state internally

**Required tests:** One positive test per defined valid transition (at minimum 8 tests); two negative tests per terminal state; two tests for arbitrary invalid transitions

**Expected deliverable:** Slate-level state machine in `backend/oracle/state_machines.py`

---

### P1-WP4-T03 — Implement Game-Level State Machine

| Field | Detail |
|---|---|
| **Task ID** | P1-WP4-T03 |
| **Parent WP** | WP-4: Run Orchestrator Core |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Implement the game-level state machine as defined in architecture Section 10.2 and the plan WP-4 specification. Same design principle as the slate-level machine: explicit allowlist, errors on invalid transitions.

9 game states: `scheduled | preliminary_analysis | lineup_monitoring | final_analysis | activation_eligible | pregame_locked | settled | voided | postponed`

Valid transitions per plan:
- `scheduled` → `preliminary_analysis`
- `preliminary_analysis` → `lineup_monitoring`
- `lineup_monitoring` → `final_analysis`
- `final_analysis` → `activation_eligible`
- `activation_eligible` → `pregame_locked`
- `pregame_locked` → `settled` | `voided` | `postponed`
- `settled`, `voided`, `postponed`: terminal

**Dependencies:** P1-WP4-T02 (same module)

**Repository areas affected:** `backend/oracle/state_machines.py`

**Acceptance criteria:**
- All valid transitions succeed
- Invalid transitions raise errors
- Terminal states raise errors on attempted outbound transitions
- Stateless implementation (same principle as slate-level machine)

**Required tests:** Positive test per valid transition; negative tests for terminal states and invalid transitions

**Expected deliverable:** Game-level state machine added to `backend/oracle/state_machines.py`

---

### P1-WP4-T04 — Implement Fixture Data Injection Interface

| Field | Detail |
|---|---|
| **Task ID** | P1-WP4-T04 |
| **Parent WP** | WP-4: Run Orchestrator Core |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Implement the fixture loader that Stage 2 of the Orchestrator calls instead of a live provider. This is the Phase 1-only substitute for the ScheduleProvider adapter, which will be built in Phase 2.

The fixture loader must return schedule data in the same shape that the future ScheduleProvider will return, so that Phase 2 can replace the fixture call with a live call without modifying the Orchestrator's Stage 2 logic.

Fixture data shape (matching future ScheduleProvider contract): a list of game records, each containing at minimum: `external_game_id` (a `gamePk`-format string — numeric, e.g., `"746484"`), `home_team` (team abbreviation), `away_team` (team abbreviation), `first_pitch_time` (UTC ISO-8601 datetime string), `venue` (stadium name string).

The fixture loader returns a pre-defined list of two or more game records matching this shape. The `gamePk` values in the fixture must be valid numeric strings in the format the MLB Stats API uses (will be confirmed in Phase 2, but the strings must be numeric).

**Dependencies:** P1-WP4-T01 (package scaffold)

**Repository areas affected:** `backend/oracle/fixtures.py` (new file) or equivalent

**Acceptance criteria:**
- Loader returns a list of at least two game records
- Each record contains `external_game_id`, `home_team`, `away_team`, `first_pitch_time`, `venue`
- `external_game_id` values are numeric strings
- `first_pitch_time` values are valid UTC datetime strings
- Shape is identical to what the ScheduleProvider contract will require (documented in fixture file)

**Required tests:** Unit test: loader returns list of dicts; unit test: each dict has all required keys; unit test: `external_game_id` values are numeric strings

**Expected deliverable:** `backend/oracle/fixtures.py`

---

### P1-WP4-T05 — Implement Orchestrator Stage 1: Slate Initialization

| Field | Detail |
|---|---|
| **Task ID** | P1-WP4-T05 |
| **Parent WP** | WP-4: Run Orchestrator Core |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Implement Stage 1 of the Run Orchestrator. This is the first stage that executes in a daily run.

Stage 1 sequence:
1. Check kill switch — if inactive (`ORACLE_AUTONOMOUS_RUN_ENABLED` false or absent), halt immediately; log kill switch state; exit; no records written
2. If kill switch active: call Identifier Manager to generate today's Slate Run ID
3. Insert record into `oracle_slate_runs` with status `initializing`, `daily_plays_activated = 0`, `run_started_at = now() (UTC)`
4. Write `slate_initialized` event to Event Store
5. Transition slate status to `schedule_loaded` via state machine (Stage 2 will follow)

**Dependencies:** P1-WP4-T01 (kill switch reader); P1-WP4-T02 (slate-level state machine); P1-WP3-T02 (Slate Run ID generator); P1-WP5-T02 (Event Store write function — required before events can be written)

**Repository areas affected:** `backend/oracle/orchestrator.py` (new file)

**Acceptance criteria:**
- Kill switch inactive: no database record written; Orchestrator exits cleanly
- Kill switch active: `oracle_slate_runs` record created with correct Slate Run ID format
- `run_status` in created record is `initializing` at record creation
- `slate_initialized` event appears in `oracle_play_events` after Stage 1
- `run_started_at` is a valid UTC timestamp
- `daily_plays_activated = 0` in created record

**Required tests:** Integration test: kill switch OFF → no record created; integration test: kill switch ON → record created with correct format and `slate_initialized` event written

**Expected deliverable:** Stage 1 implementation in `backend/oracle/orchestrator.py`

---

### P1-WP4-T06 — Implement Orchestrator Stage 2: Schedule Retrieval (Fixture-Based)

| Field | Detail |
|---|---|
| **Task ID** | P1-WP4-T06 |
| **Parent WP** | WP-4: Run Orchestrator Core |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Implement Stage 2 of the Run Orchestrator. Stage 2 loads the slate's game data and creates per-game analysis records.

Stage 2 sequence:
1. Check kill switch — halt if inactive
2. Call fixture loader (P1-WP4-T04) to retrieve game data — no live provider call
3. For each game in fixture data: call Identifier Manager to generate a Game Analysis Run ID; insert record into `oracle_game_analyses` with `external_game_id` from fixture's `gamePk` value, `game_status = scheduled`, and all other available fixture fields
4. Write `schedule_retrieved` event to Event Store
5. Write `game_analysis_started` event for each game to Event Store
6. Transition slate status from `schedule_loaded` to `analysis_in_progress` via state machine

**Dependencies:** P1-WP4-T05 (Stage 1 implemented; `oracle_slate_runs` record must exist before Stage 2 runs); P1-WP4-T04 (fixture loader); P1-WP3-T03 (Game Analysis Run ID generator); P1-WP5-T02 (Event Store write function)

**Repository areas affected:** `backend/oracle/orchestrator.py`

**Acceptance criteria:**
- Kill switch inactive: Stage 2 halts; no game records created
- Kill switch active: one `oracle_game_analyses` record created per fixture game
- Each record's `external_game_id` matches the fixture's `gamePk` value exactly
- Each record's `game_run_id` matches format `{slate_run_id}-{game_identifier}`
- `schedule_retrieved` event present in `oracle_play_events`
- `game_analysis_started` event present once per game in `oracle_play_events`
- No live MLB Stats API call made at any point

**Required tests:** Integration test: run Stage 2 with fixture containing two games → two records in `oracle_game_analyses` with correct `external_game_id` values; event presence test

**Expected deliverable:** Stage 2 implementation added to `backend/oracle/orchestrator.py`

---

### P1-WP4-T07 — Implement Orchestrator Stages 3–10 Stubs

| Field | Detail |
|---|---|
| **Task ID** | P1-WP4-T07 |
| **Parent WP** | WP-4: Run Orchestrator Core |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Implement Stages 3 through 10 as stubs. Each stub: (1) checks the kill switch; (2) logs the stage invocation; (3) writes the appropriate event type(s) to the Event Store; (4) transitions the relevant state machine; (5) returns without calling any provider, engine, or LLM.

Stage stubs and their events:
- Stage 3 (Preliminary Data Gather): writes `game_analysis_started` per game (if not already written); stub logs that data gather is deferred to Phase 2
- Stage 4 (ECF Calculation): writes `ecf_calculated` per game; stub notes ECF engine deferred to Phase 3
- Stage 5 (Intelligence Pipeline): writes `phie_completed`, `gse_completed`, `mve_completed`, `ce_completed`, `odg_completed`, `srl_completed` per game; stub notes all engines deferred to Phase 3
- Stage 6 (Lineup Monitoring): writes `lineup_observation_recorded` stub event; polling loop deferred to Phase 2
- Stage 7 (Final Analysis): writes stub events; recalculation deferred to Phase 3
- Stage 8 (Candidate Activation): writes stub events; activation logic deferred to Phase 4; enforces kill switch before activation gate
- Stage 9 (Pregame Lock): writes `play_locked` stub; lock logic deferred to Phase 4
- Stage 10 (Settlement): writes `settlement_completed` stub; settlement logic deferred to Phase 5

**Dependencies:** P1-WP4-T06 (Stage 2 implemented); P1-WP5-T02 (Event Store write function)

**Repository areas affected:** `backend/oracle/orchestrator.py`

**Acceptance criteria:**
- Each stage stub completes without error when called in sequence after Stages 1–2
- Kill switch check is present at the start of each stage
- Appropriate event type is written to Event Store for each stage
- No provider is called; no engine is called; no LLM is called
- State machine transitions occur correctly for each stage

**Required tests:** Integration test: full Phase 1 run through all 10 stages completes without error; event presence test for all stage-level events; kill switch test: kill switch toggled off mid-run halts before next stage

**Expected deliverable:** Stages 3–10 stubs added to `backend/oracle/orchestrator.py`

---

### P1-WP4-T08 — Orchestrator Unit and Integration Tests

| Field | Detail |
|---|---|
| **Task ID** | P1-WP4-T08 |
| **Parent WP** | WP-4: Run Orchestrator Core |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Execute the complete WP-4 test suite. This is the WP-4 gate. Covers kill switch, state machine transitions, Stage 1–2 behavior, and the full stub pipeline run.

Tests per plan Section 6.4:
1. Kill switch OFF: Orchestrator exits before Stage 1; no records written
2. Kill switch ON: Stage 1 creates slate run record with correct ID format
3. Invalid slate-level state transition (e.g., `initializing → settled`) raises error
4. Invalid game-level state transition raises error
5. All valid state machine transitions accepted
6. Slate Run ID in created record matches `ORACLE-\d{8}-\d{3}` format
7. Stage 2 creates game analysis records with correct `external_game_id` from fixture
8. Full 10-stage stub run completes without error

**Dependencies:** P1-WP4-T07 (all 10 stages implemented)

**Repository areas affected:** `backend/tests/oracle/` or `backend/oracle/tests/` (test files)

**Acceptance criteria:**
- All eight tests pass
- No test relies on live external providers
- Tests are self-cleaning (seed records removed on teardown)

**Required tests:** As enumerated; integration tests require live PostgreSQL

**Expected deliverable:** Passing WP-4 test suite; written gate evidence for PM

---

## WP-5: EVENT STORE SERVICE

**Work Package Purpose:** Implement the application-layer service that is the sole path for writing events to `oracle_play_events`. No component writes directly to the events table.

**Repo area:** `backend/oracle/`

**WP-5 dependency:** WP-2 (immutability trigger must be in place) and WP-3 complete (P1-WP3-T08 passed).

**Execution order:** Parallel with WP-4 after WP-2 and WP-3. WP-5-T01 and T02 may be built concurrently with WP-4-T01 through T04.

---

### P1-WP5-T01 — Implement Event Type Registry

| Field | Detail |
|---|---|
| **Task ID** | P1-WP5-T01 |
| **Parent WP** | WP-5: Event Store Service |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Implement the event type registry as an enumeration, constant set, or equivalent structure that enumerates all 27 valid Oracle event types. This is the authoritative list; the Event Store service validates against it before any database call.

27 event types per architecture Section 13.2:
`slate_initialized`, `schedule_retrieved`, `game_analysis_started`, `ecf_calculated`, `phie_completed`, `gse_completed`, `mve_completed`, `ce_completed`, `odg_completed`, `srl_completed`, `candidate_created`, `candidate_reentered`, `evaluation_version_created`, `recalculation_triggered`, `lineup_observation_recorded`, `lineup_confirmed`, `lineup_change_detected`, `play_id_assigned`, `play_activated`, `play_locked`, `conditional_play_nominated`, `conditional_resolved`, `conditional_expired`, `settlement_completed`, `settlement_manual_required`, `le_milestone_detected`, `le_report_stored`, `immutability_violation_rejected`

**Dependencies:** P1-WP3-T01 (package scaffold)

**Repository areas affected:** `backend/oracle/event_store.py` (new file)

**Acceptance criteria:**
- All 27 event types present in the registry
- Membership check works: `"slate_initialized"` is in the registry; `"unknown_event"` is not
- Registry is not modifiable at runtime (use an immutable type if the language permits)

**Required tests:** Unit test: all 27 types present; unit test: unknown type not present; unit test: registry cannot be modified at runtime (if applicable)

**Expected deliverable:** Event type registry in `backend/oracle/event_store.py`

---

### P1-WP5-T02 — Implement Event Store Write Function

| Field | Detail |
|---|---|
| **Task ID** | P1-WP5-T02 |
| **Parent WP** | WP-5: Event Store Service |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Implement the `record_event()` function per the plan Section 2 WP-5 service contract (updated per DCR-W5-001):

`record_event(conn, event_type, slate_run_id, event_timestamp, game_run_id=None, play_id=None, payload=None) -> event_id`

Behavior:
- `conn` is a caller-supplied psycopg2 connection with autocommit disabled; the Event Store creates and closes cursors only — it does not commit, roll back, or close the caller's connection
- Transaction ownership: caller; WP-4 Stage 1 combines Slate Run ID generation, `oracle_slate_runs` INSERT, and `slate_initialized` event INSERT within one atomic transaction using this model (see DCR-W5-001 §10)
- Validates `event_type` against the 27-type registry; raises `ValueError` if unknown (before any database call)
- Validates `slate_run_id` format using the Identifier Manager's `is_valid_slate_run_id()`; raises `ValueError` if invalid
- Performs INSERT into `oracle_play_events` with the provided fields; `event_id` is auto-assigned by the database (BIGSERIAL)
- Returns the `event_id` assigned by the database
- Does NOT perform UPDATE or DELETE — no such code paths exist in this function or module

This function is the only path through which Oracle events reach `oracle_play_events`.

**Dependencies:** P1-WP5-T01 (event type registry); P1-WP3-T07 (identifier validation functions); WP-2 complete (trigger enforces append-only at database layer as a backstop)

**Repository areas affected:** `backend/oracle/event_store.py`

**Acceptance criteria:**
- All 27 event types accepted; `record_event` completes and returns an `event_id`
- Unknown event type raises `ValueError` before database call
- Invalid `slate_run_id` format raises `ValueError` before database call
- Returned `event_id` is a positive integer matching the database-assigned value
- No UPDATE or DELETE statements exist anywhere in `event_store.py`

**Required tests:** Unit test: 27 event types each accepted; unit test: unknown type raises ValueError; unit test: invalid slate_run_id raises ValueError; integration test: event written to database; integration test: returned event_id matches database record

**Expected deliverable:** `record_event()` function in `backend/oracle/event_store.py`

---

### P1-WP5-T03 — Event Store Unit Tests

| Field | Detail |
|---|---|
| **Task ID** | P1-WP5-T03 |
| **Parent WP** | WP-5: Event Store Service |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Execute the unit test portion of the WP-5 test suite. Unit tests cover validation logic without requiring database access. These tests can run without a live PostgreSQL instance.

Tests per plan Section 6.5:
1. All 27 event types individually accepted (raises no `ValueError` — validation check only, before any cursor operation)
2. Unknown event type (`"invented_event_type"`) raises `ValueError` before any database call
3. Malformed `slate_run_id` (e.g., `"ORACLE-2026-1"`) raises `ValueError` before any database call
4. Static code inspection confirms no UPDATE or DELETE statements in `event_store.py`

**Connection requirement for unit tests (DCR-W5-001 §12):** Tests 1–3 call `record_event()` with a lightweight mock connection object, consistent with the WP-3 unit test pattern (`_MockCursor` / mock connection in `test_oracle_identifier_manager.py`). No live database is accessed; `ValueError` is raised before any cursor operation. No `ORACLE_TEST_DATABASE_URL` required for these tests.

**Dependencies:** P1-WP5-T02

**Repository areas affected:** `backend/tests/oracle/` (test file)

**Acceptance criteria:**
- All four test categories pass
- No database connection required for tests 1–3
- Test 4 is a code review / static check, not a runtime test

**Required tests:** As enumerated

**Expected deliverable:** Unit test file for Event Store; passing results

---

### P1-WP5-T04 — Event Store Integration Tests

| Field | Detail |
|---|---|
| **Task ID** | P1-WP5-T04 |
| **Parent WP** | WP-5: Event Store Service |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Execute the integration test portion of the WP-5 test suite. Requires a live PostgreSQL connection with the schema applied (WP-1) and the immutability trigger active (WP-2). These tests verify that events are correctly written to `oracle_play_events` and are retrievable in insertion order.

Tests per plan Section 6.5:
1. Three events inserted via `record_event()`; query retrieves them in `event_timestamp` order
2. Returned `event_id` from each call matches the `event_id` in the database record
3. Database trigger does not fire on INSERT (confirming trigger only blocks UPDATE/DELETE)

**Dependencies:** P1-WP5-T03 (unit tests pass); WP-2 complete (trigger in place); WP-1 complete (schema in place)

**Repository areas affected:** `backend/tests/oracle/` (test file)

**Acceptance criteria:**
- Three-event retrieval-order test passes
- `event_id` round-trip test passes
- INSERT does not trigger the immutability violation handler

**Required tests:** Requires live PostgreSQL; tests self-clean (inserted test records removed on teardown)

**Expected deliverable:** Integration test file for Event Store; passing results; written WP-5 gate evidence

---

## WP-6: PHASE 1 INTEGRATION VERIFICATION

**Work Package Purpose:** End-to-end verification that all Phase 1 deliverables together satisfy the five Phase 1 exit criteria. This work package builds nothing — it verifies what was built.

**Repo area:** `backend/tests/oracle/`

**WP-6 dependency:** All of WP-1, WP-2, WP-3, WP-4, and WP-5 individually gate-complete.

**Execution order:** Last; nothing in WP-6 is parallel with other work.

---

### P1-WP6-T01 — Create Test Directory Scaffold and Phase 1 Fixture Definitions

| Field | Detail |
|---|---|
| **Task ID** | P1-WP6-T01 |
| **Parent WP** | WP-6: Phase 1 Integration Verification |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Create the `backend/tests/oracle/` directory (if it does not already exist from WP-3 or WP-4 test work) and establish the Phase 1 integration fixture definitions used across all five EC tests. The fixture defines at minimum two games with:
- `external_game_id`: valid numeric `gamePk`-format strings (e.g., `"746484"`, `"746485"`)
- `home_team` and `away_team`: valid MLB team abbreviations (e.g., `"BOS"`, `"NYY"`)
- `first_pitch_time`: valid UTC datetime strings (e.g., `"2026-07-20T17:10:00Z"`)
- `venue`: stadium name string

This fixture is the canonical Phase 1 schedule fixture. All WP-6 tests that require game records use this fixture.

**Dependencies:** All WP-1 through WP-5 gate-complete

**Repository areas affected:** `backend/tests/oracle/` (directory and fixture file)

**Acceptance criteria:**
- `backend/tests/oracle/` directory exists and contains `__init__.py`
- Fixture file defines at least two games with all required fields
- All `external_game_id` values are numeric strings
- Fixture shape matches the ScheduleProvider contract shape (from WP-4-T04)

**Required tests:** Unit test: fixture loads without error; unit test: each game has all required keys

**Expected deliverable:** `backend/tests/oracle/__init__.py`; fixture definition file or fixture function

---

### P1-WP6-T02 — EC-1 Test: Slate Run ID Format

| Field | Detail |
|---|---|
| **Task ID** | P1-WP6-T02 |
| **Parent WP** | WP-6: Phase 1 Integration Verification |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Implement and execute the integration test for Phase 1 Exit Criterion 1: the Run Orchestrator creates a slate run record with a correctly formatted Slate Run ID.

Test sequence:
1. Set `ORACLE_AUTONOMOUS_RUN_ENABLED = "true"`
2. Invoke the Orchestrator (Stage 1)
3. Query `oracle_slate_runs` for the most recently created record
4. Assert `slate_run_id` matches the regex `ORACLE-\d{8}-\d{3}`
5. Assert `run_status` is not null
6. Teardown: delete the test record

**Dependencies:** P1-WP6-T01

**Repository areas affected:** `backend/tests/oracle/` (test file)

**Acceptance criteria:**
- Test passes: created record has `slate_run_id` matching `ORACLE-YYYYMMDD-NNN` format
- Test is idempotent (run twice produces consistent results)
- Test self-cleans

**Required tests:** Integration test against live database

**Expected deliverable:** Passing EC-1 test in `backend/tests/oracle/`

---

### P1-WP6-T03 — EC-2 Test: Fixture Game Records with `gamePk` as `external_game_id`

| Field | Detail |
|---|---|
| **Task ID** | P1-WP6-T03 |
| **Parent WP** | WP-6: Phase 1 Integration Verification |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Implement and execute the integration test for Phase 1 Exit Criterion 2: game analysis records are created from fixture data with `gamePk`-formatted values as canonical `external_game_id`; no live provider call is made.

Test sequence:
1. Set `ORACLE_AUTONOMOUS_RUN_ENABLED = "true"`
2. Invoke the Orchestrator through Stage 2 using the Phase 1 fixture
3. Query `oracle_game_analyses` for records created in this run
4. Assert one record per fixture game exists
5. Assert each record's `external_game_id` matches the fixture's `gamePk` value exactly
6. Assert no live network call was made to any external host (may be verified via test isolation or network mock if available)
7. Teardown: delete test records

**Dependencies:** P1-WP6-T02 (EC-1 passed; Orchestrator produces valid slate run records)

**Repository areas affected:** `backend/tests/oracle/` (test file)

**Acceptance criteria:**
- One `oracle_game_analyses` record per fixture game
- Each `external_game_id` matches fixture `gamePk` exactly
- No live provider call made
- Test is idempotent and self-cleaning

**Required tests:** Integration test against live database

**Expected deliverable:** Passing EC-2 test in `backend/tests/oracle/`

---

### P1-WP6-T04 — EC-3 Test: Immutability Violations Raise Exceptions and Write Audit Records

| Field | Detail |
|---|---|
| **Task ID** | P1-WP6-T04 |
| **Parent WP** | WP-6: Phase 1 Integration Verification |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Implement and execute the integration test for Phase 1 Exit Criterion 3: UPDATE and DELETE on `oracle_play_events` raise exceptions and write to `oracle_immutability_audit`.

Test sequence:
1. Insert a test event record into `oracle_play_events` via the Event Store service (using a valid `slate_run_id` from a seed slate run)
2. Attempt direct UPDATE on the inserted record; assert EXCEPTION raised; assert no change to the record
3. Query `oracle_immutability_audit`; assert one new record with `violation_type = 'UPDATE'`
4. Attempt direct DELETE on the inserted record; assert EXCEPTION raised; assert record still exists
5. Query `oracle_immutability_audit`; assert one new record with `violation_type = 'DELETE'`
6. Teardown: cannot DELETE the event record (trigger blocks it); teardown must use the immutability-safe approach — this means the test environment needs a plan for teardown (either truncation in a test schema or a separate teardown mechanism agreed with PM)

**Dependencies:** P1-WP6-T01; WP-2 complete (trigger in place)

**Repository areas affected:** `backend/tests/oracle/` (test file)

**Acceptance criteria:**
- UPDATE attempt raises EXCEPTION
- DELETE attempt raises EXCEPTION
- Each violation writes exactly one audit record
- Event record remains intact after both violation attempts

**Required tests:** Integration test against live database; cannot be mocked

**Expected deliverable:** Passing EC-3 test in `backend/tests/oracle/`

---

### P1-WP6-T05 — EC-4 Test: Kill Switch Halts All Stage Triggers

| Field | Detail |
|---|---|
| **Task ID** | P1-WP6-T05 |
| **Parent WP** | WP-6: Phase 1 Integration Verification |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Implement and execute the integration test for Phase 1 Exit Criterion 4: when `ORACLE_AUTONOMOUS_RUN_ENABLED` is false or absent, all stage triggers halt and no Oracle records are created.

Test sequence:
1. Record current count of records in `oracle_slate_runs`
2. Set `ORACLE_AUTONOMOUS_RUN_ENABLED = "false"` (or unset it entirely)
3. Invoke the Orchestrator
4. Assert no new records were added to `oracle_slate_runs` (count unchanged)
5. Assert no new records were added to `oracle_game_analyses`
6. Assert no new records were added to `oracle_play_events`
7. Verify that database read queries (e.g., SELECT on `oracle_slate_runs`) still succeed — read API not affected

**Dependencies:** P1-WP6-T01

**Repository areas affected:** `backend/tests/oracle/` (test file)

**Acceptance criteria:**
- No records written to any Oracle table when kill switch is inactive
- Read queries continue to succeed
- Test passes for both `"false"` and absent (unset) variable states

**Required tests:** Integration test against live database; two sub-cases (value `"false"` and variable absent)

**Expected deliverable:** Passing EC-4 test in `backend/tests/oracle/`

---

### P1-WP6-T06 — EC-5 Test: `daily_plays_activated` Cap Enforced at Database Level

| Field | Detail |
|---|---|
| **Task ID** | P1-WP6-T06 |
| **Parent WP** | WP-6: Phase 1 Integration Verification |
| **Status** | Not Started |
| **Complexity** | S |

**Description:** Implement and execute the integration test for Phase 1 Exit Criterion 5: the database-level CHECK constraint prevents `daily_plays_activated` from exceeding 3.

Test sequence:
1. Insert a test `oracle_slate_runs` record with `daily_plays_activated = 3`
2. Attempt to UPDATE the record to set `daily_plays_activated = 4`
3. Assert that a CHECK constraint violation is raised
4. Query the record; assert `daily_plays_activated` is still 3 (no partial update)
5. Teardown: DELETE the test record (this is a `slate_runs` record, not an `oracle_play_events` record — DELETE is permitted)

**Dependencies:** P1-WP6-T01

**Repository areas affected:** `backend/tests/oracle/` (test file)

**Acceptance criteria:**
- INSERT with `daily_plays_activated = 3` succeeds
- UPDATE to `daily_plays_activated = 4` raises constraint violation
- Record retains `daily_plays_activated = 3` after violation
- Test is idempotent and self-cleaning

**Required tests:** Integration test against live database

**Expected deliverable:** Passing EC-6 test in `backend/tests/oracle/`

---

### P1-WP6-T07 — Full Phase 1 Integration Verification Run

| Field | Detail |
|---|---|
| **Task ID** | P1-WP6-T07 |
| **Parent WP** | WP-6: Phase 1 Integration Verification |
| **Status** | Not Started |
| **Complexity** | M |

**Description:** Execute all five EC tests (T02–T06) in sequence as a complete Phase 1 verification run. This is the Phase 1 exit gate. All five must pass without manual intervention in a single run.

Additionally verify:
- All tests are idempotent: run the entire suite twice; results are identical on both runs
- All tests self-clean: after the second run, the database contains no residual test records from either run
- No test makes a live call to any external provider

Document the results as the formal Phase 1 completion evidence for PM review.

**Dependencies:** P1-WP6-T02, P1-WP6-T03, P1-WP6-T04, P1-WP6-T05, P1-WP6-T06 (all five EC tests individually passing)

**Repository areas affected:** `backend/tests/oracle/` (full suite run)

**Acceptance criteria:**
- EC-1 passes: Slate Run ID format `ORACLE-YYYYMMDD-NNN` confirmed
- EC-2 passes: Game records created from fixture with correct `external_game_id`; no live provider call
- EC-3 passes: UPDATE and DELETE raise exceptions; audit records written
- EC-4 passes: Kill switch halts all stage triggers
- EC-5 passes: `daily_plays_activated > 3` rejected at database level
- Suite is idempotent on two consecutive runs
- Suite self-cleans

**Required tests:** Full integration suite run against live PostgreSQL

**Expected deliverable:** Written Phase 1 exit verification report (all five exit criteria, pass/fail result for each, confirmation of idempotency and self-cleaning); delivered to PM as formal Phase 1 completion evidence

---

## BACKLOG SUMMARY

### Task Count by Work Package

| Work Package | Tasks | Complexity Profile |
|---|---|---|
| WP-1: Oracle Database Schema | 8 (T01–T08) | S, S, M, M, M, M, S, M |
| WP-2: Immutability Enforcement | 3 (T01–T03) | M, S, M |
| WP-3: Identifier Lifecycle Manager | 8 (T01–T08) | S, M, S, S, S, M, S, M |
| WP-4: Run Orchestrator Core | 8 (T01–T08) | S, M, M, S, M, M, M, M |
| WP-5: Event Store Service | 4 (T01–T04) | S, M, M, S |
| WP-6: Phase 1 Integration Verification | 7 (T01–T07) | S, S, S, S, S, S, M |
| **Total** | **38** | |

### Critical Path

```
PRE-GATE
  └─ P1-WP1-T01 Verify PostgreSQL + no naming conflicts
  └─ P1-WP1-T02 Migration naming convention

WP-1 (must complete before WP-2 or WP-3 begin)
  P1-WP1-T03 → T04 → T05 → T06 → T07 → T08

  ┌─────────────────────────────────────────┐
  │ WP-2 (parallel with WP-3)               │
  │ T01 Trigger migration                   │
  │ T02 Trigger rollback                    │
  │ T03 Immutability tests (gate)           │
  └─────────────────────────────────────────┘
         ∥
  ┌─────────────────────────────────────────┐
  │ WP-3 (parallel with WP-2)               │
  │ T01 Package scaffold                    │
  │ T02 Slate Run ID generator              │
  │ T03 Game Analysis Run ID generator      │
  │ T04 Evaluation ID generator             │
  │ T05 Candidate ID generator              │
  │ T06 Play ID generator (governed-path)   │
  │ T07 Validation functions                │
  │ T08 Identifier Manager tests (gate)     │
  └─────────────────────────────────────────┘

  ┌─────────────────────────────────────────┐
  │ WP-4/WP-5 parallel window               │
  │                                         │
  │ WP-4-T01 Kill switch reader  ─┐         │
  │ WP-4-T02 Slate state machine  ├ parallel│
  │ WP-4-T03 Game state machine   │ with    │
  │ WP-4-T04 Fixture loader      ─┘ WP-5   │
  │                                T01-T02  │
  │ WP-5-T01 Event type registry  ─┐        │
  │ WP-5-T02 Write function       ─┘        │
  │                                         │
  │ [WP-5-T02 complete unblocks WP-4-T05+] │
  │                                         │
  │ WP-4-T05 Stage 1                        │
  │ WP-4-T06 Stage 2                        │
  │ WP-4-T07 Stages 3-10 stubs             │
  │ WP-4-T08 Orchestrator tests (gate)      │
  │                                         │
  │ WP-5-T03 Event Store unit tests         │
  │ WP-5-T04 Event Store integration tests  │
  └─────────────────────────────────────────┘

WP-6 (all prior gates must be complete)
  T01 Test scaffold + fixture definitions
  T02 EC-1 test
  T03 EC-2 test
  T04 EC-3 test
  T05 EC-4 test
  T06 EC-5 test
  T07 Full Phase 1 verification run (exit gate)
```

### Traceability: Backlog Tasks → Plan Exit Criteria

| Exit Criterion | Implemented By | Verified By |
|---|---|---|
| EC-1: Slate Run ID format | P1-WP3-T02, P1-WP4-T05 | P1-WP6-T02, P1-WP6-T07 |
| EC-2: `external_game_id` from fixture | P1-WP4-T04, P1-WP4-T06 | P1-WP6-T03, P1-WP6-T07 |
| EC-3: Immutability violations logged | P1-WP2-T01 | P1-WP6-T04, P1-WP6-T07 |
| EC-4: Kill switch halts triggers | P1-WP4-T01, P1-WP4-T05 | P1-WP6-T05, P1-WP6-T07 |
| EC-5: Daily cap enforced at DB level | P1-WP1-T03 | P1-WP6-T06, P1-WP6-T07 |

### Traceability: Backlog Tasks → Architecture Sections

| Architecture Section | Backlog Tasks |
|---|---|
| Section 6 — Identifier Lifecycle | P1-WP3-T02 through T07 |
| Section 7.1 Stage 1 — Slate Initialization | P1-WP4-T05 |
| Section 7.1 Stage 2 — Schedule Retrieval | P1-WP4-T04, P1-WP4-T06 |
| Section 7.1 Stages 3–10 | P1-WP4-T07 |
| Section 10.1 — Slate-Level State Machine | P1-WP4-T02 |
| Section 10.2 — Game-Level State Machine | P1-WP4-T03 |
| Section 12 — Run Orchestrator | P1-WP4-T01 through T08 |
| Section 12.2 — Kill Switch | P1-WP4-T01 |
| Section 13.1 — Event Model Principles | P1-WP5-T01, P1-WP5-T02 |
| Section 13.2 — 27 Event Types | P1-WP5-T01 |
| Section 13.3 — Append-Only Trigger | P1-WP2-T01, P1-WP2-T02 |
| Section 13.4 — Immutability Audit Table | P1-WP1-T07, P1-WP2-T01 |
| Section 20.1 — Phase 1 Exit Criteria | P1-WP6-T02 through T07 |
| Section 21 — Phase 1 Scope | All WP-1 through WP-6 tasks |

---

*ORACLE PHASE 1 IMPLEMENTATION BACKLOG — Edge Oracle, MLB Betting Edge Project*
*Plan Reference: ORACLE_PHASE_1_IMPLEMENTATION_PLAN.md (Final)*
*Architecture Reference: ORACLE_INTELLIGENCE_ARCHITECTURE_v1_2.md (Final Candidate)*
*Status: Awaiting PM Authorization to Begin Implementation*
