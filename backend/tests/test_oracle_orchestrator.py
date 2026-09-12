"""Oracle Phase 1 WP-4 — Orchestrator Foundation tests (T01–T04) and
Run Orchestrator tests (T05–T08).

Sections A–L are pure unit tests (no database required).
Sections M–U are unit tests that patch DB dependencies.
Section V requires ORACLE_TEST_DATABASE_URL (integration tests).

Sections:
    A. Kill Switch (T01)
    B. Slate State Machine — valid transitions (T02)
    C. Slate State Machine — terminal state enforcement (T02)
    D. Slate State Machine — invalid and unknown transitions (T02)
    E. Game State Machine — valid transitions (T03)
    F. Game State Machine — terminal state enforcement (T03)
    G. Game State Machine — invalid, unknown, and DCR-W4-003 transitions (T03)
    H. Fixture Loader — shape and determinism (T04)
    I. Fixture Validation (T04)
    J. Fixture get_game_pk — WP-4 boundary conversion (T04)
    K. Fixture WP-3 integration — type compatibility (T04)
    L. Fixture connection invariants (T04)
    M. Orchestrator imports and interface (T05–T08)
    N. Kill switch enforcement in all stages (T05–T08)
    O. Stage 1 — Slate Initialization unit tests (T05)
    P. Stage 2 — Schedule Retrieval unit tests (T06)
    Q. Stage 3 — Preliminary Data Gather stub unit tests (T07)
    R. Stages 4–10 stub unit tests (T07)
    S. Event ordering and correctness (T05–T08)
    T. Transaction ownership (T05–T08)
    U. Failure and kill switch propagation (T05–T08)
    V. Integration tests — full Phase 1 run (T08, requires DB)
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from backend.oracle.fixtures import (
    FixtureValidationError,
    get_game_pk,
    load_phase1_fixtures,
    validate_fixture_record,
)
from backend.oracle.identifier_manager import (
    InvalidIdentifierInputError,
    generate_game_run_id,
    is_valid_game_run_id,
)
from backend.oracle.kill_switch import (
    _ENV_VAR,
    is_autonomous_run_enabled,
)
from backend.oracle.state_machines import (
    InvalidStateTransitionError,
    transition_game_state,
    transition_slate_state,
)
from backend.oracle.adapter_interface import (
    AvailabilityStatus,
    PreliminaryDataRecord,
    PreliminaryDataResponse,
    UnavailabilityReason,
)
from backend.oracle import stage9_pregame_lock as s9
from backend.oracle.orchestrator import (
    KillSwitchHaltError,
    OrchestratorError,
    run_oracle_phase1,
    run_stage_1,
    run_stage_2,
    run_stage_3,
    run_stage_4,
    run_stage_5,
    run_stage_6,
    run_stage_7,
    run_stage_8,
    run_stage_9,
    run_stage_10,
)


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

class _TrackingConn:
    """Minimal mock connection that records commit() and rollback() calls.

    Used to prove T04 functions never touch a caller-owned connection.
    The connection is never passed to any T04 function; its pristine
    state after each call demonstrates the absence of implicit DB access.
    """

    def __init__(self) -> None:
        self.autocommit = False
        self.commit_called = False
        self.rollback_called = False

    def commit(self) -> None:
        self.commit_called = True

    def rollback(self) -> None:
        self.rollback_called = True


# ---------------------------------------------------------------------------
# A. Kill Switch (T01)
# ---------------------------------------------------------------------------

class TestKillSwitch:
    """T01 — is_autonomous_run_enabled() via injected env dict (DCR-W4-001)."""

    # Absent / empty / whitespace — must return False

    def test_returns_false_when_variable_absent(self):
        assert is_autonomous_run_enabled(env={}) is False

    def test_returns_false_when_value_is_empty_string(self):
        assert is_autonomous_run_enabled(env={_ENV_VAR: ""}) is False

    def test_returns_false_when_value_is_whitespace_only(self):
        assert is_autonomous_run_enabled(env={_ENV_VAR: "   "}) is False

    # Truthy values — must return True

    def test_returns_true_for_lowercase_true(self):
        assert is_autonomous_run_enabled(env={_ENV_VAR: "true"}) is True

    def test_returns_true_for_uppercase_true(self):
        assert is_autonomous_run_enabled(env={_ENV_VAR: "TRUE"}) is True

    def test_returns_true_for_mixed_case_true(self):
        assert is_autonomous_run_enabled(env={_ENV_VAR: "True"}) is True

    def test_returns_true_for_true_with_surrounding_whitespace(self):
        assert is_autonomous_run_enabled(env={_ENV_VAR: "  true  "}) is True

    def test_returns_true_for_digit_one(self):
        assert is_autonomous_run_enabled(env={_ENV_VAR: "1"}) is True

    def test_returns_true_for_digit_one_with_surrounding_whitespace(self):
        assert is_autonomous_run_enabled(env={_ENV_VAR: " 1 "}) is True

    # Falsy explicit values — must return False

    def test_returns_false_for_false(self):
        assert is_autonomous_run_enabled(env={_ENV_VAR: "false"}) is False

    def test_returns_false_for_zero(self):
        assert is_autonomous_run_enabled(env={_ENV_VAR: "0"}) is False

    def test_returns_false_for_yes(self):
        assert is_autonomous_run_enabled(env={_ENV_VAR: "yes"}) is False

    def test_returns_false_for_on(self):
        assert is_autonomous_run_enabled(env={_ENV_VAR: "on"}) is False

    def test_returns_false_for_arbitrary_string(self):
        assert is_autonomous_run_enabled(env={_ENV_VAR: "foobar"}) is False

    # No-arg path uses os.environ — verified indirectly

    def test_returns_bool_type(self):
        result = is_autonomous_run_enabled(env={})
        assert isinstance(result, bool)

    def test_returns_bool_type_when_enabled(self):
        result = is_autonomous_run_enabled(env={_ENV_VAR: "true"})
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# B. Slate State Machine — valid transitions (T02)
# ---------------------------------------------------------------------------

class TestSlateStateMachineValidTransitions:
    """T02 — All 13 allowlist transitions must return to_state (DCR-W4-002)."""

    def test_initializing_to_schedule_loaded(self):
        assert transition_slate_state("initializing", "schedule_loaded") == "schedule_loaded"

    def test_initializing_to_analysis_failed(self):
        assert transition_slate_state("initializing", "analysis_failed") == "analysis_failed"

    def test_schedule_loaded_to_analysis_in_progress(self):
        assert transition_slate_state("schedule_loaded", "analysis_in_progress") == "analysis_in_progress"

    def test_analysis_in_progress_to_activation_window_open(self):
        assert transition_slate_state("analysis_in_progress", "activation_window_open") == "activation_window_open"

    def test_analysis_in_progress_to_analysis_failed(self):
        assert transition_slate_state("analysis_in_progress", "analysis_failed") == "analysis_failed"

    def test_activation_window_open_to_pregame_locked(self):
        assert transition_slate_state("activation_window_open", "pregame_locked") == "pregame_locked"

    def test_activation_window_open_to_activation_failed(self):
        assert transition_slate_state("activation_window_open", "activation_failed") == "activation_failed"

    def test_pregame_locked_to_settled(self):
        assert transition_slate_state("pregame_locked", "settled") == "settled"

    def test_pregame_locked_to_partial_void(self):
        assert transition_slate_state("pregame_locked", "partial_void") == "partial_void"

    def test_pregame_locked_to_settlement_pending_retry_dcr_w4_002(self):
        """DCR-W4-002: pregame_locked → settlement_pending_retry is a valid inbound transition."""
        assert transition_slate_state("pregame_locked", "settlement_pending_retry") == "settlement_pending_retry"

    def test_partial_void_to_settled(self):
        assert transition_slate_state("partial_void", "settled") == "settled"

    def test_partial_void_to_settlement_pending_retry_dcr_w4_002(self):
        """DCR-W4-002: partial_void → settlement_pending_retry is a valid inbound transition."""
        assert transition_slate_state("partial_void", "settlement_pending_retry") == "settlement_pending_retry"

    def test_settlement_pending_retry_to_settled(self):
        assert transition_slate_state("settlement_pending_retry", "settled") == "settled"

    def test_returns_the_to_state_string(self):
        result = transition_slate_state("initializing", "schedule_loaded")
        assert result == "schedule_loaded"
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# C. Slate State Machine — terminal state enforcement (T02)
# ---------------------------------------------------------------------------

class TestSlateStateMachineTerminalEnforcement:
    """T02 — Terminal states must reject all outbound transitions."""

    def test_settled_is_terminal(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("settled", "initializing")

    def test_analysis_failed_is_terminal(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("analysis_failed", "initializing")

    def test_activation_failed_is_terminal(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("activation_failed", "initializing")

    def test_settled_to_valid_non_terminal_state_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("settled", "schedule_loaded")

    def test_analysis_failed_to_schedule_loaded_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("analysis_failed", "schedule_loaded")

    def test_activation_failed_to_pregame_locked_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("activation_failed", "pregame_locked")

    def test_error_message_identifies_terminal_state(self):
        with pytest.raises(InvalidStateTransitionError, match="terminal"):
            transition_slate_state("settled", "initializing")


# ---------------------------------------------------------------------------
# D. Slate State Machine — invalid and unknown transitions (T02)
# ---------------------------------------------------------------------------

class TestSlateStateMachineInvalidTransitions:
    """T02 — Non-allowlist and unknown transitions must raise."""

    def test_unknown_from_state_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("unknown_state", "schedule_loaded")

    def test_unknown_to_state_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("initializing", "unknown_state")

    def test_both_unknown_states_raise(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("unknown_a", "unknown_b")

    def test_non_adjacent_forward_jump_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("initializing", "activation_window_open")

    def test_backward_transition_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("schedule_loaded", "initializing")

    def test_self_transition_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("initializing", "initializing")

    def test_settlement_pending_retry_cannot_go_back(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("settlement_pending_retry", "pregame_locked")

    def test_partial_void_cannot_go_to_initializing(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("partial_void", "initializing")

    def test_empty_string_from_state_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("", "schedule_loaded")

    def test_empty_string_to_state_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("initializing", "")

    def test_error_is_invalid_state_transition_error_type(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_slate_state("unknown_state", "schedule_loaded")


# ---------------------------------------------------------------------------
# E. Game State Machine — valid transitions (T03)
# ---------------------------------------------------------------------------

class TestGameStateMachineValidTransitions:
    """T03 — All 9 allowlist transitions must return to_state (DCR-W4-003; Inc-1 D-3)."""

    def test_scheduled_to_preliminary_analysis(self):
        assert transition_game_state("scheduled", "preliminary_analysis") == "preliminary_analysis"

    def test_scheduled_to_data_gather_failed(self):
        assert transition_game_state("scheduled", "data_gather_failed") == "data_gather_failed"

    def test_preliminary_analysis_to_lineup_monitoring(self):
        assert transition_game_state("preliminary_analysis", "lineup_monitoring") == "lineup_monitoring"

    def test_lineup_monitoring_to_final_analysis(self):
        assert transition_game_state("lineup_monitoring", "final_analysis") == "final_analysis"

    def test_final_analysis_to_activation_eligible(self):
        assert transition_game_state("final_analysis", "activation_eligible") == "activation_eligible"

    def test_activation_eligible_to_pregame_locked(self):
        assert transition_game_state("activation_eligible", "pregame_locked") == "pregame_locked"

    def test_pregame_locked_to_settled(self):
        assert transition_game_state("pregame_locked", "settled") == "settled"

    def test_pregame_locked_to_voided(self):
        assert transition_game_state("pregame_locked", "voided") == "voided"

    def test_pregame_locked_to_postponed(self):
        assert transition_game_state("pregame_locked", "postponed") == "postponed"

    def test_returns_to_state_string(self):
        result = transition_game_state("scheduled", "preliminary_analysis")
        assert result == "preliminary_analysis"
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# F. Game State Machine — terminal state enforcement (T03)
# ---------------------------------------------------------------------------

class TestGameStateMachineTerminalEnforcement:
    """T03 — Terminal game states must reject all outbound transitions."""

    def test_settled_is_terminal(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("settled", "scheduled")

    def test_voided_is_terminal(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("voided", "scheduled")

    def test_postponed_is_terminal(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("postponed", "scheduled")

    def test_data_gather_failed_is_terminal(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("data_gather_failed", "preliminary_analysis")

    def test_settled_to_preliminary_analysis_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("settled", "preliminary_analysis")

    def test_voided_to_lineup_monitoring_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("voided", "lineup_monitoring")

    def test_postponed_to_final_analysis_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("postponed", "final_analysis")

    def test_data_gather_failed_to_scheduled_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("data_gather_failed", "scheduled")

    def test_error_message_identifies_terminal_state(self):
        with pytest.raises(InvalidStateTransitionError, match="terminal"):
            transition_game_state("settled", "scheduled")

    def test_error_message_identifies_data_gather_failed_as_terminal(self):
        with pytest.raises(InvalidStateTransitionError, match="terminal"):
            transition_game_state("data_gather_failed", "scheduled")


# ---------------------------------------------------------------------------
# G. Game State Machine — invalid, unknown, and DCR-W4-003 transitions (T03)
# ---------------------------------------------------------------------------

class TestGameStateMachineInvalidTransitions:
    """T03 — Non-allowlist, unknown, and analysis_failed transitions must raise."""

    def test_unknown_from_state_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("unknown_state", "preliminary_analysis")

    def test_unknown_to_state_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("scheduled", "unknown_state")

    def test_forward_skip_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("scheduled", "lineup_monitoring")

    def test_backward_transition_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("preliminary_analysis", "scheduled")

    def test_self_transition_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("scheduled", "scheduled")

    def test_empty_string_from_state_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("", "preliminary_analysis")

    def test_empty_string_to_state_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("scheduled", "")

    # DCR-W4-003: analysis_failed is NOT a game state

    def test_analysis_failed_as_to_state_from_preliminary_analysis_raises(self):
        """DCR-W4-003: preliminary_analysis → analysis_failed must be rejected.
        analysis_failed is a slate state, not a game state."""
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("preliminary_analysis", "analysis_failed")

    def test_analysis_failed_as_to_state_from_final_analysis_raises(self):
        """DCR-W4-003: final_analysis → analysis_failed must be rejected."""
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("final_analysis", "analysis_failed")

    def test_analysis_failed_as_to_state_from_scheduled_raises(self):
        """DCR-W4-003: analysis_failed is unknown to the game machine."""
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("scheduled", "analysis_failed")

    def test_analysis_failed_as_from_state_raises(self):
        """DCR-W4-003: analysis_failed cannot appear as a game source state."""
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("analysis_failed", "settled")

    def test_data_gather_failed_outbound_raises_because_terminal(self):
        """Inc-1 D-3: data_gather_failed is a game terminal state; no outbound transitions."""
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("data_gather_failed", "preliminary_analysis")

    def test_error_is_invalid_state_transition_error_type(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("unknown_state", "preliminary_analysis")


# ---------------------------------------------------------------------------
# H. Fixture Loader — shape and determinism (T04)
# ---------------------------------------------------------------------------

class TestFixtureLoaderShape:
    """T04 — load_phase1_fixtures() shape, field presence, and determinism."""

    def test_returns_a_list(self):
        result = load_phase1_fixtures()
        assert isinstance(result, list)

    def test_returns_at_least_two_records(self):
        result = load_phase1_fixtures()
        assert len(result) >= 2

    def test_each_record_is_a_dict(self):
        for record in load_phase1_fixtures():
            assert isinstance(record, dict)

    def test_each_record_has_external_game_id(self):
        for record in load_phase1_fixtures():
            assert "external_game_id" in record

    def test_each_record_has_home_team(self):
        for record in load_phase1_fixtures():
            assert "home_team" in record

    def test_each_record_has_away_team(self):
        for record in load_phase1_fixtures():
            assert "away_team" in record

    def test_each_record_has_first_pitch_time(self):
        for record in load_phase1_fixtures():
            assert "first_pitch_time" in record

    def test_each_record_has_venue(self):
        for record in load_phase1_fixtures():
            assert "venue" in record

    def test_external_game_id_is_a_string(self):
        for record in load_phase1_fixtures():
            assert isinstance(record["external_game_id"], str)

    def test_external_game_id_is_a_numeric_string(self):
        """DCR-W4-004: external_game_id is stored as a numeric string, not an int."""
        for record in load_phase1_fixtures():
            assert record["external_game_id"].isdigit()

    def test_external_game_id_is_not_stored_as_int(self):
        """DCR-W4-004: The fixture contract stores external_game_id as str, not int."""
        for record in load_phase1_fixtures():
            assert not isinstance(record["external_game_id"], int)

    def test_first_pitch_time_ends_with_z_utc_marker(self):
        for record in load_phase1_fixtures():
            assert record["first_pitch_time"].endswith("Z"), (
                f"first_pitch_time must be UTC ISO-8601 ending with 'Z', "
                f"got {record['first_pitch_time']!r}"
            )

    def test_home_team_is_uppercase_alphabetic(self):
        for record in load_phase1_fixtures():
            abbr = record["home_team"]
            assert abbr.isupper() and abbr.isalpha()

    def test_away_team_is_uppercase_alphabetic(self):
        for record in load_phase1_fixtures():
            abbr = record["away_team"]
            assert abbr.isupper() and abbr.isalpha()

    def test_team_abbreviations_are_two_to_three_characters(self):
        for record in load_phase1_fixtures():
            assert 2 <= len(record["home_team"]) <= 3
            assert 2 <= len(record["away_team"]) <= 3

    def test_is_deterministic_across_calls(self):
        first = load_phase1_fixtures()
        second = load_phase1_fixtures()
        assert first == second

    def test_returns_new_list_each_call(self):
        """Mutations to the returned list must not affect subsequent calls."""
        first = load_phase1_fixtures()
        first.clear()
        second = load_phase1_fixtures()
        assert len(second) >= 2

    def test_returns_independent_records_each_call(self):
        first = load_phase1_fixtures()
        original_home_team = first[0]["home_team"]

        first[0]["home_team"] = "XYZ"

        second = load_phase1_fixtures()

        assert second[0]["home_team"] == original_home_team
        assert first[0] is not second[0]

    def test_all_records_pass_validate_fixture_record(self):
        """Every fixture record must satisfy the validation contract."""
        for record in load_phase1_fixtures():
            validate_fixture_record(record)  # must not raise


# ---------------------------------------------------------------------------
# I. Fixture Validation (T04)
# ---------------------------------------------------------------------------

class TestFixtureValidation:
    """T04 — validate_fixture_record() enforcement of the fixture contract."""

    _VALID: dict = {
        "external_game_id": "746484",
        "home_team": "NYY",
        "away_team": "BOS",
        "first_pitch_time": "2026-07-25T17:10:00Z",
        "venue": "Yankee Stadium",
    }

    def test_valid_record_passes_without_raising(self):
        validate_fixture_record(self._VALID)

    def test_non_dict_input_raises(self):
        with pytest.raises(FixtureValidationError):
            validate_fixture_record("not a dict")

    def test_list_input_raises(self):
        with pytest.raises(FixtureValidationError):
            validate_fixture_record(["external_game_id", "home_team"])

    def test_none_input_raises(self):
        with pytest.raises(FixtureValidationError):
            validate_fixture_record(None)

    def test_missing_external_game_id_raises(self):
        record = {k: v for k, v in self._VALID.items() if k != "external_game_id"}
        with pytest.raises(FixtureValidationError):
            validate_fixture_record(record)

    def test_missing_home_team_raises(self):
        record = {k: v for k, v in self._VALID.items() if k != "home_team"}
        with pytest.raises(FixtureValidationError):
            validate_fixture_record(record)

    def test_missing_away_team_raises(self):
        record = {k: v for k, v in self._VALID.items() if k != "away_team"}
        with pytest.raises(FixtureValidationError):
            validate_fixture_record(record)

    def test_missing_first_pitch_time_raises(self):
        record = {k: v for k, v in self._VALID.items() if k != "first_pitch_time"}
        with pytest.raises(FixtureValidationError):
            validate_fixture_record(record)

    def test_missing_venue_raises(self):
        record = {k: v for k, v in self._VALID.items() if k != "venue"}
        with pytest.raises(FixtureValidationError):
            validate_fixture_record(record)

    def test_empty_dict_raises(self):
        with pytest.raises(FixtureValidationError):
            validate_fixture_record({})

    def test_integer_external_game_id_raises(self):
        """DCR-W4-004: external_game_id must be str, not int."""
        record = {**self._VALID, "external_game_id": 746484}
        with pytest.raises(FixtureValidationError):
            validate_fixture_record(record)

    def test_float_external_game_id_raises(self):
        record = {**self._VALID, "external_game_id": 746484.0}
        with pytest.raises(FixtureValidationError):
            validate_fixture_record(record)

    def test_non_numeric_string_external_game_id_raises(self):
        record = {**self._VALID, "external_game_id": "abc123"}
        with pytest.raises(FixtureValidationError):
            validate_fixture_record(record)

    def test_empty_string_external_game_id_raises(self):
        record = {**self._VALID, "external_game_id": ""}
        with pytest.raises(FixtureValidationError):
            validate_fixture_record(record)

    def test_whitespace_string_external_game_id_raises(self):
        record = {**self._VALID, "external_game_id": "  "}
        with pytest.raises(FixtureValidationError):
            validate_fixture_record(record)

    def test_error_type_is_fixture_validation_error(self):
        with pytest.raises(FixtureValidationError):
            validate_fixture_record(None)


# ---------------------------------------------------------------------------
# J. Fixture get_game_pk — WP-4 boundary conversion (T04)
# ---------------------------------------------------------------------------

class TestGetGamePk:
    """T04 — get_game_pk() converts external_game_id from str to int (DCR-W4-004)."""

    _VALID: dict = {
        "external_game_id": "746484",
        "home_team": "NYY",
        "away_team": "BOS",
        "first_pitch_time": "2026-07-25T17:10:00Z",
        "venue": "Yankee Stadium",
    }

    def test_converts_numeric_string_to_int(self):
        result = get_game_pk(self._VALID)
        assert result == 746484

    def test_returns_int_type(self):
        """DCR-W4-004: generate_game_run_id requires game_pk: int."""
        result = get_game_pk(self._VALID)
        assert isinstance(result, int)
        assert not isinstance(result, bool)

    def test_large_game_pk_converted_correctly(self):
        record = {**self._VALID, "external_game_id": "9999999"}
        assert get_game_pk(record) == 9999999

    def test_invalid_record_raises_fixture_validation_error(self):
        with pytest.raises(FixtureValidationError):
            get_game_pk({"external_game_id": "abc", "home_team": "NYY",
                         "away_team": "BOS", "first_pitch_time": "...", "venue": "..."})

    def test_integer_external_game_id_raises_before_conversion(self):
        """Validate that int external_game_id is caught by validation, not int()."""
        record = {**self._VALID, "external_game_id": 746484}
        with pytest.raises(FixtureValidationError):
            get_game_pk(record)

    def test_missing_external_game_id_raises(self):
        record = {k: v for k, v in self._VALID.items() if k != "external_game_id"}
        with pytest.raises(FixtureValidationError):
            get_game_pk(record)

    def test_all_fixture_records_convert_successfully(self):
        for record in load_phase1_fixtures():
            pk = get_game_pk(record)
            assert isinstance(pk, int)
            assert pk > 0

    def test_deterministic_for_same_record(self):
        pk1 = get_game_pk(self._VALID)
        pk2 = get_game_pk(self._VALID)
        assert pk1 == pk2


# ---------------------------------------------------------------------------
# K. Fixture WP-3 integration — type compatibility (T04)
# ---------------------------------------------------------------------------

class TestFixtureWP3Integration:
    """T04 — Fixture records, processed at the WP-4 boundary, produce correct
    arguments for the WP-3 Identifier Manager's generate_game_run_id()."""

    _SLATE_RUN_ID = "ORACLE-20260725-001"

    def test_get_game_pk_result_accepted_by_generate_game_run_id(self):
        """DCR-W4-004: int(external_game_id) passes WP-3 type validation."""
        record = load_phase1_fixtures()[0]
        game_pk = get_game_pk(record)
        # generate_game_run_id validates game_pk type; must not raise
        game_run_id = generate_game_run_id(
            self._SLATE_RUN_ID,
            record["away_team"],
            record["home_team"],
            game_pk,
        )
        assert isinstance(game_run_id, str)

    def test_generate_game_run_id_rejects_string_external_game_id(self):
        """Proves WP-3 would reject the unconverted string — conversion is mandatory."""
        record = load_phase1_fixtures()[0]
        with pytest.raises(InvalidIdentifierInputError):
            generate_game_run_id(
                self._SLATE_RUN_ID,
                record["away_team"],
                record["home_team"],
                record["external_game_id"],  # str — must fail WP-3 validation
            )

    def test_game_run_id_embeds_game_pk_value(self):
        record = load_phase1_fixtures()[0]
        game_pk = get_game_pk(record)
        game_run_id = generate_game_run_id(
            self._SLATE_RUN_ID,
            record["away_team"],
            record["home_team"],
            game_pk,
        )
        assert str(game_pk) in game_run_id

    def test_game_run_id_is_valid_per_wp3_validator(self):
        record = load_phase1_fixtures()[0]
        game_pk = get_game_pk(record)
        game_run_id = generate_game_run_id(
            self._SLATE_RUN_ID,
            record["away_team"],
            record["home_team"],
            game_pk,
        )
        assert is_valid_game_run_id(game_run_id)

    def test_all_fixture_records_produce_valid_game_run_ids(self):
        for record in load_phase1_fixtures():
            game_pk = get_game_pk(record)
            game_run_id = generate_game_run_id(
                self._SLATE_RUN_ID,
                record["away_team"],
                record["home_team"],
                game_pk,
            )
            assert is_valid_game_run_id(game_run_id), (
                f"Fixture record produced invalid game_run_id: {game_run_id!r}"
            )

    def test_fixture_game_run_ids_are_distinct(self):
        """Each fixture record must produce a distinct game_run_id."""
        ids = [
            generate_game_run_id(
                self._SLATE_RUN_ID,
                r["away_team"],
                r["home_team"],
                get_game_pk(r),
            )
            for r in load_phase1_fixtures()
        ]
        assert len(ids) == len(set(ids)), f"Duplicate game_run_ids: {ids}"

    def test_team_abbreviations_preserved_through_wp3(self):
        """Fixture team abbreviations must appear verbatim in the game_run_id."""
        record = load_phase1_fixtures()[0]
        game_run_id = generate_game_run_id(
            self._SLATE_RUN_ID,
            record["away_team"],
            record["home_team"],
            get_game_pk(record),
        )
        assert record["away_team"] in game_run_id
        assert record["home_team"] in game_run_id

    def test_generation_is_deterministic(self):
        record = load_phase1_fixtures()[0]
        game_pk = get_game_pk(record)
        id1 = generate_game_run_id(self._SLATE_RUN_ID, record["away_team"], record["home_team"], game_pk)
        id2 = generate_game_run_id(self._SLATE_RUN_ID, record["away_team"], record["home_team"], game_pk)
        assert id1 == id2


