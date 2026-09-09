"""Oracle Phase 1 WP-1 schema validation tests.

Requires ORACLE_TEST_DATABASE_URL pointing to a disposable PostgreSQL
database with Migration 005 applied.  All tests are skipped when the
variable is absent so the existing CI suite can run without a live database.

Covers:
  A. Schema existence and column definitions
  B. Primary key enforcement
  C. Foreign key enforcement
  D. CHECK constraint enforcement (including three-play maximum boundary)
  E. TIMESTAMPTZ storage and timezone preservation
  F. JSONB insertion, retrieval, and type confirmation
  G. BIGSERIAL automatic identifier generation
  K. Existing platform table protection
"""

import json
import os

import psycopg2
import psycopg2.errors
import pytest

_TEST_DB_URL = os.getenv("ORACLE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not _TEST_DB_URL,
    reason="ORACLE_TEST_DATABASE_URL not set — Oracle schema integration tests skipped",
)

ORACLE_TABLES = [
    "oracle_slate_runs",
    "oracle_game_analyses",
    "oracle_plays",
    "oracle_play_events",
    "oracle_immutability_audit",
    "oracle_preliminary_data",
    "oracle_lifecycle_audit",
    "oracle_ecf_results",
    # Inc-3 Stage 5 (migration 009)
    "oracle_stage5_results",
    "oracle_preliminary_outputs",
    "oracle_scheduled_cutoffs",
    "oracle_sport_policies",
    "oracle_sport_policy_active",
]

# Stage 5 (migration 009) tables — registered explicitly to prevent recurrence
# of the Stage 4 approved-table omission (PM-1007 §6).
STAGE5_TABLES = [
    "oracle_stage5_results",
    "oracle_preliminary_outputs",
    "oracle_scheduled_cutoffs",
    "oracle_sport_policies",
    "oracle_sport_policy_active",
]

_MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "database",
    "migrations",
)

PLATFORM_TABLES = [
    "teams",
    "games",
    "starting_pitchers",
    "odds_history",
    "team_records",
    "game_weather",
    "team_bullpen_context",
    "team_injuries",
]

_SLATE_RUN_ID = "ORACLE-20260101-001"
_GAME_RUN_ID = "ORACLE-20260101-001-TST-TST"
_PLAY_ID = "EO-2026-001"


@pytest.fixture(scope="module")
def conn():
    connection = psycopg2.connect(_TEST_DB_URL)
    connection.autocommit = True
    yield connection
    connection.close()


# ---------------------------------------------------------------------------
# A. Schema validation — all five tables exist with expected columns
# ---------------------------------------------------------------------------

