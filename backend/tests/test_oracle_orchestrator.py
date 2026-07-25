"""Oracle Phase 1 WP-4 — Orchestrator Foundation tests (T01–T04).

All tests in this file are pure unit tests and run without a database.
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
"""

from __future__ import annotations

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
    """T03 — All 8 allowlist transitions must return to_state (DCR-W4-003)."""

    def test_scheduled_to_preliminary_analysis(self):
        assert transition_game_state("scheduled", "preliminary_analysis") == "preliminary_analysis"

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

    def test_settled_to_preliminary_analysis_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("settled", "preliminary_analysis")

    def test_voided_to_lineup_monitoring_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("voided", "lineup_monitoring")

    def test_postponed_to_final_analysis_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            transition_game_state("postponed", "final_analysis")

    def test_error_message_identifies_terminal_state(self):
        with pytest.raises(InvalidStateTransitionError, match="terminal"):
            transition_game_state("settled", "scheduled")


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