# ---------------------------------------------------------------------------
# L. Fixture connection invariants (T04)
# ---------------------------------------------------------------------------

class TestFixtureConnectionInvariants:
    """T04 — Fixture processing must not commit or rollback a caller-owned connection.

    T04 functions do not accept a connection parameter; a caller-owned connection
    exists only in Stage 2 scope.  These tests prove that the T04 module has no
    implicit database access that could touch such a connection.
    """

    def test_load_phase1_fixtures_does_not_commit_caller_connection(self):
        conn = _TrackingConn()
        load_phase1_fixtures()
        assert not conn.commit_called

    def test_load_phase1_fixtures_does_not_rollback_caller_connection(self):
        conn = _TrackingConn()
        load_phase1_fixtures()
        assert not conn.rollback_called

    def test_validate_fixture_record_does_not_commit_caller_connection(self):
        conn = _TrackingConn()
        record = load_phase1_fixtures()[0]
        validate_fixture_record(record)
        assert not conn.commit_called

    def test_validate_fixture_record_does_not_rollback_caller_connection(self):
        conn = _TrackingConn()
        record = load_phase1_fixtures()[0]
        validate_fixture_record(record)
        assert not conn.rollback_called

    def test_get_game_pk_does_not_commit_caller_connection(self):
        conn = _TrackingConn()
        record = load_phase1_fixtures()[0]
        get_game_pk(record)
        assert not conn.commit_called

    def test_get_game_pk_does_not_rollback_caller_connection(self):
        conn = _TrackingConn()
        record = load_phase1_fixtures()[0]
        get_game_pk(record)
        assert not conn.rollback_called

    def test_full_fixture_processing_pipeline_does_not_commit(self):
        """Complete T04 processing pipeline leaves caller connection untouched."""
        conn = _TrackingConn()
        fixtures = load_phase1_fixtures()
        for record in fixtures:
            validate_fixture_record(record)
            get_game_pk(record)
        assert not conn.commit_called

    def test_full_fixture_processing_pipeline_does_not_rollback(self):
        conn = _TrackingConn()
        fixtures = load_phase1_fixtures()
        for record in fixtures:
            validate_fixture_record(record)
            get_game_pk(record)
        assert not conn.rollback_called