def test_all_oracle_tables_exist(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = ANY(%s)
        """,
        (ORACLE_TABLES,),
    )
    found = {row[0] for row in cur.fetchall()}
    cur.close()
    assert found == set(ORACLE_TABLES), (
        f"Missing tables: {set(ORACLE_TABLES) - found}"
    )


def _get_columns(conn, table_name):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    rows = cur.fetchall()
    cur.close()
    return {row[0]: {"type": row[1], "nullable": row[2], "default": row[3]} for row in rows}


def test_oracle_slate_runs_columns(conn):
    cols = _get_columns(conn, "oracle_slate_runs")
    assert "slate_run_id" in cols
    assert cols["slate_run_id"]["type"] == "character varying"
    assert "run_date" in cols
    assert cols["run_date"]["nullable"] == "NO"
    assert "daily_plays_activated" in cols
    assert cols["daily_plays_activated"]["nullable"] == "NO"
    assert "run_started_at" in cols
    assert cols["run_started_at"]["type"] == "timestamp with time zone"
    assert cols["run_started_at"]["nullable"] == "NO"
    assert "run_completed_at" in cols
    assert cols["run_completed_at"]["type"] == "timestamp with time zone"
    assert cols["run_completed_at"]["nullable"] == "YES"
    assert "created_at" in cols
    assert cols["created_at"]["type"] == "timestamp with time zone"


def test_oracle_game_analyses_columns(conn):
    cols = _get_columns(conn, "oracle_game_analyses")
    assert "game_run_id" in cols
    assert cols["external_game_id"]["nullable"] == "NO"
    assert cols["home_team"]["nullable"] == "NO"
    assert cols["away_team"]["nullable"] == "NO"
    assert cols["first_pitch_time"]["type"] == "timestamp with time zone"
    assert cols["first_pitch_time"]["nullable"] == "NO"
    assert cols["venue"]["nullable"] == "YES"


def test_oracle_plays_columns(conn):
    cols = _get_columns(conn, "oracle_plays")
    assert "play_id" in cols
    assert cols["candidate_id"]["nullable"] == "NO"
    assert cols["slate_run_id"]["nullable"] == "NO"
    assert cols["game_run_id"]["nullable"] == "NO"
    assert cols["market"]["nullable"] == "NO"
    assert cols["selected_side"]["nullable"] == "NO"
    assert cols["odds_at_nomination"]["type"] == "integer"
    assert cols["odds_at_nomination"]["nullable"] == "NO"
    assert cols["nomination_timestamp"]["type"] == "timestamp with time zone"
    assert cols["nomination_timestamp"]["nullable"] == "NO"
    assert cols["pregame_locked_at"]["nullable"] == "YES"
    assert cols["settlement_result"]["nullable"] == "YES"
    assert cols["mock_pnl"]["nullable"] == "YES"
    assert cols["closing_odds"]["nullable"] == "YES"
    assert cols["clv"]["nullable"] == "YES"
    assert cols["settled_at"]["nullable"] == "YES"


def test_oracle_play_events_columns(conn):
    cols = _get_columns(conn, "oracle_play_events")
    assert "event_id" in cols
    assert cols["event_type"]["nullable"] == "NO"
    assert cols["slate_run_id"]["nullable"] == "NO"
    assert cols["game_run_id"]["nullable"] == "YES"
    assert cols["play_id"]["nullable"] == "YES"
    assert cols["event_timestamp"]["type"] == "timestamp with time zone"
    assert cols["event_timestamp"]["nullable"] == "NO"
    assert cols["event_payload"]["type"] == "jsonb"
    assert cols["event_payload"]["nullable"] == "YES"
    assert cols["recorded_at"]["type"] == "timestamp with time zone"


def test_oracle_immutability_audit_columns(conn):
    cols = _get_columns(conn, "oracle_immutability_audit")
    assert "audit_id" in cols
    assert cols["rejected_event_id"]["nullable"] == "YES"
    assert cols["violation_type"]["nullable"] == "NO"
    assert cols["rejected_at"]["type"] == "timestamp with time zone"
    assert cols["rejected_at"]["nullable"] == "NO"
    assert cols["attempted_by"]["nullable"] == "NO"
    assert cols["detail"]["nullable"] == "YES"


# ---------------------------------------------------------------------------
# B. Primary key validation
# ---------------------------------------------------------------------------

def _get_pk_columns(conn, table_name):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = 'public'
          AND tc.table_name = %s
        ORDER BY kcu.ordinal_position
        """,
        (table_name,),
    )
    rows = cur.fetchall()
    cur.close()
    return [row[0] for row in rows]


def test_oracle_slate_runs_primary_key(conn):
    assert _get_pk_columns(conn, "oracle_slate_runs") == ["slate_run_id"]


def test_oracle_game_analyses_primary_key(conn):
    assert _get_pk_columns(conn, "oracle_game_analyses") == ["game_run_id"]


def test_oracle_plays_primary_key(conn):
    assert _get_pk_columns(conn, "oracle_plays") == ["play_id"]


def test_oracle_play_events_primary_key(conn):
    assert _get_pk_columns(conn, "oracle_play_events") == ["event_id"]


def test_oracle_immutability_audit_primary_key(conn):
    assert _get_pk_columns(conn, "oracle_immutability_audit") == ["audit_id"]


# ---------------------------------------------------------------------------
# C. Foreign key validation
# ---------------------------------------------------------------------------

@pytest.fixture
def seed_slate_run(conn):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_slate_runs
            (slate_run_id, run_date, run_status, run_started_at)
        VALUES (%s, '2026-01-01', 'initializing', NOW())
        """,
        (_SLATE_RUN_ID,),
    )
    cur.close()
    yield _SLATE_RUN_ID
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM oracle_slate_runs WHERE slate_run_id = %s",
        (_SLATE_RUN_ID,),
    )
    cur.close()


@pytest.fixture
def seed_game_analysis(conn, seed_slate_run):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_game_analyses
            (game_run_id, slate_run_id, external_game_id, home_team, away_team, first_pitch_time)
        VALUES (%s, %s, '746484', 'BOS', 'NYY', '2026-01-01T18:00:00+00:00')
        """,
        (_GAME_RUN_ID, seed_slate_run),
    )
    cur.close()
    yield _GAME_RUN_ID
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM oracle_game_analyses WHERE game_run_id = %s",
        (_GAME_RUN_ID,),
    )
    cur.close()


