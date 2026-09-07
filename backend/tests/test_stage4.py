"""Stage 4 — Structural ECF v1 Engine unit tests (PM-867).

Tests compute_ecf(), component-score helpers, ECFResult contract, and the
Stage 4 orchestrator path via patched DB helpers.

Sections:
    A. ECFResult dataclass contract
    B. compute_ecf — score range and formula
    C. _compute_data_completeness
    D. _compute_data_freshness
    E. _compute_data_payload_density
    F. compute_ecf — computed_at parameter
    G. Stage 4 orchestrator — success path (patched DB)
    H. Stage 4 orchestrator — failure path (preliminary_analysis_failed)
    I. Stage 4 orchestrator — games without preliminary data (skip)
    J. Stage 4 orchestrator — kill switch
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, call, patch

import pytest

from backend.oracle.stage4_ecf import (
    FRESHNESS_WINDOW_SECONDS,
    MIN_EXPECTED_FIELDS,
    MODEL_VERSION,
    ECFComponentScores,
    ECFResult,
    _compute_data_completeness,
    _compute_data_freshness,
    _compute_data_payload_density,
    compute_ecf,
)
from backend.oracle.orchestrator import (
    KillSwitchHaltError,
    run_stage_4,
)
from backend.oracle.state_machines import InvalidStateTransitionError


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

_ENABLED_ENV = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "true"}
_DISABLED_ENV: dict = {}
_TEST_SLATE_ID = "ORACLE-20260725-001"
_TEST_GAME_IDS = [
    "ORACLE-20260725-001-BOS-NYY-746484",
    "ORACLE-20260725-001-SFG-LAD-746485",
]
_GATHERED_AT = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
_REFERENCE_TIME = datetime(2026, 7, 25, 13, 0, tzinfo=timezone.utc)  # 1 hour after gather
_TEST_DV_ID = "DV-test-0"
_DUMMY_COMPONENTS = ECFComponentScores(
    data_completeness=0.0,
    data_freshness=0.0,
    data_payload_density=0.0,
)
_DUMMY_RESULT = ECFResult(
    ecf_result_id="ECFR-test-0",
    ecf_score=0.5,
    components=_DUMMY_COMPONENTS,
    model_version=MODEL_VERSION,
    computed_at=_REFERENCE_TIME,
    data_version_id=_TEST_DV_ID,
)

_PATCH_RECORD_EVENT = "backend.oracle.orchestrator.record_event"
_PATCH_FETCH = "backend.oracle.orchestrator._fetch_preliminary_record"
_PATCH_INSERT_ECF = "backend.oracle.orchestrator._insert_ecf_result"
_PATCH_INSERT_AUDIT = "backend.oracle.orchestrator._insert_lifecycle_audit"
_PATCH_TRANSITION_GAME = "backend.oracle.orchestrator.transition_game_state"
_PATCH_UPDATE_GAME_STATUS = "backend.oracle.orchestrator._update_game_status"
_PATCH_COMPUTE_ECF = "backend.oracle.orchestrator.compute_ecf"

_FULL_PAYLOAD = {
    "gameData": {"status": {"abstractGameState": "Live"}},
    "liveData": {"plays": {"currentPlay": {}}},
    "teams": {"home": "NYY", "away": "BOS"},
    "venue": "Yankee Stadium",
    "weather": {"condition": "Clear"},
}

_EMPTY_PAYLOAD: dict = {}


class _MockCursor:
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
    def __init__(self) -> None:
        self.autocommit = False
        self.cursors: list[_MockCursor] = []
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self) -> _MockCursor:
        cur = _MockCursor()
        self.cursors.append(cur)
        return cur

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    @property
    def commit_called(self) -> bool:
        return self.commit_count > 0


# ---------------------------------------------------------------------------
# A. EcfResult dataclass contract
# ---------------------------------------------------------------------------

class TestEcfResultDataclass:
    """A — ECFResult frozen dataclass invariants."""

    def test_ecf_result_is_importable(self):
        assert ECFResult is not None

    def test_ecf_result_is_frozen(self):
        with pytest.raises(Exception):
            _DUMMY_RESULT.ecf_score = 0.9  # type: ignore[misc]

    def test_ecf_result_stores_score(self):
        result = ECFResult(
            ecf_result_id="ECFR-test-1",
            ecf_score=0.75,
            components=_DUMMY_COMPONENTS,
            model_version=MODEL_VERSION,
            computed_at=_REFERENCE_TIME,
            data_version_id=_TEST_DV_ID,
        )
        assert result.ecf_score == 0.75

    def test_ecf_result_stores_components(self):
        comps = ECFComponentScores(
            data_completeness=1.0,
            data_freshness=0.5,
            data_payload_density=0.8,
        )
        result = ECFResult(
            ecf_result_id="ECFR-test-2",
            ecf_score=0.77,
            components=comps,
            model_version=MODEL_VERSION,
            computed_at=_REFERENCE_TIME,
            data_version_id=_TEST_DV_ID,
        )
        assert result.components == comps

    def test_ecf_result_stores_model_version(self):
        assert _DUMMY_RESULT.model_version == MODEL_VERSION

    def test_model_version_constant_value(self):
        assert MODEL_VERSION == "structural-ecf-v1"

    def test_freshness_window_constant_value(self):
        assert FRESHNESS_WINDOW_SECONDS == 14400

    def test_min_expected_fields_constant_value(self):
        assert MIN_EXPECTED_FIELDS == 5


# ---------------------------------------------------------------------------
# B. compute_ecf — score range and formula
# ---------------------------------------------------------------------------

class TestComputeEcfScoreRange:
    """B — ecf_score must be in [0.0, 1.0] and formula is applied correctly."""

    def test_returns_ecf_result_type(self):
        result = compute_ecf(_TEST_GAME_IDS[0], _TEST_DV_ID, _FULL_PAYLOAD, _GATHERED_AT, _REFERENCE_TIME)
        assert isinstance(result, ECFResult)

    def test_ecf_score_is_float(self):
        result = compute_ecf(_TEST_GAME_IDS[0], _TEST_DV_ID, _FULL_PAYLOAD, _GATHERED_AT, _REFERENCE_TIME)
        assert isinstance(result.ecf_score, float)

    def test_ecf_score_minimum_is_zero(self):
        result = compute_ecf(_TEST_GAME_IDS[0], _TEST_DV_ID, _EMPTY_PAYLOAD, _GATHERED_AT, _REFERENCE_TIME)
        assert result.ecf_score >= 0.0

    def test_ecf_score_maximum_is_one(self):
        very_fresh = datetime.now(tz=timezone.utc) + timedelta(seconds=1)
        computed = datetime.now(tz=timezone.utc)
        result = compute_ecf(_TEST_GAME_IDS[0], _TEST_DV_ID, _FULL_PAYLOAD, very_fresh, computed)
        assert result.ecf_score <= 1.0

    def test_ecf_score_capped_at_one(self):
        """All components at 1.0 should give ecf_score = 1.0, not 1.0 * (0.4+0.3+0.3) > 1."""
        huge_payload = {str(i): i for i in range(100)}
        just_now = datetime.now(tz=timezone.utc)
        result = compute_ecf(_TEST_GAME_IDS[0], _TEST_DV_ID, huge_payload, just_now, just_now)
        assert result.ecf_score <= 1.0

    def test_empty_payload_gives_zero_completeness_and_density(self):
        result = compute_ecf(_TEST_GAME_IDS[0], _TEST_DV_ID, _EMPTY_PAYLOAD, _GATHERED_AT, _REFERENCE_TIME)
        assert result.components.data_completeness == 0.0
        assert result.components.data_payload_density == 0.0

    def test_components_is_ecf_component_scores(self):
        result = compute_ecf(_TEST_GAME_IDS[0], _TEST_DV_ID, _FULL_PAYLOAD, _GATHERED_AT, _REFERENCE_TIME)
        assert isinstance(result.components, ECFComponentScores)

    def test_model_version_is_structural_ecf_v1(self):
        result = compute_ecf(_TEST_GAME_IDS[0], _TEST_DV_ID, _FULL_PAYLOAD, _GATHERED_AT, _REFERENCE_TIME)
        assert result.model_version == "structural-ecf-v1"

    def test_formula_applied_correctly_known_values(self):
        """Verify formula with all-1.0 components gives min(1.0, 1.0)."""
        just_now = datetime.now(tz=timezone.utc)
        large_payload = {str(i): i + 1 for i in range(10)}  # 10 fields, all non-empty
        result = compute_ecf(_TEST_GAME_IDS[0], _TEST_DV_ID, large_payload, just_now, just_now)
        # completeness = 10/10 = 1.0 (non_empty/max(total,1); all 10 fields non-empty)
        # freshness = 1.0 (age=0)
        # density = min(1.0, 10/5) = 1.0
        # ecf = min(1.0, 1.0*0.4 + 1.0*0.3 + 1.0*0.3) = min(1.0, 1.0) = 1.0
        assert result.ecf_score == pytest.approx(1.0)

    def test_formula_applied_correctly_partial_values(self):
        """Five fields, 1-hour-old, all non-empty: completeness=1.0, density=1.0."""
        payload = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
        gathered = _REFERENCE_TIME - timedelta(hours=1)
        result = compute_ecf(_TEST_GAME_IDS[0], _TEST_DV_ID, payload, gathered, _REFERENCE_TIME)
        # completeness = 5/5 = 1.0 (non_empty/max(total,1); all 5 non-empty)
        # freshness = max(0.0, 1.0 - 3600/14400) = max(0.0, 0.75) = 0.75
        # density = min(1.0, 5/5) = 1.0
        # ecf = min(1.0, 1.0*0.4 + 0.75*0.3 + 1.0*0.3) = min(1.0, 0.4+0.225+0.3) = 0.925
        assert result.ecf_score == pytest.approx(0.925)


# ---------------------------------------------------------------------------
# C. _compute_data_completeness
# ---------------------------------------------------------------------------

class TestComputeDataCompleteness:
    """C — data_completeness = non_empty_count / max(total_count, 1); non-empty ≡ not None and not ""."""

    def test_empty_dict_returns_zero(self):
        assert _compute_data_completeness({}) == 0.0

    def test_non_dict_returns_zero(self):
        assert _compute_data_completeness(None) == 0.0  # type: ignore[arg-type]
        assert _compute_data_completeness("string") == 0.0  # type: ignore[arg-type]
        assert _compute_data_completeness([]) == 0.0  # type: ignore[arg-type]

    def test_partial_completeness_with_mixed_values(self):
        # C formula: only None and "" excluded; 2 of 4 fields non-empty
        payload = {"a": 1, "b": None, "c": "x", "d": ""}
        assert _compute_data_completeness(payload) == pytest.approx(0.5)

    def test_exactly_min_fields_returns_one(self):
        payload = {str(i): i for i in range(MIN_EXPECTED_FIELDS)}
        assert _compute_data_completeness(payload) == pytest.approx(1.0)

    def test_more_than_min_fields_capped_at_one(self):
        payload = {str(i): i for i in range(MIN_EXPECTED_FIELDS * 3)}
        assert _compute_data_completeness(payload) == pytest.approx(1.0)

    def test_one_non_empty_field_returns_full_completeness(self):
        # 1 non-empty / max(1, 1) = 1.0
        assert _compute_data_completeness({"a": 1}) == pytest.approx(1.0)

    def test_list_and_dict_values_count_as_non_empty(self):
        # PM-855 §3.4: only None and "" are excluded; [] and {} ARE non-empty
        payload = {"a": [], "b": {}, "c": None, "d": ""}
        assert _compute_data_completeness(payload) == pytest.approx(0.5)

    def test_result_in_zero_to_one_range(self):
        for n in range(0, 20):
            payload = {str(i): i for i in range(n)}
            result = _compute_data_completeness(payload)
            assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# D. _compute_data_freshness
# ---------------------------------------------------------------------------

class TestComputeDataFreshness:
    """D — data_freshness = max(0.0, 1.0 - age_seconds/FRESHNESS_WINDOW_SECONDS)."""

    def test_age_zero_returns_one(self):
        t = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        assert _compute_data_freshness(t, t) == pytest.approx(1.0)

    def test_future_gathered_at_returns_one(self):
        ref = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        future = ref + timedelta(seconds=100)
        assert _compute_data_freshness(future, ref) == pytest.approx(1.0)

    def test_exactly_at_window_boundary_returns_zero(self):
        ref = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        old = ref - timedelta(seconds=FRESHNESS_WINDOW_SECONDS)
        assert _compute_data_freshness(old, ref) == pytest.approx(0.0)

    def test_beyond_window_clamped_to_zero(self):
        ref = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        very_old = ref - timedelta(seconds=FRESHNESS_WINDOW_SECONDS * 2)
        assert _compute_data_freshness(very_old, ref) == pytest.approx(0.0)

    def test_halfway_through_window_returns_half(self):
        ref = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        half_window = ref - timedelta(seconds=FRESHNESS_WINDOW_SECONDS / 2)
        assert _compute_data_freshness(half_window, ref) == pytest.approx(0.5)

    def test_one_hour_old_returns_correct_value(self):
        ref = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        one_hour_ago = ref - timedelta(hours=1)
        # 3600 / 14400 = 0.25; result = 0.75
        assert _compute_data_freshness(one_hour_ago, ref) == pytest.approx(0.75)

    def test_naive_gathered_at_treated_as_utc(self):
        ref = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        naive = datetime(2026, 7, 25, 11, 0)  # naive, 1 hour before ref
        result = _compute_data_freshness(naive, ref)
        assert result == pytest.approx(0.75)

    def test_result_in_zero_to_one_range(self):
        ref = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        for hours_ago in [0, 1, 2, 3, 4, 5, 10]:
            gathered = ref - timedelta(hours=hours_ago)
            result = _compute_data_freshness(gathered, ref)
            assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# E. _compute_data_payload_density
# ---------------------------------------------------------------------------

class TestComputeDataPayloadDensity:
    """E — data_payload_density = min(1.0, field_count / MIN_EXPECTED_FIELDS)."""

    def test_empty_dict_returns_zero(self):
        assert _compute_data_payload_density({}) == 0.0

    def test_non_dict_returns_zero(self):
        assert _compute_data_payload_density(None) == 0.0  # type: ignore[arg-type]
        assert _compute_data_payload_density("string") == 0.0  # type: ignore[arg-type]

    def test_fewer_than_min_fields_returns_partial(self):
        # 4 fields: min(1.0, 4/5) = 0.8
        payload = {"a": 1, "b": 2, "c": 3, "d": 4}
        assert _compute_data_payload_density(payload) == pytest.approx(0.8)

    def test_exactly_min_fields_returns_one(self):
        payload = {str(i): i for i in range(MIN_EXPECTED_FIELDS)}
        assert _compute_data_payload_density(payload) == pytest.approx(1.0)

    def test_more_than_min_fields_capped_at_one(self):
        payload = {str(i): i for i in range(MIN_EXPECTED_FIELDS * 3)}
        assert _compute_data_payload_density(payload) == pytest.approx(1.0)

    def test_one_field_returns_correct_fraction(self):
        # 1 field: min(1.0, 1/5) = 0.2
        assert _compute_data_payload_density({"a": 1}) == pytest.approx(1.0 / MIN_EXPECTED_FIELDS)

    def test_field_values_do_not_affect_density(self):
        # D depends only on field count, not value content
        sparse = {"a": None, "b": None, "c": None, "d": None, "e": None}
        assert _compute_data_payload_density(sparse) == pytest.approx(1.0)

    def test_result_in_zero_to_one_range(self):
        payload = {"a": 1, "b": None, "c": "", "d": [1, 2]}
        result = _compute_data_payload_density(payload)
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# F. compute_ecf — computed_at parameter
# ---------------------------------------------------------------------------

class TestComputeEcfComputedAt:
    """F — computed_at controls freshness; ecf_result_id is generated from game_run_id."""

    def test_explicit_computed_at_does_not_raise(self):
        result = compute_ecf(_TEST_GAME_IDS[0], _TEST_DV_ID, _FULL_PAYLOAD, _GATHERED_AT, _REFERENCE_TIME)
        assert isinstance(result, ECFResult)

    def test_fresh_data_high_freshness_via_computed_at(self):
        """gathered_at == computed_at → freshness 1.0."""
        just_now = datetime.now(tz=timezone.utc)
        result = compute_ecf(_TEST_GAME_IDS[0], _TEST_DV_ID, _FULL_PAYLOAD, just_now, just_now)
        assert result.components.data_freshness > 0.95

    def test_old_data_low_freshness_via_computed_at(self):
        very_old = datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc)
        computed = datetime.now(tz=timezone.utc)
        result = compute_ecf(_TEST_GAME_IDS[0], _TEST_DV_ID, _FULL_PAYLOAD, very_old, computed)
        assert result.components.data_freshness == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# G. Stage 4 orchestrator — success path (patched DB)
# ---------------------------------------------------------------------------

_SUCCESS_ROW = (_FULL_PAYLOAD, _TEST_DV_ID, _GATHERED_AT)


class TestStage4OrchestratorSuccess:
    """G — Stage 4 success path: ECF computed, oracle_ecf_results inserted,
    lifecycle_audit inserted, ecf_calculated event recorded."""

    def _run(self, conn=None, game_ids=None, fetch_return=_SUCCESS_ROW):
        if conn is None:
            conn = _StageConn()
        if game_ids is None:
            game_ids = _TEST_GAME_IDS
        with patch(_PATCH_FETCH, return_value=fetch_return), \
             patch(_PATCH_INSERT_ECF) as mock_ecf, \
             patch(_PATCH_INSERT_AUDIT) as mock_audit, \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_4(conn, _TEST_SLATE_ID, game_ids, env=_ENABLED_ENV)
        return conn, mock_ecf, mock_audit, mock_re

    def test_inserts_ecf_result_per_game(self):
        _, mock_ecf, _, _ = self._run()
        assert mock_ecf.call_count == 2

    def test_inserts_lifecycle_audit_per_game(self):
        _, _, mock_audit, _ = self._run()
        assert mock_audit.call_count == 2

    def test_audit_stage_is_4(self):
        _, _, mock_audit, _ = self._run()
        for c in mock_audit.call_args_list:
            assert c[1]["stage"] == "4"

    def test_audit_event_is_ecf_calculated(self):
        _, _, mock_audit, _ = self._run()
        for c in mock_audit.call_args_list:
            assert c[1]["event"] == "ecf_calculated"

    def test_records_ecf_calculated_event_per_game(self):
        _, _, _, mock_re = self._run()
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert event_types.count("ecf_calculated") == 2

    def test_ecf_event_includes_game_run_id(self):
        _, _, _, mock_re = self._run()
        for c in mock_re.call_args_list:
            assert c[1].get("game_run_id") is not None

    def test_commits_exactly_once(self):
        conn, _, _, _ = self._run()
        assert conn.commit_count == 1

    def test_does_not_rollback(self):
        conn, _, _, _ = self._run()
        assert conn.rollback_count == 0

    def test_no_game_status_update_on_success(self):
        conn, _, _, _ = self._run()
        update_cursors = [
            c for c in conn.cursors
            if any("UPDATE" in s.upper() for s in c.sql_log)
        ]
        assert len(update_cursors) == 0

    def test_ecf_result_receives_data_version_id(self):
        _, mock_ecf, _, _ = self._run()
        for c in mock_ecf.call_args_list:
            assert c[1].get("data_version_id") == _TEST_DV_ID

    def test_ecf_result_receives_model_version(self):
        _, mock_ecf, _, _ = self._run()
        for c in mock_ecf.call_args_list:
            assert c[1].get("model_version") == MODEL_VERSION

    def test_ecf_result_score_in_valid_range(self):
        _, mock_ecf, _, _ = self._run()
        for c in mock_ecf.call_args_list:
            score = c[1].get("ecf_score")
            assert 0.0 <= score <= 1.0

    def test_single_game_produces_one_ecf_result(self):
        _, mock_ecf, _, _ = self._run(game_ids=[_TEST_GAME_IDS[0]])
        assert mock_ecf.call_count == 1


# ---------------------------------------------------------------------------
# H. Stage 4 orchestrator — failure path (preliminary_analysis_failed)
# ---------------------------------------------------------------------------

class TestStage4OrchestratorFailure:
    """H — Stage 4 failure path: ECF raises → preliminary_analysis_failed
    with dual-audit (oracle_play_events + oracle_lifecycle_audit)."""

    def _run_with_ecf_error(self, error=RuntimeError("ecf error")):
        conn = _StageConn()
        with patch(_PATCH_FETCH, return_value=_SUCCESS_ROW), \
             patch(_PATCH_COMPUTE_ECF, side_effect=error), \
             patch(_PATCH_INSERT_AUDIT) as mock_audit, \
             patch(_PATCH_TRANSITION_GAME) as mock_trans, \
             patch(_PATCH_UPDATE_GAME_STATUS) as mock_update, \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_4(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        return conn, mock_audit, mock_trans, mock_update, mock_re

    def test_records_preliminary_analysis_failed_event_per_game(self):
        _, _, _, _, mock_re = self._run_with_ecf_error()
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert event_types.count("preliminary_analysis_failed") == 2

    def test_dual_audit_oracle_play_events_written(self):
        _, _, _, _, mock_re = self._run_with_ecf_error()
        assert mock_re.call_count == 2

    def test_dual_audit_lifecycle_audit_written(self):
        _, mock_audit, _, _, _ = self._run_with_ecf_error()
        assert mock_audit.call_count == 2

    def test_audit_event_is_preliminary_analysis_failed(self):
        _, mock_audit, _, _, _ = self._run_with_ecf_error()
        for c in mock_audit.call_args_list:
            assert c[1]["event"] == "preliminary_analysis_failed"

    def test_audit_stage_is_4_on_failure(self):
        _, mock_audit, _, _, _ = self._run_with_ecf_error()
        for c in mock_audit.call_args_list:
            assert c[1]["stage"] == "4"

    def test_transitions_to_preliminary_analysis_failed(self):
        _, _, mock_trans, _, _ = self._run_with_ecf_error()
        for c in mock_trans.call_args_list:
            assert c[0] == ("preliminary_analysis", "preliminary_analysis_failed")

    def test_updates_game_status_to_preliminary_analysis_failed(self):
        _, _, _, mock_update, _ = self._run_with_ecf_error()
        for c in mock_update.call_args_list:
            assert c[0][2] == "preliminary_analysis_failed"

    def test_commits_exactly_once_on_failure(self):
        conn, _, _, _, _ = self._run_with_ecf_error()
        assert conn.commit_count == 1

    def test_error_detail_captured_in_audit(self):
        error = ValueError("test sentinel error")
        _, mock_audit, _, _, _ = self._run_with_ecf_error(error=error)
        details = [c[1].get("detail") for c in mock_audit.call_args_list]
        assert all("test sentinel error" in d for d in details)

    def test_failure_path_does_not_insert_ecf_result(self):
        conn = _StageConn()
        with patch(_PATCH_FETCH, return_value=_SUCCESS_ROW), \
             patch(_PATCH_COMPUTE_ECF, side_effect=RuntimeError("fail")), \
             patch(_PATCH_INSERT_ECF) as mock_ecf_insert, \
             patch(_PATCH_INSERT_AUDIT), \
             patch(_PATCH_TRANSITION_GAME), \
             patch(_PATCH_UPDATE_GAME_STATUS), \
             patch(_PATCH_RECORD_EVENT, return_value=1):
            run_stage_4(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        mock_ecf_insert.assert_not_called()


# ---------------------------------------------------------------------------
# I. Stage 4 orchestrator — games without preliminary data (skip)
# ---------------------------------------------------------------------------

class TestStage4OrchestratorSkipNoData:
    """I — Games without preliminary data (data_gather_failed) are silently skipped."""

    def test_no_events_written_when_all_games_have_no_data(self):
        conn = _StageConn()
        with patch(_PATCH_FETCH, return_value=None), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_4(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        assert mock_re.call_count == 0

    def test_still_commits_when_all_games_skipped(self):
        conn = _StageConn()
        with patch(_PATCH_FETCH, return_value=None), \
             patch(_PATCH_RECORD_EVENT, return_value=1):
            run_stage_4(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        assert conn.commit_count == 1

    def test_no_status_update_when_games_skipped(self):
        conn = _StageConn()
        with patch(_PATCH_FETCH, return_value=None), \
             patch(_PATCH_RECORD_EVENT, return_value=1):
            run_stage_4(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        update_cursors = [
            c for c in conn.cursors
            if any("UPDATE" in s.upper() for s in c.sql_log)
        ]
        assert len(update_cursors) == 0

    def test_empty_game_list_commits_once(self):
        conn = _StageConn()
        with patch(_PATCH_RECORD_EVENT, return_value=1):
            run_stage_4(conn, _TEST_SLATE_ID, [], env=_ENABLED_ENV)
        assert conn.commit_count == 1

    def test_mixed_some_have_data_some_dont(self):
        conn = _StageConn()
        call_count = 0

        def fetch_side_effect(c, game_run_id):
            nonlocal call_count
            call_count += 1
            return _SUCCESS_ROW if call_count == 1 else None

        with patch(_PATCH_FETCH, side_effect=fetch_side_effect), \
             patch(_PATCH_INSERT_ECF), \
             patch(_PATCH_INSERT_AUDIT), \
             patch(_PATCH_RECORD_EVENT, return_value=1) as mock_re:
            run_stage_4(conn, _TEST_SLATE_ID, _TEST_GAME_IDS, env=_ENABLED_ENV)
        event_types = [c[0][1] for c in mock_re.call_args_list]
        assert event_types.count("ecf_calculated") == 1


# ---------------------------------------------------------------------------
# J. Stage 4 orchestrator — kill switch
# ---------------------------------------------------------------------------

class TestStage4KillSwitch:
    """J — Kill switch raises KillSwitchHaltError before any work."""

    def test_raises_kill_switch_halt_error_when_disabled(self):
        with pytest.raises(KillSwitchHaltError):
            run_stage_4(_StageConn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)

    def test_kill_switch_raises_before_fetch(self):
        with patch(_PATCH_FETCH) as mock_fetch:
            with pytest.raises(KillSwitchHaltError):
                run_stage_4(_StageConn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)
        mock_fetch.assert_not_called()

    def test_kill_switch_raises_before_record_event(self):
        with patch(_PATCH_RECORD_EVENT) as mock_re:
            with pytest.raises(KillSwitchHaltError):
                run_stage_4(_StageConn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)
        mock_re.assert_not_called()

    def test_kill_switch_halt_error_is_orchestrator_error(self):
        from backend.oracle.orchestrator import OrchestratorError
        with pytest.raises(OrchestratorError):
            run_stage_4(_StageConn(), _TEST_SLATE_ID, _TEST_GAME_IDS, env=_DISABLED_ENV)