# ===========================================================================
# T05–T08 infrastructure
# ===========================================================================

_TEST_DB_URL = os.getenv("ORACLE_TEST_DATABASE_URL")
_requires_db = pytest.mark.skipif(
    not _TEST_DB_URL,
    reason="ORACLE_TEST_DATABASE_URL not set",
)

_ENABLED_ENV = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "true"}
_DISABLED_ENV: dict = {}
_TEST_DATE = date(2026, 7, 25)
# Stage 8 (PM-1067/1069/1071) enforces a strict decision_time < scheduled_cutoff_at gate. The
# Phase-1 fixtures use fixed past first-pitch dates (2026-07-25T17:10Z / 22:10Z → cutoffs
# 16:55Z / 21:55Z at the MLB-A3-v1 −900s offset), so the end-to-end pipeline is now time-
# sensitive. This deterministic instant is BEFORE every fixture cutoff, so the window opens and
# the slate settles; it controls time without weakening any assertion.
_PIPELINE_CLOCK = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
_TEST_SLATE_ID = "ORACLE-20260725-001"
_TEST_GAME_IDS = [
    "ORACLE-20260725-001-BOS-NYY-746484",
    "ORACLE-20260725-001-SFG-LAD-746485",
]

_PATCH_GENERATE_SLATE = "backend.oracle.orchestrator.generate_slate_run_id"
_PATCH_RECORD_EVENT = "backend.oracle.orchestrator.record_event"
_PATCH_GENERATE_GAME = "backend.oracle.orchestrator.generate_game_run_id"
_PATCH_LOAD_FIXTURES = "backend.oracle.orchestrator.load_phase1_fixtures"
_PATCH_GET_GAME_PK = "backend.oracle.orchestrator.get_game_pk"
_PATCH_VALIDATE_FIXTURE = "backend.oracle.orchestrator.validate_fixture_record"
_PATCH_TRANSITION_SLATE = "backend.oracle.orchestrator.transition_slate_state"
_PATCH_TRANSITION_GAME = "backend.oracle.orchestrator.transition_game_state"
_PATCH_MLB_ADAPTER = "backend.oracle.orchestrator.MLBAdapter"
_PATCH_GATHER_PRELIMINARY_DATA = "backend.oracle.orchestrator.gather_preliminary_data"
_PATCH_FETCH_PRELIMINARY_RECORD = "backend.oracle.orchestrator._fetch_preliminary_record"
_PATCH_INSERT_ECF_RESULT = "backend.oracle.orchestrator._insert_ecf_result"

_TEST_PRELIMINARY_ROW = (
    {},
    "DV-test-0",
    datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
)

_FIXTURE_RECORDS = [
    {
        "external_game_id": "746484",
        "home_team": "NYY",
        "away_team": "BOS",
        "first_pitch_time": "2026-07-25T17:10:00Z",
        "venue": "Yankee Stadium",
    },
    {
        "external_game_id": "746485",
        "home_team": "LAD",
        "away_team": "SFG",
        "first_pitch_time": "2026-07-25T22:10:00Z",
        "venue": "Dodger Stadium",
    },
]