def test_fk_game_analyses_to_slate_runs_valid(conn, seed_game_analysis):
    cur = conn.cursor()
    cur.execute(
        "SELECT game_run_id FROM oracle_game_analyses WHERE game_run_id = %s",
        (_GAME_RUN_ID,),
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None
    assert row[0] == _GAME_RUN_ID


def test_fk_game_analyses_to_slate_runs_invalid(conn):
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO oracle_game_analyses
                (game_run_id, slate_run_id, external_game_id, home_team, away_team, first_pitch_time)
            VALUES ('ORACLE-20260101-999-BAD-FK', 'ORACLE-99991231-999', '000000', 'AAA', 'BBB', NOW())
            """
        )
        cur.close()


def test_fk_plays_to_slate_runs_valid(conn, seed_game_analysis):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_plays
            (play_id, candidate_id, slate_run_id, game_run_id, market,
             selected_side, odds_at_nomination, nomination_timestamp)
        VALUES (%s, 'CAND-TST', %s, %s, 'ML', 'home', -140, NOW())
        """,
        (_PLAY_ID, _SLATE_RUN_ID, _GAME_RUN_ID),
    )
    cur.execute("SELECT play_id FROM oracle_plays WHERE play_id = %s", (_PLAY_ID,))
    row = cur.fetchone()
    cur.execute("DELETE FROM oracle_plays WHERE play_id = %s", (_PLAY_ID,))
    cur.close()
    assert row is not None
    assert row[0] == _PLAY_ID


def test_fk_plays_to_slate_runs_invalid(conn, seed_game_analysis):
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO oracle_plays
                (play_id, candidate_id, slate_run_id, game_run_id, market,
                 selected_side, odds_at_nomination, nomination_timestamp)
            VALUES ('EO-2026-BAD', 'CAND-TST', 'ORACLE-99991231-999', %s, 'ML', 'home', -140, NOW())
            """,
            (_GAME_RUN_ID,),
        )
        cur.close()


def test_fk_plays_to_game_analyses_invalid(conn, seed_slate_run):
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO oracle_plays
                (play_id, candidate_id, slate_run_id, game_run_id, market,
                 selected_side, odds_at_nomination, nomination_timestamp)
            VALUES ('EO-2026-BAD2', 'CAND-TST', %s, 'ORACLE-20260101-001-NO-GAME', 'ML', 'home', -140, NOW())
            """,
            (seed_slate_run,),
        )
        cur.close()


def test_fk_play_events_required_slate_run_invalid(conn):
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO oracle_play_events
                (event_type, slate_run_id, event_timestamp)
            VALUES ('slate_initialized', 'ORACLE-99991231-999', NOW())
            """
        )
        cur.close()


def test_fk_play_events_nullable_game_run_id_accepts_null(conn, seed_slate_run):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_play_events
            (event_type, slate_run_id, game_run_id, event_timestamp)
        VALUES ('slate_initialized', %s, NULL, NOW())
        RETURNING event_id
        """,
        (seed_slate_run,),
    )
    event_id = cur.fetchone()[0]
    # DELETE blocked by append-only trigger (WP-2); TRUNCATE bypasses row-level triggers.
    cur.execute("TRUNCATE oracle_play_events")
    cur.close()
    assert isinstance(event_id, int)