_GATHER_AVAILABLE_RESPONSE = PreliminaryDataResponse(
    record=PreliminaryDataRecord(
        game_id="test",
        data_version_id="DV-test-0",
        gathered_at=datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
        source_system="mlb-statsapi",
        raw_payload={},
    ),
    availability=AvailabilityStatus(available=True),
)


class _MockCursor:
    """Minimal cursor that records SQL and params; supports close()."""

    def __init__(self) -> None:
        self.sql_log: list[str] = []
        self.params_log: list = []
        self.closed = False

    def execute(self, sql: str, params=None) -> None:
        self.sql_log.append(sql.strip())
        self.params_log.append(params)

    def fetchone(self):
        return None

    def close(self) -> None:
        self.closed = True


class _StageConn:
    """Mock psycopg2 connection for orchestrator unit tests.

    autocommit=False so _require_manual_transaction() does not raise when
    called by patched functions that have been replaced but whose callers
    (like _update_slate_status) still use conn.cursor() directly.
    """

    def __init__(self) -> None:
        self.autocommit = False
        self.cursors: list[_MockCursor] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def cursor(self) -> _MockCursor:
        cur = _MockCursor()
        self.cursors.append(cur)
        return cur

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1

    @property
    def commit_called(self) -> bool:
        return self.commit_count > 0

    @property
    def rollback_called(self) -> bool:
        return self.rollback_count > 0


# ---------------------------------------------------------------------------
# M. Orchestrator imports and interface
# ---------------------------------------------------------------------------

class TestOrchestratorInterface:
    """M — Public surface of backend.oracle.orchestrator."""

    def test_orchestrator_error_is_importable(self):
        assert OrchestratorError is not None

    def test_orchestrator_error_is_exception_subclass(self):
        assert issubclass(OrchestratorError, Exception)

    def test_kill_switch_halt_error_is_importable(self):
        assert KillSwitchHaltError is not None

    def test_kill_switch_halt_error_is_orchestrator_error(self):
        assert issubclass(KillSwitchHaltError, OrchestratorError)

    def test_kill_switch_halt_error_is_exception_subclass(self):
        assert issubclass(KillSwitchHaltError, Exception)

    def test_run_stage_1_is_callable(self):
        assert callable(run_stage_1)

    def test_run_stage_2_is_callable(self):
        assert callable(run_stage_2)

    def test_run_stage_3_through_10_are_callable(self):
        for fn in (run_stage_3, run_stage_4, run_stage_5,
                   run_stage_6, run_stage_7, run_stage_8,
                   run_stage_9, run_stage_10):
            assert callable(fn)

    def test_run_oracle_phase1_is_callable(self):
        assert callable(run_oracle_phase1)

    def test_kill_switch_halt_error_can_be_raised_and_caught_as_orchestrator_error(self):
        with pytest.raises(OrchestratorError):
            raise KillSwitchHaltError("test")


# ---------------------------------------------------------------------------
# N. Kill switch enforcement in all stages
# ---------------------------------------------------------------------------

class TestKillSwitchEnforcementInStages:
    """N — Every stage gate raises KillSwitchHaltError when disabled."""

    def _conn(self):
        return _StageConn()

    def test_stage1_raises_when_kill_switch_disabled(self):
        with pytest.raises(KillSwitchHaltError):
            run_stage_1(self._conn(), _TEST_DATE, env=_DISABLED_ENV)

    def test_stage2_raises_when_kill_switch_disabled(self):
        with pytest.raises(KillSwitchHaltError):
            run_stage_2(self._conn(), _TEST_SLATE_ID, env=_DISABLED_ENV)

    def test_stage3_raises_when_kill_switch_disabled(self):
        with pytest.raises(KillSwitchHaltError):
            run_stage_3(self._conn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)

    def test_stage4_raises_when_kill_switch_disabled(self):
        with pytest.raises(KillSwitchHaltError):
            run_stage_4(self._conn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)

    def test_stage5_raises_when_kill_switch_disabled(self):
        with pytest.raises(KillSwitchHaltError):
            run_stage_5(self._conn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)

    def test_stage6_raises_when_kill_switch_disabled(self):
        with pytest.raises(KillSwitchHaltError):
            run_stage_6(self._conn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)

    def test_stage7_raises_when_kill_switch_disabled(self):
        with pytest.raises(KillSwitchHaltError):
            run_stage_7(self._conn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)

    def test_stage8_raises_when_kill_switch_disabled(self):
        with pytest.raises(KillSwitchHaltError):
            run_stage_8(self._conn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)

    def test_stage9_raises_when_kill_switch_disabled(self):
        with pytest.raises(KillSwitchHaltError):
            run_stage_9(self._conn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)

    def test_stage10_raises_when_kill_switch_disabled(self):
        with pytest.raises(KillSwitchHaltError):
            run_stage_10(self._conn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)

    def test_run_oracle_phase1_raises_when_kill_switch_disabled(self):
        with pytest.raises(KillSwitchHaltError):
            run_oracle_phase1(self._conn(), _TEST_DATE, env=_DISABLED_ENV)

    def test_stage1_kill_switch_check_precedes_any_db_call(self):
        conn = _StageConn()
        with pytest.raises(KillSwitchHaltError):
            run_stage_1(conn, _TEST_DATE, env=_DISABLED_ENV)
        assert len(conn.cursors) == 0

    def test_stage2_kill_switch_check_precedes_any_db_call(self):
        conn = _StageConn()
        with pytest.raises(KillSwitchHaltError):
            run_stage_2(conn, _TEST_SLATE_ID, env=_DISABLED_ENV)
        assert len(conn.cursors) == 0

    def test_stage3_kill_switch_check_precedes_any_db_call(self):
        conn = _StageConn()
        with pytest.raises(KillSwitchHaltError):
            run_stage_3(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)
        assert len(conn.cursors) == 0


# ---------------------------------------------------------------------------
# O. Stage 1 — Slate Initialization unit tests
# ---------------------------------------------------------------------------

class TestStage1SlateInitialization:
    """O — Stage 1 unit tests with generate_slate_run_id and record_event patched."""

    def _run(self, conn=None, env=_ENABLED_ENV):
        if conn is None:
            conn = _StageConn()
        with patch(_PATCH_GENERATE_SLATE, return_value=_TEST_SLATE_ID), \
             patch(_PATCH_RECORD_EVENT, return_value=1):
            return run_stage_1(conn, _TEST_DATE, env=env), conn

    def test_returns_slate_run_id_string(self):
        result, _ = self._run()
        assert result == _TEST_SLATE_ID

    def test_returns_string_type(self):
        result, _ = self._run()
        assert isinstance(result, str)

    def test_inserts_into_oracle_slate_runs(self):
        _, conn = self._run()
        insert_sqls = [s for c in conn.cursors for s in c.sql_log if "oracle_slate_runs" in s.lower() and "INSERT" in s.upper()]
        assert len(insert_sqls) == 1

    def test_insert_includes_slate_run_id(self):
        _, conn = self._run()
        insert_cursor = next(c for c in conn.cursors if any("INSERT" in s.upper() and "oracle_slate_runs" in s.lower() for s in c.sql_log))
        assert _TEST_SLATE_ID in insert_cursor.params_log[0]

    def test_insert_includes_initializing_status(self):
        _, conn = self._run()
        insert_cursor = next(c for c in conn.cursors if any("INSERT" in s.upper() and "oracle_slate_runs" in s.lower() for s in c.sql_log))
        assert "initializing" in insert_cursor.params_log[0]

    def test_insert_includes_zero_daily_plays_activated(self):
        _, conn = self._run()
        insert_cursor = next(c for c in conn.cursors if any("INSERT" in s.upper() and "oracle_slate_runs" in s.lower() for s in c.sql_log))
        assert 0 in insert_cursor.params_log[0]

    def test_insert_includes_run_date(self):
        _, conn = self._run()
        insert_cursor = next(c for c in conn.cursors if any("INSERT" in s.upper() and "oracle_slate_runs" in s.lower() for s in c.sql_log))
        assert _TEST_DATE in insert_cursor.params_log[0]

    def test_updates_slate_status_to_schedule_loaded(self):
        _, conn = self._run()
        update_sqls = [s for c in conn.cursors for s in c.sql_log if "UPDATE" in s.upper() and "oracle_slate_runs" in s.lower()]
        assert len(update_sqls) == 1
        update_cursor = next(c for c in conn.cursors if any("UPDATE" in s.upper() and "oracle_slate_runs" in s.lower() for s in c.sql_log))
        assert "schedule_loaded" in update_cursor.params_log[0]

    def test_calls_record_event_with_slate_initialized(self):
        conn = _StageConn()
        with patch(_PATCH_GENERATE_SLATE, return_value=_TEST_SLATE_ID) as _gs, \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_1(conn, _TEST_DATE, env=_ENABLED_ENV)
        assert mock_re.call_args[0][1] == "slate_initialized"

    def test_record_event_receives_conn_as_first_arg(self):
        conn = _StageConn()
        with patch(_PATCH_GENERATE_SLATE, return_value=_TEST_SLATE_ID), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_1(conn, _TEST_DATE, env=_ENABLED_ENV)
        assert mock_re.call_args[0][0] is conn

    def test_record_event_receives_slate_run_id(self):
        conn = _StageConn()
        with patch(_PATCH_GENERATE_SLATE, return_value=_TEST_SLATE_ID), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_1(conn, _TEST_DATE, env=_ENABLED_ENV)
        assert mock_re.call_args[0][2] == _TEST_SLATE_ID

    def test_calls_commit_exactly_once(self):
        _, conn = self._run()
        assert conn.commit_count == 1

    def test_does_not_call_rollback(self):
        _, conn = self._run()
        assert not conn.rollback_called

    def test_does_not_close_connection(self):
        _, conn = self._run()
        assert conn.close_count == 0

    def test_all_cursors_are_closed(self):
        _, conn = self._run()
        assert all(c.closed for c in conn.cursors)

    def test_generate_slate_run_id_exception_does_not_commit(self):
        conn = _StageConn()
        with patch(_PATCH_GENERATE_SLATE, side_effect=RuntimeError("db error")):
            with pytest.raises(RuntimeError):
                run_stage_1(conn, _TEST_DATE, env=_ENABLED_ENV)
        assert not conn.commit_called

    def test_record_event_exception_does_not_commit(self):
        conn = _StageConn()
        with patch(_PATCH_GENERATE_SLATE, return_value=_TEST_SLATE_ID), \
             patch(_PATCH_RECORD_EVENT, side_effect=ValueError("bad event")):
            with pytest.raises(ValueError):
                run_stage_1(conn, _TEST_DATE, env=_ENABLED_ENV)
        assert not conn.commit_called


# ---------------------------------------------------------------------------
# P. Stage 2 — Schedule Retrieval unit tests
# ---------------------------------------------------------------------------

class TestStage2ScheduleRetrieval:
    """P — Stage 2 unit tests with load_phase1_fixtures, record_event patched."""

    def _run(self, conn=None, env=_ENABLED_ENV):
        if conn is None:
            conn = _StageConn()
        with patch(_PATCH_LOAD_FIXTURES, return_value=_FIXTURE_RECORDS), \
             patch(_PATCH_VALIDATE_FIXTURE), \
             patch(_PATCH_GET_GAME_PK, side_effect=lambda r: int(r["external_game_id"])), \
             patch(_PATCH_GENERATE_GAME, side_effect=lambda s, a, h, pk: f"{s}-{a}-{h}-{pk}"), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            result = run_stage_2(conn, _TEST_SLATE_ID, env=env)
        return result, conn, mock_re

    def test_returns_list(self):
        result, _, _ = self._run()
        assert isinstance(result, list)

    def test_returns_two_game_run_ids(self):
        result, _, _ = self._run()
        assert len(result) == 2

    def test_game_run_ids_contain_slate_run_id(self):
        result, _, _ = self._run()
        for gid in result:
            assert _TEST_SLATE_ID in gid

    def test_inserts_game_analyses_for_each_fixture(self):
        _, conn, _ = self._run()
        inserts = [s for c in conn.cursors for s in c.sql_log if "INSERT" in s.upper() and "oracle_game_analyses" in s.lower()]
        assert len(inserts) == 2

    def test_game_analyses_include_scheduled_status(self):
        _, conn, _ = self._run()
        game_cursors = [c for c in conn.cursors if any("oracle_game_analyses" in s.lower() for s in c.sql_log)]
        for c in game_cursors:
            assert "scheduled" in c.params_log[0]

    def test_game_analyses_include_slate_run_id(self):
        _, conn, _ = self._run()
        game_cursors = [c for c in conn.cursors if any("oracle_game_analyses" in s.lower() for s in c.sql_log)]
        for c in game_cursors:
            assert _TEST_SLATE_ID in c.params_log[0]

    def test_writes_schedule_retrieved_event(self):
        _, _, mock_re = self._run()
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert "schedule_retrieved" in event_types

    def test_writes_game_analysis_started_per_game(self):
        _, _, mock_re = self._run()
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert event_types.count("game_analysis_started") == 2

    def test_schedule_retrieved_before_first_game_analysis_started(self):
        _, _, mock_re = self._run()
        event_types = [c[0][1] for c in mock_re.call_args_list]
        sr_idx = event_types.index("schedule_retrieved")
        ga_idx = event_types.index("game_analysis_started")
        assert sr_idx < ga_idx

    def test_updates_slate_status_to_analysis_in_progress(self):
        _, conn, _ = self._run()
        update_cursor = next(c for c in conn.cursors if any("UPDATE" in s.upper() and "oracle_slate_runs" in s.lower() for s in c.sql_log))
        assert "analysis_in_progress" in update_cursor.params_log[0]

    def test_calls_commit_exactly_once(self):
        _, conn, _ = self._run()
        assert conn.commit_count == 1

    def test_does_not_call_rollback(self):
        _, conn, _ = self._run()
        assert not conn.rollback_called

    def test_does_not_close_connection(self):
        _, conn, _ = self._run()
        assert conn.close_count == 0

    def test_all_cursors_are_closed(self):
        _, conn, _ = self._run()
        assert all(c.closed for c in conn.cursors)


# ---------------------------------------------------------------------------
# Q. Stage 3 — Preliminary Data Gather stub unit tests
# ---------------------------------------------------------------------------

class TestStage3PreliminaryDataGather:
    """Q — Stage 3 Inc-1: preliminary data gather; game state scheduled→preliminary_analysis."""

    def _run(self, conn=None, env=_ENABLED_ENV):
        if conn is None:
            conn = _StageConn()
        with patch(_PATCH_GATHER_PRELIMINARY_DATA, return_value=_GATHER_AVAILABLE_RESPONSE), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            result = run_stage_3(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=env)
        return result, conn, mock_re

    def test_returns_none(self):
        result, _, _ = self._run()
        assert result is None

    def test_writes_preliminary_data_gathered_per_game(self):
        _, _, mock_re = self._run()
        assert mock_re.call_count == 2
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert all(et == "preliminary_data_gathered" for et in event_types)

    def test_updates_game_status_to_preliminary_analysis_per_game(self):
        _, conn, _ = self._run()
        update_cursors = [c for c in conn.cursors if any("UPDATE" in s.upper() and "oracle_game_analyses" in s.lower() for s in c.sql_log)]
        assert len(update_cursors) == 2
        for c in update_cursors:
            assert "preliminary_analysis" in c.params_log[0]

    def test_inserts_into_oracle_preliminary_data_per_game(self):
        _, conn, _ = self._run()
        insert_sqls = [s for c in conn.cursors for s in c.sql_log
                       if "oracle_preliminary_data" in s.lower() and "INSERT" in s.upper()]
        assert len(insert_sqls) == 2

    def test_inserts_into_oracle_lifecycle_audit_per_game(self):
        _, conn, _ = self._run()
        insert_sqls = [s for c in conn.cursors for s in c.sql_log
                       if "oracle_lifecycle_audit" in s.lower() and "INSERT" in s.upper()]
        assert len(insert_sqls) == 2

    def test_preliminary_data_insert_includes_game_run_id(self):
        _, conn, _ = self._run()
        prelim_cursors = [c for c in conn.cursors
                          if any("oracle_preliminary_data" in s.lower() and "INSERT" in s.upper()
                                 for s in c.sql_log)]
        game_run_ids_in_params = [c.params_log[0][0] for c in prelim_cursors]
        assert set(game_run_ids_in_params) == set(_TEST_GAME_IDS)

    def test_commits_exactly_once(self):
        _, conn, _ = self._run()
        assert conn.commit_count == 1

    def test_does_not_rollback(self):
        _, conn, _ = self._run()
        assert not conn.rollback_called