def test_fk_play_events_nullable_game_run_id_rejects_nonexistent(conn, seed_slate_run):
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO oracle_play_events
                (event_type, slate_run_id, game_run_id, event_timestamp)
            VALUES ('slate_initialized', %s, 'ORACLE-20260101-001-NO-GAME', NOW())
            """,
            (seed_slate_run,),
        )
        cur.close()


# ---------------------------------------------------------------------------
# D. CHECK constraint — three-play maximum boundary
# ---------------------------------------------------------------------------

def test_check_daily_plays_activated_lower_bound_zero(conn):
    run_id = "ORACLE-20260101-CHK"
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_slate_runs
            (slate_run_id, run_date, run_status, daily_plays_activated, run_started_at)
        VALUES (%s, '2026-01-01', 'initializing', 0, NOW())
        """,
        (run_id,),
    )
    cur.execute("SELECT daily_plays_activated FROM oracle_slate_runs WHERE slate_run_id = %s", (run_id,))
    val = cur.fetchone()[0]
    cur.execute("DELETE FROM oracle_slate_runs WHERE slate_run_id = %s", (run_id,))
    cur.close()
    assert val == 0


def test_check_daily_plays_activated_maximum_of_3(conn):
    run_id = "ORACLE-20260101-CK3"
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_slate_runs
            (slate_run_id, run_date, run_status, daily_plays_activated, run_started_at)
        VALUES (%s, '2026-01-01', 'initializing', 3, NOW())
        """,
        (run_id,),
    )
    cur.execute("SELECT daily_plays_activated FROM oracle_slate_runs WHERE slate_run_id = %s", (run_id,))
    val = cur.fetchone()[0]
    cur.execute("DELETE FROM oracle_slate_runs WHERE slate_run_id = %s", (run_id,))
    cur.close()
    assert val == 3


def test_check_daily_plays_activated_rejects_below_zero(conn):
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO oracle_slate_runs
                (slate_run_id, run_date, run_status, daily_plays_activated, run_started_at)
            VALUES ('ORACLE-20260101-CMI', '2026-01-01', 'initializing', -1, NOW())
            """
        )
        cur.close()


def test_check_daily_plays_activated_rejects_above_3(conn):
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO oracle_slate_runs
                (slate_run_id, run_date, run_status, daily_plays_activated, run_started_at)
            VALUES ('ORACLE-20260101-CMA', '2026-01-01', 'initializing', 4, NOW())
            """
        )
        cur.close()


# ---------------------------------------------------------------------------
# E. TIMESTAMPTZ — timezone-aware values preserved
# ---------------------------------------------------------------------------

def test_timestamptz_preserves_utc_value(conn):
    run_id = "ORACLE-20260101-TSZ"
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_slate_runs
            (slate_run_id, run_date, run_status, run_started_at)
        VALUES (%s, '2026-01-01', 'initializing', '2026-01-01T18:05:00+00:00')
        """,
        (run_id,),
    )
    cur.execute(
        "SELECT run_started_at AT TIME ZONE 'UTC' FROM oracle_slate_runs WHERE slate_run_id = %s",
        (run_id,),
    )
    stored = cur.fetchone()[0]
    cur.execute("DELETE FROM oracle_slate_runs WHERE slate_run_id = %s", (run_id,))
    cur.close()
    assert stored.hour == 18
    assert stored.minute == 5


def test_timestamptz_preserves_offset_aware_value(conn):
    run_id = "ORACLE-20260101-TZO"
    cur = conn.cursor()
    # Insert with +05:30 offset (IST); UTC equivalent is 12:30:00
    cur.execute(
        """
        INSERT INTO oracle_slate_runs
            (slate_run_id, run_date, run_status, run_started_at)
        VALUES (%s, '2026-01-01', 'initializing', '2026-01-01T18:00:00+05:30')
        """,
        (run_id,),
    )
    cur.execute(
        "SELECT run_started_at AT TIME ZONE 'UTC' FROM oracle_slate_runs WHERE slate_run_id = %s",
        (run_id,),
    )
    stored = cur.fetchone()[0]
    cur.execute("DELETE FROM oracle_slate_runs WHERE slate_run_id = %s", (run_id,))
    cur.close()
    # 18:00 +05:30 = 12:30 UTC
    assert stored.hour == 12
    assert stored.minute == 30


def test_first_pitch_time_is_timestamptz(conn):
    cols = _get_columns(conn, "oracle_game_analyses")
    assert cols["first_pitch_time"]["type"] == "timestamp with time zone"


# ---------------------------------------------------------------------------
# F. JSONB — valid insertion, retrieval, and type confirmation
# ---------------------------------------------------------------------------

def test_jsonb_event_payload_insert_and_retrieve(conn, seed_slate_run):
    payload = {"confidence": 0.87, "edge_pct": 4.2, "notes": ["lineup confirmed"]}
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_play_events
            (event_type, slate_run_id, event_timestamp, event_payload)
        VALUES ('ecf_calculated', %s, NOW(), %s)
        RETURNING event_id, event_payload
        """,
        (seed_slate_run, json.dumps(payload)),
    )
    event_id, retrieved = cur.fetchone()
    # DELETE blocked by append-only trigger (WP-2); TRUNCATE bypasses row-level triggers.
    cur.execute("TRUNCATE oracle_play_events")
    cur.close()
    assert retrieved["confidence"] == 0.87
    assert retrieved["edge_pct"] == 4.2
    assert retrieved["notes"] == ["lineup confirmed"]


def test_jsonb_event_payload_type_in_catalog(conn):
    cols = _get_columns(conn, "oracle_play_events")
    assert cols["event_payload"]["type"] == "jsonb"


def test_jsonb_event_payload_null_accepted(conn, seed_slate_run):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_play_events
            (event_type, slate_run_id, event_timestamp, event_payload)
        VALUES ('slate_initialized', %s, NOW(), NULL)
        RETURNING event_id, event_payload
        """,
        (seed_slate_run,),
    )
    event_id, payload_val = cur.fetchone()
    # DELETE blocked by append-only trigger (WP-2); TRUNCATE bypasses row-level triggers.
    cur.execute("TRUNCATE oracle_play_events")
    cur.close()
    assert payload_val is None


# ---------------------------------------------------------------------------
# G. BIGSERIAL — automatic sequence-backed identifier generation
# ---------------------------------------------------------------------------

def test_bigserial_event_id_auto_assigned(conn, seed_slate_run):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_play_events
            (event_type, slate_run_id, event_timestamp)
        VALUES ('slate_initialized', %s, NOW())
        RETURNING event_id
        """,
        (seed_slate_run,),
    )
    event_id = cur.fetchone()[0]
    # DELETE blocked by append-only trigger (WP-2); TRUNCATE bypasses row-level triggers.
    cur.execute("TRUNCATE oracle_play_events")
    cur.close()
    assert isinstance(event_id, int)
    assert event_id > 0


def test_bigserial_event_id_increments(conn, seed_slate_run):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO oracle_play_events (event_type, slate_run_id, event_timestamp) VALUES ('slate_initialized', %s, NOW()) RETURNING event_id",
        (seed_slate_run,),
    )
    id1 = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO oracle_play_events (event_type, slate_run_id, event_timestamp) VALUES ('schedule_retrieved', %s, NOW()) RETURNING event_id",
        (seed_slate_run,),
    )
    id2 = cur.fetchone()[0]
    # DELETE blocked by append-only trigger (WP-2); TRUNCATE bypasses row-level triggers.
    cur.execute("TRUNCATE oracle_play_events")
    cur.close()
    assert id2 > id1


def test_bigserial_audit_id_auto_assigned(conn):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_immutability_audit
            (violation_type, attempted_by)
        VALUES ('UPDATE', 'test_user')
        RETURNING audit_id
        """
    )
    audit_id = cur.fetchone()[0]
    cur.execute("DELETE FROM oracle_immutability_audit WHERE audit_id = %s", (audit_id,))
    cur.close()
    assert isinstance(audit_id, int)
    assert audit_id > 0


# ---------------------------------------------------------------------------
# K. Existing platform table protection
# ---------------------------------------------------------------------------

def test_existing_platform_tables_present(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = ANY(%s)
        """,
        (PLATFORM_TABLES,),
    )
    found = {row[0] for row in cur.fetchall()}
    cur.close()
    assert found == set(PLATFORM_TABLES), (
        f"Missing platform tables: {set(PLATFORM_TABLES) - found}"
    )


def test_no_unapproved_oracle_tables(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name LIKE 'oracle_%'
        """
    )
    found = {row[0] for row in cur.fetchall()}
    cur.close()
    unexpected = found - set(ORACLE_TABLES)
    assert not unexpected, f"Unapproved Oracle tables found: {unexpected}"


# ---------------------------------------------------------------------------
# L. Migration completeness and deterministic discovery (Inc-3; PM-1007 §§6-7)
# ---------------------------------------------------------------------------