class TestStage3MI5AvailabilityGate:
    """Q — MI-5 gate: run_stage_3 early-exits when adapter unavailable (PM-783/Authority B)."""

    def _run_unavailable(self, reason=UnavailabilityReason.DATA_SOURCE_UNREACHABLE):
        conn = _StageConn()
        mock_adapter = MagicMock()
        mock_adapter.get_availability.return_value = AvailabilityStatus(
            available=False, reason=reason
        )
        with patch(_PATCH_MLB_ADAPTER, return_value=mock_adapter), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            result = run_stage_3(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        return result, conn, mock_re

    def test_mi5_unavailable_returns_none(self):
        result, _, _ = self._run_unavailable()
        assert result is None

    def test_mi5_unavailable_commits_exactly_once(self):
        _, conn, _ = self._run_unavailable()
        assert conn.commit_count == 1

    def test_mi5_unavailable_writes_data_gather_failed_per_game(self):
        _, _, mock_re = self._run_unavailable()
        assert mock_re.call_count == 2
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert all(et == "data_gather_failed" for et in event_types)


# ---------------------------------------------------------------------------
# R. Stages 4–10 stub unit tests
# ---------------------------------------------------------------------------

class TestStage4EcfCalculation:
    """R — Stage 4: ecf_calculated per game (success path); no game state update."""

    def _run(self, conn=None, env=_ENABLED_ENV):
        if conn is None:
            conn = _StageConn()
        with patch(_PATCH_FETCH_PRELIMINARY_RECORD, return_value=_TEST_PRELIMINARY_ROW), \
             patch(_PATCH_INSERT_ECF_RESULT), \
             patch("backend.oracle.orchestrator._insert_lifecycle_audit"), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_4(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=env)
        return conn, mock_re

    def test_writes_ecf_calculated_per_game(self):
        _, mock_re = self._run()
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert event_types.count("ecf_calculated") == 2

    def test_ecf_calculated_includes_game_run_id(self):
        _, mock_re = self._run()
        for c in mock_re.call_args_list:
            assert c[1].get("game_run_id") is not None or c[0][4] is not None

    def test_commits_exactly_once(self):
        conn, _ = self._run()
        assert conn.commit_count == 1

    def test_no_game_status_update_cursors(self):
        conn, _ = self._run()
        update_cursors = [c for c in conn.cursors if any("UPDATE" in s.upper() for s in c.sql_log)]
        assert len(update_cursors) == 0


class _FakePolicy:
    """Stand-in for the active MLB-A3-v1 sport policy record."""
    policy_version_id = "MLB-A3-v1"
    time_cutoff_offset = timedelta(minutes=-15)


def _fake_ecf_row(game_run_id):
    return (
        f"ECFR-{game_run_id}",
        f"DV-{game_run_id}",
        0.9,
        {"data_completeness": 0.9, "data_freshness": 0.9, "data_payload_density": 0.8},
    )


_PATCH_LOAD_POLICY = "backend.oracle.orchestrator._load_active_mlb_policy"
_PATCH_FETCH_ECF = "backend.oracle.orchestrator._fetch_latest_ecf_result"
_PATCH_FETCH_FIRST_PITCH = "backend.oracle.orchestrator._fetch_first_pitch_time"
_PATCH_FETCH_PAYLOAD = "backend.oracle.orchestrator._fetch_preliminary_payload"


class TestStage5IntelligencePipeline:
    """R — Stage 5 MVP: four-engine pipeline; multi_model_analysis_completed;
    game→lineup_monitoring; result/output/cutoff/audit persisted; atomic commit.
    (Inc-3; PM-1009 under PM-1007. Replaces the retired stub coverage.)"""

    def _run(self, conn=None, env=_ENABLED_ENV, ecf_side_effect=None):
        if conn is None:
            conn = _StageConn()
        first_pitch = datetime(2026, 7, 25, 17, 10, tzinfo=timezone.utc)
        fetch_ecf = ecf_side_effect or (lambda c, grid: _fake_ecf_row(grid))
        with patch(_PATCH_LOAD_POLICY, return_value=_FakePolicy()), \
             patch(_PATCH_FETCH_ECF, side_effect=fetch_ecf), \
             patch(_PATCH_FETCH_FIRST_PITCH, return_value=first_pitch), \
             patch(_PATCH_FETCH_PAYLOAD, return_value={"home_pitcher": "A", "away_pitcher": "B"}), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_5(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=env)
        return conn, mock_re

    def test_emits_multi_model_analysis_completed_per_game(self):
        _, mock_re = self._run()
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert event_types == ["multi_model_analysis_completed"] * 2

    def test_does_not_emit_phie_or_ce_events(self):
        _, mock_re = self._run()
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert "phie_completed" not in event_types
        assert "ce_completed" not in event_types

    def test_updates_game_status_to_lineup_monitoring(self):
        conn, _ = self._run()
        update_cursors = [
            c for c in conn.cursors
            if any("UPDATE" in s.upper() and "oracle_game_analyses" in s.lower() for s in c.sql_log)
        ]
        assert len(update_cursors) == 2
        for c in update_cursors:
            assert "lineup_monitoring" in c.params_log[0]

    def test_persists_stage5_result_and_preliminary_output(self):
        conn, _ = self._run()
        all_sql = " ".join(s.lower() for c in conn.cursors for s in c.sql_log)
        assert "oracle_stage5_results" in all_sql
        assert "oracle_preliminary_outputs" in all_sql

    def test_persists_scheduled_cutoff(self):
        conn, _ = self._run()
        all_sql = " ".join(s.lower() for c in conn.cursors for s in c.sql_log)
        assert "oracle_scheduled_cutoffs" in all_sql

    def test_writes_lifecycle_audit_at_stage_5(self):
        conn, _ = self._run()
        audit_cursors = [
            c for c in conn.cursors
            if any("oracle_lifecycle_audit" in s.lower() for s in c.sql_log)
        ]
        assert audit_cursors
        assert any("5" in c.params_log[0] for c in audit_cursors)

    def test_commits_exactly_once(self):
        conn, _ = self._run()
        assert conn.commit_count == 1

    def test_does_not_rollback_on_success(self):
        conn, _ = self._run()
        assert not conn.rollback_called

    def test_skips_games_without_ecf_result(self):
        conn, mock_re = self._run(ecf_side_effect=lambda c, grid: None)
        assert mock_re.call_count == 0
        assert conn.commit_count == 1  # empty commit, no work


class TestStage6LineupMonitoring:
    """R — Stage 6 evidence-safe: one OBSERVED_FULL observation per game;
    lineup_observation_recorded emitted; stays in lineup_monitoring; never emits
    lineup_confirmed / recalculation_triggered. (Replaces retired stub coverage;
    Inc-3+ PM-1031 under PM-1029.)"""

    def _obs(self, game_id="1"):
        from backend.oracle.mlb_adapter import LineupObservation, LINEUP_OBSERVED_FULL, PITCHER_PROBABLE
        return LineupObservation(
            game_id=game_id, classification=LINEUP_OBSERVED_FULL,
            home_order=tuple(range(1, 10)), away_order=tuple(range(11, 20)),
            home_pitcher={"id": 100, "epistemic_status": PITCHER_PROBABLE},
            away_pitcher={"id": 200, "epistemic_status": PITCHER_PROBABLE},
            home_lineup_status=LINEUP_OBSERVED_FULL, away_lineup_status=LINEUP_OBSERVED_FULL,
        )

    def _run(self, conn=None, env=_ENABLED_ENV):
        if conn is None:
            conn = _StageConn()
        with patch("backend.oracle.orchestrator._load_active_mlb_policy", return_value=_FakePolicy()), \
             patch("backend.oracle.orchestrator.MLBAdapter") as MockAdapter, \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            MockAdapter.return_value.observe_lineup.side_effect = lambda gid: self._obs(gid)
            run_stage_6(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=env)
        return conn, mock_re

    def test_emits_lineup_observation_recorded_per_game(self):
        _, mock_re = self._run()
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert event_types.count("lineup_observation_recorded") == 2

    def test_never_emits_confirmed_or_recalc(self):
        _, mock_re = self._run()
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert "lineup_confirmed" not in event_types
        assert "recalculation_triggered" not in event_types

    def test_no_first_observation_change_event(self):
        _, mock_re = self._run()  # mock conn has no prior observation
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert "lineup_change_detected" not in event_types

    def test_no_game_status_update(self):
        conn, _ = self._run()
        update_cursors = [c for c in conn.cursors if any("UPDATE" in s.upper() and "game_status" in s.lower() for s in c.sql_log)]
        assert len(update_cursors) == 0

    def test_persists_observation_row(self):
        conn, _ = self._run()
        all_sql = " ".join(s.lower() for c in conn.cursors for s in c.sql_log)
        assert "oracle_lineup_observations" in all_sql

    def test_commits_exactly_once(self):
        conn, _ = self._run()
        assert conn.commit_count == 1


class TestStage7FinalAnalysis:
    """R — Stage 7 finalization (Option A; PM-1047/PM-1049/PM-1051): emits NO event, and
    read-only outcomes make no writes. With the pristine mock connection every fetch returns
    None, so each game is INELIGIBLE (actual status is not lineup_monitoring). Full
    behavioural coverage (first finalization / replay / changed provenance / temporal /
    concurrency / rollback / immutability) is DB-backed in test_stage7.py."""

    def _run(self, conn=None, env=_ENABLED_ENV):
        if conn is None:
            conn = _StageConn()
        with patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            results = run_stage_7(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=env)
        return conn, mock_re, results

    def test_emits_no_event(self):
        _, mock_re, _ = self._run()
        assert mock_re.call_count == 0

    def test_returns_one_result_per_game(self):
        _, _, results = self._run()
        assert len(results) == len(_TEST_GAME_IDS)

    def test_ineligible_when_not_in_lineup_monitoring(self):
        _, _, results = self._run()
        assert all(r.outcome == "INELIGIBLE" for r in results)
        assert all(r.reason == "not_in_lineup_monitoring" for r in results)

    def test_read_only_outcome_makes_no_commit_or_rollback(self):
        conn, _, _ = self._run()
        assert conn.commit_count == 0
        assert conn.rollback_count == 0

    def test_all_cursors_closed(self):
        conn, _, _ = self._run()
        assert all(c.closed for c in conn.cursors)


class TestStage8ActivationWindow:
    """R — Stage 8 activation window (C1 FULL; PM-1067 / PM-1069 / PM-1071).

    These mock-only tests assert the event-free invariant (C3) and no-false-write behaviour.
    Under the _StageConn mock the slate row is absent (fetchone → None), so no game is admitted;
    full contract behaviour (WINDOW_OPENED / EXACT_REPLAY / CHANGED_PROVENANCE, the strict cutoff
    gate, slate-lock contention, later admission, advanced-state rejection, defensive uniqueness
    recovery) is covered against a real PostgreSQL database in test_stage8.py."""

    def _run(self, conn=None, env=_ENABLED_ENV):
        if conn is None:
            conn = _StageConn()
        with patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            results = run_stage_8(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=env)
        return conn, mock_re, results

    def test_event_free_no_event_emitted(self):
        # C3 EVENT-FREE: Stage 8 emits no event at all (in particular no candidate_created).
        _, mock_re, _ = self._run()
        mock_re.assert_not_called()

    def test_no_false_write_when_slate_not_admitting(self):
        # Under the mock (slate row absent), no game is admitted: no commit and no rollback.
        conn, _, _ = self._run()
        assert conn.commit_count == 0
        assert not conn.rollback_called

    def test_returns_one_ineligible_result_per_game_under_mock(self):
        # Under the mock every fetch returns None, so persisted game membership is absent →
        # the membership guard (PM-1075) rejects each game before any write.
        _, _, results = self._run()
        assert [r.game_run_id for r in results] == _TEST_GAME_IDS
        assert all(r.outcome == "INELIGIBLE" for r in results)
        assert all(r.reason == "not_in_slate" for r in results)

    def test_no_game_status_update_when_not_admitting(self):
        conn, _, _ = self._run()
        game_updates = [
            c for c in conn.cursors
            if any("UPDATE" in s.upper() and "oracle_game_analyses" in s.lower() for s in c.sql_log)
        ]
        assert game_updates == []


class TestStage9PregameLock:
    """R — Stage 9 pregame lock (FULL immutable lock; PM-1089/1091/1092).

    Orchestrator-level unit behaviour with a mock connection whose reads return None (no persisted
    slate/game/admission state): every game is truthfully INELIGIBLE (not_in_slate), nothing is
    locked, no play_locked event is emitted, and no commit occurs. This proves the corrected
    membership-first / actual-state discipline (no silent lock). Full DB acceptance — locking,
    replay, freeze boundary, aggregate completion, contention, defensive recovery — lives in
    backend/tests/test_stage9.py.
    """

    def _run(self, conn=None, env=_ENABLED_ENV):
        if conn is None:
            conn = _StageConn()
        with patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            results = run_stage_9(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=env)
        return conn, mock_re, results

    def test_returns_one_result_per_game(self):
        _, _, results = self._run()
        assert [r.game_run_id for r in results] == list(_TEST_GAME_IDS)

    def test_all_ineligible_not_in_slate_without_persisted_state(self):
        _, _, results = self._run()
        assert all(r.outcome == s9.INELIGIBLE for r in results)
        assert all(r.reason == s9.REASON_NOT_IN_SLATE for r in results)

    def test_no_play_locked_event_when_nothing_locked(self):
        _, mock_re, _ = self._run()
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert event_types.count("play_locked") == 0

    def test_no_commit_when_nothing_locked(self):
        conn, _, _ = self._run()
        assert conn.commit_count == 0

    def test_no_game_status_update_when_nothing_locked(self):
        conn, _, _ = self._run()
        game_updates = [
            c for c in conn.cursors
            if any("UPDATE" in s.upper() and "oracle_game_analyses" in s.lower() for s in c.sql_log)
        ]
        assert game_updates == []


class TestStage10Settlement:
    """R — Stage 10 stub: settlement_completed per game; game→settled; slate→settled."""

    def _run(self, conn=None, env=_ENABLED_ENV):
        if conn is None:
            conn = _StageConn()
        with patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_10(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=env)
        return conn, mock_re

    def test_writes_settlement_completed_per_game(self):
        _, mock_re = self._run()
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert event_types.count("settlement_completed") == 2

    def test_updates_game_status_to_settled(self):
        conn, _ = self._run()
        game_updates = [c for c in conn.cursors if any("UPDATE" in s.upper() and "oracle_game_analyses" in s.lower() for s in c.sql_log)]
        for c in game_updates:
            assert "settled" in c.params_log[0]

    def test_updates_slate_status_to_settled(self):
        conn, _ = self._run()
        slate_updates = [c for c in conn.cursors if any("UPDATE" in s.upper() and "oracle_slate_runs" in s.lower() for s in c.sql_log)]
        assert len(slate_updates) == 1
        assert "settled" in slate_updates[0].params_log[0]

    def test_commits_exactly_once(self):
        conn, _ = self._run()
        assert conn.commit_count == 1

    def test_does_not_rollback(self):
        conn, _ = self._run()
        assert not conn.rollback_called


# ---------------------------------------------------------------------------
# S. Event ordering and correctness
# ---------------------------------------------------------------------------

class TestEventOrderingAndCorrectness:
    """S — Cross-stage event ordering, counts, and type correctness."""

    def test_stage1_writes_only_slate_initialized(self):
        conn = _StageConn()
        with patch(_PATCH_GENERATE_SLATE, return_value=_TEST_SLATE_ID), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_1(conn, _TEST_DATE, env=_ENABLED_ENV)
        assert mock_re.call_count == 1
        assert mock_re.call_args[0][1] == "slate_initialized"

    def test_stage2_writes_exactly_three_events_for_two_fixtures(self):
        conn = _StageConn()
        with patch(_PATCH_LOAD_FIXTURES, return_value=_FIXTURE_RECORDS), \
             patch(_PATCH_VALIDATE_FIXTURE), \
             patch(_PATCH_GET_GAME_PK, side_effect=lambda r: int(r["external_game_id"])), \
             patch(_PATCH_GENERATE_GAME, side_effect=lambda s, a, h, pk: f"{s}-{a}-{h}-{pk}"), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_2(conn, _TEST_SLATE_ID, env=_ENABLED_ENV)
        assert mock_re.call_count == 3

    def test_stage2_schedule_retrieved_is_event_index_0(self):
        conn = _StageConn()
        with patch(_PATCH_LOAD_FIXTURES, return_value=_FIXTURE_RECORDS), \
             patch(_PATCH_VALIDATE_FIXTURE), \
             patch(_PATCH_GET_GAME_PK, side_effect=lambda r: int(r["external_game_id"])), \
             patch(_PATCH_GENERATE_GAME, side_effect=lambda s, a, h, pk: f"{s}-{a}-{h}-{pk}"), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_2(conn, _TEST_SLATE_ID, env=_ENABLED_ENV)
        assert mock_re.call_args_list[0][0][1] == "schedule_retrieved"

    def test_stage3_writes_preliminary_data_gathered_per_game(self):
        conn = _StageConn()
        with patch(_PATCH_GATHER_PRELIMINARY_DATA, return_value=_GATHER_AVAILABLE_RESPONSE), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_3(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        assert mock_re.call_count == 2
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert all(et == "preliminary_data_gathered" for et in event_types)

    def test_stage4_writes_exactly_two_events(self):
        conn = _StageConn()
        with patch(_PATCH_FETCH_PRELIMINARY_RECORD, return_value=_TEST_PRELIMINARY_ROW), \
             patch(_PATCH_INSERT_ECF_RESULT), \
             patch("backend.oracle.orchestrator._insert_lifecycle_audit"), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_4(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        assert mock_re.call_count == 2

    def _run_stage5(self, mock_re_name="mock_re"):
        conn = _StageConn()
        first_pitch = datetime(2026, 7, 25, 17, 10, tzinfo=timezone.utc)
        with patch(_PATCH_LOAD_POLICY, return_value=_FakePolicy()), \
             patch(_PATCH_FETCH_ECF, side_effect=lambda c, grid: _fake_ecf_row(grid)), \
             patch(_PATCH_FETCH_FIRST_PITCH, return_value=first_pitch), \
             patch(_PATCH_FETCH_PAYLOAD, return_value={"home_pitcher": "A", "away_pitcher": "B"}), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_5(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        return conn, mock_re

    def test_stage5_writes_one_completion_event_per_game(self):
        _, mock_re = self._run_stage5()
        assert mock_re.call_count == 2

    def test_stage5_emits_only_multi_model_completion_event(self):
        _, mock_re = self._run_stage5()
        seen = {c[0][1] for c in mock_re.call_args_list}
        assert seen == {"multi_model_analysis_completed"}


# ---------------------------------------------------------------------------
# T. Transaction ownership
# ---------------------------------------------------------------------------

class TestTransactionOwnership:
    """T — Orchestrator owns commit; WP-3/WP-5 must not commit (DCR-W5-001 §6-8)."""

    def test_stage1_connection_autocommit_remains_false_after_run(self):
        conn = _StageConn()
        with patch(_PATCH_GENERATE_SLATE, return_value=_TEST_SLATE_ID), \
             patch(_PATCH_RECORD_EVENT, return_value=1):
            run_stage_1(conn, _TEST_DATE, env=_ENABLED_ENV)
        assert conn.autocommit is False

    def test_stage2_connection_autocommit_remains_false_after_run(self):
        conn = _StageConn()
        with patch(_PATCH_LOAD_FIXTURES, return_value=_FIXTURE_RECORDS), \
             patch(_PATCH_VALIDATE_FIXTURE), \
             patch(_PATCH_GET_GAME_PK, side_effect=lambda r: int(r["external_game_id"])), \
             patch(_PATCH_GENERATE_GAME, side_effect=lambda s, a, h, pk: f"{s}-{a}-{h}-{pk}"), \
             patch(_PATCH_RECORD_EVENT, return_value=1):
            run_stage_2(conn, _TEST_SLATE_ID, env=_ENABLED_ENV)
        assert conn.autocommit is False

    def test_stage1_commits_after_update_not_before(self):
        """UPDATE must precede commit — verify at least one cursor exists before commit."""
        conn = _StageConn()
        commit_call_order = []
        original_commit = conn.commit

        def tracking_commit():
            commit_call_order.append(("commit", len(conn.cursors)))
            original_commit()

        conn.commit = tracking_commit
        with patch(_PATCH_GENERATE_SLATE, return_value=_TEST_SLATE_ID), \
             patch(_PATCH_RECORD_EVENT, return_value=1):
            run_stage_1(conn, _TEST_DATE, env=_ENABLED_ENV)
        assert commit_call_order[0][1] >= 2

    def test_stage3_commits_separately_from_stage4(self):
        conn = _StageConn()
        with patch(_PATCH_GATHER_PRELIMINARY_DATA, return_value=_GATHER_AVAILABLE_RESPONSE), \
             patch(_PATCH_RECORD_EVENT, return_value=1):
            run_stage_3(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        commit_after_stage3 = conn.commit_count
        with patch(_PATCH_RECORD_EVENT, return_value=1):
            run_stage_4(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        assert conn.commit_count == commit_after_stage3 + 1

    def test_stage1_does_not_close_connection(self):
        conn = _StageConn()
        with patch(_PATCH_GENERATE_SLATE, return_value=_TEST_SLATE_ID), \
             patch(_PATCH_RECORD_EVENT, return_value=1):
            run_stage_1(conn, _TEST_DATE, env=_ENABLED_ENV)
        assert conn.close_count == 0

    def test_stage2_does_not_close_connection(self):
        conn = _StageConn()
        with patch(_PATCH_LOAD_FIXTURES, return_value=_FIXTURE_RECORDS), \
             patch(_PATCH_VALIDATE_FIXTURE), \
             patch(_PATCH_GET_GAME_PK, side_effect=lambda r: int(r["external_game_id"])), \
             patch(_PATCH_GENERATE_GAME, side_effect=lambda s, a, h, pk: f"{s}-{a}-{h}-{pk}"), \
             patch(_PATCH_RECORD_EVENT, return_value=1):
            run_stage_2(conn, _TEST_SLATE_ID, env=_ENABLED_ENV)
        assert conn.close_count == 0

    def test_all_stage_cursors_are_closed(self):
        """Verify try/finally cursor close in _update_slate_status and _update_game_status."""
        conn = _StageConn()
        with patch(_PATCH_RECORD_EVENT, return_value=1):
            run_stage_7(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        assert all(c.closed for c in conn.cursors)

    def test_stage10_closes_all_cursors(self):
        conn = _StageConn()
        with patch(_PATCH_RECORD_EVENT, return_value=1):
            run_stage_10(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        assert all(c.closed for c in conn.cursors)


# ---------------------------------------------------------------------------
# U. Failure and kill switch propagation
# ---------------------------------------------------------------------------

class TestFailureAndKillSwitchPropagation:
    """U — Exceptions propagate unchanged; kill switch raises before DB ops."""

    def test_stage1_kill_switch_raises_before_generate_slate_run_id(self):
        conn = _StageConn()
        with patch(_PATCH_GENERATE_SLATE) as mock_gs:
            with pytest.raises(KillSwitchHaltError):
                run_stage_1(conn, _TEST_DATE, env=_DISABLED_ENV)
        mock_gs.assert_not_called()

    def test_stage2_kill_switch_raises_before_load_fixtures(self):
        with patch(_PATCH_LOAD_FIXTURES) as mock_lf:
            with pytest.raises(KillSwitchHaltError):
                run_stage_2(_StageConn(), _TEST_SLATE_ID, env=_DISABLED_ENV)
        mock_lf.assert_not_called()

    def test_stage4_kill_switch_raises_before_record_event(self):
        with patch(_PATCH_RECORD_EVENT) as mock_re:
            with pytest.raises(KillSwitchHaltError):
                run_stage_4(_StageConn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)
        mock_re.assert_not_called()

    def test_stage5_kill_switch_raises_before_record_event(self):
        with patch(_PATCH_RECORD_EVENT) as mock_re:
            with pytest.raises(KillSwitchHaltError):
                run_stage_5(_StageConn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)
        mock_re.assert_not_called()

    def test_stage8_kill_switch_raises_before_record_event(self):
        with patch(_PATCH_RECORD_EVENT) as mock_re:
            with pytest.raises(KillSwitchHaltError):
                run_stage_8(_StageConn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)
        mock_re.assert_not_called()

    def test_stage1_runtime_error_propagates_unchanged(self):
        conn = _StageConn()
        with patch(_PATCH_GENERATE_SLATE, side_effect=RuntimeError("sentinel")):
            with pytest.raises(RuntimeError, match="sentinel"):
                run_stage_1(conn, _TEST_DATE, env=_ENABLED_ENV)

    def test_kill_switch_halt_error_is_catchable_as_orchestrator_error(self):
        with pytest.raises(OrchestratorError):
            run_stage_1(_StageConn(), _TEST_DATE, env=_DISABLED_ENV)

    def test_stage1_insert_exception_does_not_commit(self):
        conn = _StageConn()
        with patch(_PATCH_GENERATE_SLATE, return_value=_TEST_SLATE_ID), \
             patch(_PATCH_RECORD_EVENT, side_effect=Exception("record_event failed")):
            with pytest.raises(Exception):
                run_stage_1(conn, _TEST_DATE, env=_ENABLED_ENV)
        assert not conn.commit_called


# ---------------------------------------------------------------------------
# V. Integration tests — full Phase 1 run (requires ORACLE_TEST_DATABASE_URL)
# ---------------------------------------------------------------------------

class TestIntegrationFullPhase1Run:
    """V — End-to-end Phase 1 run against a real PostgreSQL schema."""

    @pytest.fixture(autouse=True)
    def _fixed_pipeline_clock(self):
        """Pin the Orchestrator clock to a deterministic instant before every fixture cutoff.

        Stage 8 now applies a strict decision_time < scheduled_cutoff_at gate (PM-1067/1069/1071);
        with the fixed past-dated Phase-1 fixtures the pipeline would otherwise be unable to open
        the activation window at real wall-clock time. This controls time only; every assertion
        (slate/game reach 'settled', event counts) is unchanged and not weakened.
        """
        with patch("backend.oracle.orchestrator._now_utc", return_value=_PIPELINE_CLOCK):
            yield

    @pytest.fixture(autouse=True)
    def db_conn(self):
        """Open connection, yield, then delete all test records and close."""
        import psycopg2
        conn = psycopg2.connect(_TEST_DB_URL)
        conn.autocommit = False
        yield conn
        conn.rollback()
        cur = conn.cursor()
        try:
            cur.execute("TRUNCATE oracle_play_events")
            cur.execute("TRUNCATE oracle_preliminary_data")
            cur.execute("TRUNCATE oracle_lifecycle_audit")
            # Per-run Oracle result tables must be cleared for test isolation. Stage 8 now applies
            # a deterministic clock (see _fixed_pipeline_clock), so clock-derived ids (e.g.
            # oracle_ecf_results.ecf_result_id) are identical across runs and would otherwise
            # collide on re-run. TRUNCATE bypasses the append-only row triggers (UPDATE/DELETE only).
            cur.execute(
                "TRUNCATE oracle_ecf_results, oracle_stage5_results, oracle_preliminary_outputs, "
                "oracle_scheduled_cutoffs, oracle_lineup_observations, "
                "oracle_stage7_final_analysis, oracle_stage8_activation_window"
            )
            cur.execute("DELETE FROM oracle_game_analyses WHERE slate_run_id LIKE 'ORACLE-20260725-%'")
            cur.execute("DELETE FROM oracle_slate_runs WHERE slate_run_id LIKE 'ORACLE-20260725-%'")
        finally:
            cur.close()
        conn.commit()
        conn.close()

    @_requires_db
    def test_run_oracle_phase1_returns_slate_run_id(self, db_conn):
        result = run_oracle_phase1(db_conn, _TEST_DATE, env=_ENABLED_ENV)
        assert isinstance(result, str)
        assert result.startswith("ORACLE-20260725-")

    @_requires_db
    def test_slate_run_id_matches_oracle_format(self, db_conn):
        import re
        result = run_oracle_phase1(db_conn, _TEST_DATE, env=_ENABLED_ENV)
        assert re.match(r"^ORACLE-\d{8}-\d{3}$", result)

    @_requires_db
    def test_oracle_slate_runs_record_exists_after_run(self, db_conn):
        slate_id = run_oracle_phase1(db_conn, _TEST_DATE, env=_ENABLED_ENV)
        cur = db_conn.cursor()
        try:
            cur.execute("SELECT run_status FROM oracle_slate_runs WHERE slate_run_id = %s", (slate_id,))
            row = cur.fetchone()
        finally:
            cur.close()
        assert row is not None

    @_requires_db
    def test_slate_final_status_is_settled(self, db_conn):
        slate_id = run_oracle_phase1(db_conn, _TEST_DATE, env=_ENABLED_ENV)
        cur = db_conn.cursor()
        try:
            cur.execute("SELECT run_status FROM oracle_slate_runs WHERE slate_run_id = %s", (slate_id,))
            row = cur.fetchone()
        finally:
            cur.close()
        assert row[0] == "settled"

    @_requires_db
    def test_oracle_game_analyses_two_records_created(self, db_conn):
        slate_id = run_oracle_phase1(db_conn, _TEST_DATE, env=_ENABLED_ENV)
        cur = db_conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM oracle_game_analyses WHERE slate_run_id = %s", (slate_id,))
            count = cur.fetchone()[0]
        finally:
            cur.close()
        assert count == 2

    @_requires_db
    def test_game_final_status_is_settled(self, db_conn):
        slate_id = run_oracle_phase1(db_conn, _TEST_DATE, env=_ENABLED_ENV)
        cur = db_conn.cursor()
        try:
            cur.execute(
                "SELECT game_status FROM oracle_game_analyses WHERE slate_run_id = %s ORDER BY game_run_id",
                (slate_id,),
            )
            rows = cur.fetchall()
        finally:
            cur.close()
        assert all(r[0] == "settled" for r in rows)

    @_requires_db
    def test_slate_initialized_event_written(self, db_conn):
        slate_id = run_oracle_phase1(db_conn, _TEST_DATE, env=_ENABLED_ENV)
        cur = db_conn.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) FROM oracle_play_events WHERE slate_run_id = %s AND event_type = 'slate_initialized'",
                (slate_id,),
            )
            count = cur.fetchone()[0]
        finally:
            cur.close()
        assert count == 1

    @_requires_db
    def test_game_analysis_started_events_written_per_game(self, db_conn):
        slate_id = run_oracle_phase1(db_conn, _TEST_DATE, env=_ENABLED_ENV)
        cur = db_conn.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) FROM oracle_play_events WHERE slate_run_id = %s AND event_type = 'game_analysis_started'",
                (slate_id,),
            )
            count = cur.fetchone()[0]
        finally:
            cur.close()
        assert count == 2

    @_requires_db
    def test_settlement_completed_events_written_per_game(self, db_conn):
        slate_id = run_oracle_phase1(db_conn, _TEST_DATE, env=_ENABLED_ENV)
        cur = db_conn.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) FROM oracle_play_events WHERE slate_run_id = %s AND event_type = 'settlement_completed'",
                (slate_id,),
            )
            count = cur.fetchone()[0]
        finally:
            cur.close()
        assert count == 2

    @_requires_db
    def test_schedule_retrieved_event_written(self, db_conn):
        slate_id = run_oracle_phase1(db_conn, _TEST_DATE, env=_ENABLED_ENV)
        cur = db_conn.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) FROM oracle_play_events WHERE slate_run_id = %s AND event_type = 'schedule_retrieved'",
                (slate_id,),
            )
            count = cur.fetchone()[0]
        finally:
            cur.close()
        assert count == 1

    @_requires_db
    def test_run_blocked_when_kill_switch_disabled(self, db_conn):
        with pytest.raises(KillSwitchHaltError):
            run_oracle_phase1(db_conn, _TEST_DATE, env=_DISABLED_ENV)
        cur = db_conn.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) FROM oracle_slate_runs WHERE run_date = %s",
                (_TEST_DATE,),
            )
            count = cur.fetchone()[0]
        finally:
            cur.close()
        assert count == 0

    @_requires_db
    def test_daily_plays_activated_is_zero_after_run(self, db_conn):
        slate_id = run_oracle_phase1(db_conn, _TEST_DATE, env=_ENABLED_ENV)
        cur = db_conn.cursor()
        try:
            cur.execute(
                "SELECT daily_plays_activated FROM oracle_slate_runs WHERE slate_run_id = %s",
                (slate_id,),
            )
            val = cur.fetchone()[0]
        finally:
            cur.close()
        assert val == 0


# ===========================================================================
# W. Stage 4 — Inc-2 augmentation tests (PM-867)
# ===========================================================================

# ---------------------------------------------------------------------------
# W1. preliminary_analysis_failed state machine (Inc-2 Stage 4)
# ---------------------------------------------------------------------------

class TestGameStateMachinePreliminaryAnalysisFailedState:
    """W1 — preliminary_analysis_failed is a valid terminal game state (Inc-2 Stage 4)."""

    def test_preliminary_analysis_to_preliminary_analysis_failed_is_valid(self):
        result = transition_game_state("preliminary_analysis", "preliminary_analysis_failed")
        assert result == "preliminary_analysis_failed"

    def test_preliminary_analysis_failed_is_terminal(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("preliminary_analysis_failed", "lineup_monitoring")

    def test_preliminary_analysis_failed_cannot_go_to_settled(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("preliminary_analysis_failed", "settled")

    def test_preliminary_analysis_failed_cannot_go_to_scheduled(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("preliminary_analysis_failed", "scheduled")

    def test_scheduled_cannot_go_to_preliminary_analysis_failed(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("scheduled", "preliminary_analysis_failed")

    def test_lineup_monitoring_cannot_go_to_preliminary_analysis_failed(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("lineup_monitoring", "preliminary_analysis_failed")

    def test_error_message_identifies_terminal_state(self):
        with pytest.raises(InvalidStateTransitionError, match="terminal"):
            transition_game_state("preliminary_analysis_failed", "scheduled")

    def test_preliminary_analysis_still_reaches_lineup_monitoring(self):
        """Inc-2 addition must not break existing preliminary_analysis → lineup_monitoring."""
        result = transition_game_state("preliminary_analysis", "lineup_monitoring")
        assert result == "lineup_monitoring"


# ---------------------------------------------------------------------------
# W2. preliminary_analysis_failed event type registry
# ---------------------------------------------------------------------------

class TestPreliminaryAnalysisFailedEventType:
    """W2 — preliminary_analysis_failed is an approved event type (P-4b; PM-859)."""

    def test_preliminary_analysis_failed_is_accepted_by_record_event(self):
        from backend.oracle.event_store import _EVENT_TYPES
        assert "preliminary_analysis_failed" in _EVENT_TYPES

    def test_event_type_count_is_34(self):
        # Inc-3 P-4b (PM-1007 §5) adds multi_model_analysis_completed: 33 -> 34.
        from backend.oracle.event_store import _EVENT_TYPES
        assert len(_EVENT_TYPES) == 34

    def test_multi_model_analysis_completed_is_registered(self):
        from backend.oracle.event_store import _EVENT_TYPES
        assert "multi_model_analysis_completed" in _EVENT_TYPES

    def test_ecf_calculated_still_present(self):
        from backend.oracle.event_store import _EVENT_TYPES
        assert "ecf_calculated" in _EVENT_TYPES

    def test_data_gather_failed_still_present(self):
        from backend.oracle.event_store import _EVENT_TYPES
        assert "data_gather_failed" in _EVENT_TYPES

    def test_preliminary_data_gathered_still_present(self):
        from backend.oracle.event_store import _EVENT_TYPES
        assert "preliminary_data_gathered" in _EVENT_TYPES


# ---------------------------------------------------------------------------
# W3. Stage 4 — failure path integration with state machine
# ---------------------------------------------------------------------------

class TestStage4FailurePathStateMachine:
    """W3 — Stage 4 failure path uses valid state machine transition."""

    def test_preliminary_analysis_to_failed_transition_is_valid_for_failure_path(self):
        """The failure path calls transition_game_state with this pair; it must not raise."""
        result = transition_game_state("preliminary_analysis", "preliminary_analysis_failed")
        assert result == "preliminary_analysis_failed"


# ---------------------------------------------------------------------------
# W4. Stage 4 — kill switch precedes DB fetch
# ---------------------------------------------------------------------------

class TestStage4KillSwitchPrecedesFetch:
    """W4 — Stage 4 kill switch check precedes _fetch_preliminary_record."""

    def test_stage4_kill_switch_raises_before_fetch(self):
        with patch(_PATCH_FETCH_PRELIMINARY_RECORD) as mock_fetch:
            with pytest.raises(KillSwitchHaltError):
                run_stage_4(_StageConn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)
        mock_fetch.assert_not_called()