def _numbered_migration_files():
    names = [
        f for f in os.listdir(_MIGRATIONS_DIR)
        if f.endswith(".sql") and f[:3].isdigit()
    ]
    return sorted(names)


def test_migration_files_are_numerically_prefixed_and_unique():
    files = _numbered_migration_files()
    numbers = [int(f[:3]) for f in files]
    assert len(numbers) == len(set(numbers)), "Duplicate migration numbers detected"


def test_migration_lexical_order_matches_numeric_order():
    """CI applies migrations in lexical filename order; it must equal numeric order."""
    files = _numbered_migration_files()
    lexical = list(files)
    numeric = sorted(files, key=lambda f: int(f[:3]))
    assert lexical == numeric, (
        "Lexical and numeric migration orders diverge; deterministic CI discovery "
        f"would apply out of order. lexical={lexical} numeric={numeric}"
    )


def test_migration_009_present():
    files = _numbered_migration_files()
    assert any(f.startswith("009_") for f in files), (
        "Migration 009 (Stage 5 schema) is missing from database/migrations/"
    )


def test_stage5_tables_exist(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = ANY(%s)
        """,
        (STAGE5_TABLES,),
    )
    found = {row[0] for row in cur.fetchall()}
    cur.close()
    assert found == set(STAGE5_TABLES), (
        f"Missing Stage 5 tables: {set(STAGE5_TABLES) - found}"
    )


def test_stage5_tables_have_append_only_triggers(conn):
    """Every Stage 5 table must carry UPDATE and DELETE append-only guards."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT event_object_table, event_manipulation
        FROM information_schema.triggers
        WHERE trigger_schema = 'public'
          AND event_object_table = ANY(%s)
        """,
        (STAGE5_TABLES,),
    )
    rows = cur.fetchall()
    cur.close()
    guarded: dict[str, set] = {}
    for table, manipulation in rows:
        guarded.setdefault(table, set()).add(manipulation)
    for table in STAGE5_TABLES:
        assert table in guarded, f"{table} has no append-only trigger"
        assert {"UPDATE", "DELETE"} <= guarded[table], (
            f"{table} missing UPDATE/DELETE append-only guard"
        )


def test_seeded_policy_update_is_rejected(conn):
    """Behavioral proof: UPDATE on the seeded policy row is blocked by the trigger."""
    cur = conn.cursor()
    with pytest.raises(psycopg2.errors.RaiseException):
        cur.execute(
            "UPDATE oracle_sport_policies SET governance_reference = 'X' "
            "WHERE policy_version_id = 'MLB-A3-v1'"
        )
    cur.close()


def test_sport_policy_mlb_a3_v1_seeded_and_active(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT time_cutoff_offset_seconds, governance_reference "
        "FROM oracle_sport_policies WHERE policy_version_id = 'MLB-A3-v1'"
    )
    policy_row = cur.fetchone()
    cur.execute(
        "SELECT policy_version_id FROM oracle_sport_policy_active "
        "WHERE sport_id = 'MLB' ORDER BY id DESC LIMIT 1"
    )
    active_row = cur.fetchone()
    cur.close()
    assert policy_row is not None, "MLB-A3-v1 policy not seeded"
    assert policy_row[0] == -900, "MLB-A3-v1 cutoff offset must be -900 seconds"
    assert policy_row[1] == "PM-1007"
    assert active_row is not None and active_row[0] == "MLB-A3-v1", (
        "MLB-A3-v1 must be the active MLB policy version"
    )


def test_migration_009_is_rerunnable(conn):
    """Re-applying migration 009 must not error or duplicate the seed."""
    path = os.path.join(_MIGRATIONS_DIR, "009_add_oracle_stage5_schema.sql")
    with open(path, "r", encoding="utf-8") as fh:
        sql = fh.read()
    cur = conn.cursor()
    cur.execute(sql)
    cur.execute("SELECT COUNT(*) FROM oracle_sport_policies WHERE policy_version_id = 'MLB-A3-v1'")
    policy_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM oracle_sport_policy_active WHERE policy_version_id = 'MLB-A3-v1'")
    active_count = cur.fetchone()[0]
    cur.close()
    assert policy_count == 1, "Re-running migration 009 duplicated the policy seed"
    assert active_count == 1, "Re-running migration 009 duplicated the active designation"
