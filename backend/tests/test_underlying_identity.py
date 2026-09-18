"""Offline unit tests for backend.oracle.underlying_identity (PM-1271).

Pure functions only — no DB, no network, no process-clock dependence.
Covers stable identity, content digest (retrieval-time independence),
window identity, expiry equality semantics, and local observation ordering.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.oracle import underlying_identity as ui


_UTC = timezone.utc


class TestMakeSui:
    def test_valid_mlb_sui(self):
        assert ui.make_sui(ui.SOURCE_NAMESPACE_MLB, 1, "746484") == ("mlb-statsapi", 1, "746484")

    def test_int_game_pk_is_normalized_to_string(self):
        assert ui.make_sui(ui.SOURCE_NAMESPACE_FIXTURE, 1, 746484) == ("fixture", 1, "746484")

    def test_non_numeric_game_pk_raises(self):
        with pytest.raises(ui.IdentityError):
            ui.make_sui(ui.SOURCE_NAMESPACE_MLB, 1, "74x")

    def test_empty_namespace_raises(self):
        with pytest.raises(ui.IdentityError):
            ui.make_sui("", 1, "1")

    def test_bool_sport_id_raises(self):
        with pytest.raises(ui.IdentityError):
            ui.make_sui(ui.SOURCE_NAMESPACE_MLB, True, "1")


class TestSuiStringAndOrdering:
    def test_sui_string(self):
        assert ui.sui_string(("mlb-statsapi", 1, "746484")) == "mlb-statsapi:1:746484"

    def test_advisory_lock_key_prefixed(self):
        assert ui.advisory_lock_key(("mlb-statsapi", 1, "1")) == "sui:mlb-statsapi:1:1"

    def test_canonical_sort_is_deterministic(self):
        suis = [("mlb-statsapi", 1, "9"), ("fixture", 1, "1"), ("mlb-statsapi", 1, "10")]
        ordered = sorted(suis, key=ui.sui_string)
        # lexical order over the string form
        assert [ui.sui_string(s) for s in ordered] == sorted(ui.sui_string(s) for s in suis)

    def test_fixture_and_live_namespaces_never_collide(self):
        assert ui.sui_string(("fixture", 1, "746484")) != ui.sui_string(("mlb-statsapi", 1, "746484"))


class TestParseGamePk:
    def test_parses_trailing_game_pk(self):
        gr = "ORACLE-20260725-001-BOS-NYY-746484"
        assert ui.parse_game_pk_from_game_run_id(gr) == "746484"

    def test_unparseable_returns_none(self):
        assert ui.parse_game_pk_from_game_run_id("no-trailing-number-x") is None

    def test_non_string_returns_none(self):
        assert ui.parse_game_pk_from_game_run_id(None) is None


class TestNormalizeUtcIso:
    def test_aware_utc(self):
        dt = datetime(2026, 7, 25, 17, 10, tzinfo=_UTC)
        assert ui.normalize_utc_iso(dt) == "2026-07-25T17:10:00Z"

    def test_offset_converted_to_utc(self):
        dt = datetime(2026, 7, 25, 13, 10, tzinfo=timezone(timedelta(hours=-4)))
        assert ui.normalize_utc_iso(dt) == "2026-07-25T17:10:00Z"

    def test_naive_raises(self):
        with pytest.raises(ui.IdentityError):
            ui.normalize_utc_iso(datetime(2026, 7, 25, 17, 10))


class TestContentDigest:
    def _digest(self, **overrides):
        base = dict(
            source_namespace="mlb-statsapi", sport_id=1, game_pk="746484",
            away_team="BOS", home_team="NYY",
            scheduled_start_at=datetime(2026, 7, 25, 17, 10, tzinfo=_UTC),
            game_status="scheduled", source_game_date="2026-07-25",
        )
        base.update(overrides)
        return ui.content_digest(**base)

    def test_deterministic(self):
        assert self._digest() == self._digest()

    def test_prefixed(self):
        assert self._digest().startswith("SC-")

    def test_retrieval_time_is_not_a_parameter_so_identical_content_matches(self):
        # Two "observations" of identical content differ only by retrieval time,
        # which is not part of the digest — so digests are equal.
        assert self._digest() == self._digest()

    def test_different_start_changes_digest(self):
        assert self._digest() != self._digest(
            scheduled_start_at=datetime(2026, 7, 25, 20, 45, tzinfo=_UTC))

    def test_different_namespace_changes_digest(self):
        assert self._digest() != self._digest(source_namespace="fixture")

    def test_offset_start_equals_utc_start(self):
        eastern = self._digest(
            scheduled_start_at=datetime(2026, 7, 25, 13, 10, tzinfo=timezone(timedelta(hours=-4))))
        assert eastern == self._digest()


class TestWindowIdentity:
    def test_deterministic_and_prefixed(self):
        d = "SC-abc"
        assert ui.window_identity("g1", d) == ui.window_identity("g1", d)
        assert ui.window_identity("g1", d).startswith("S2W-")

    def test_varies_by_run(self):
        assert ui.window_identity("g1", "SC-x") != ui.window_identity("g2", "SC-x")


class TestExpiry:
    def test_before_cutoff_not_expired(self):
        assert ui.is_expired(datetime(2026, 7, 25, 18, 40, tzinfo=_UTC),
                             datetime(2026, 7, 25, 18, 45, tzinfo=_UTC)) is False

    def test_equality_is_expired(self):
        t = datetime(2026, 7, 25, 18, 45, tzinfo=_UTC)
        assert ui.is_expired(t, t) is True

    def test_after_cutoff_expired(self):
        assert ui.is_expired(datetime(2026, 7, 25, 19, 10, tzinfo=_UTC),
                             datetime(2026, 7, 25, 18, 45, tzinfo=_UTC)) is True

    def test_naive_raises(self):
        with pytest.raises(ui.IdentityError):
            ui.is_expired(datetime(2026, 7, 25, 18, 40), datetime(2026, 7, 25, 18, 45, tzinfo=_UTC))


class TestObservationOrder:
    def test_strictly_newer_true(self):
        assert ui.is_strictly_newer(datetime(2026, 7, 25, 19, 0, tzinfo=_UTC),
                                    datetime(2026, 7, 25, 18, 0, tzinfo=_UTC)) is True

    def test_older_is_not_newer(self):
        assert ui.is_strictly_newer(datetime(2026, 7, 25, 18, 0, tzinfo=_UTC),
                                    datetime(2026, 7, 25, 19, 0, tzinfo=_UTC)) is False

    def test_equal_is_not_strictly_newer(self):
        t = datetime(2026, 7, 25, 18, 0, tzinfo=_UTC)
        assert ui.is_strictly_newer(t, t) is False

    def test_naive_is_not_newer(self):
        assert ui.is_strictly_newer(datetime(2026, 7, 25, 19, 0),
                                    datetime(2026, 7, 25, 18, 0, tzinfo=_UTC)) is False


class TestDecideWindowAction:
    """Pure D-4 / D-5 / supersession / stale-observation decision (PM-1269 §1–§3)."""

    _CUTOFF = datetime(2026, 7, 25, 18, 45, tzinfo=_UTC)
    _EARLY = datetime(2026, 7, 25, 18, 0, tzinfo=_UTC)
    _LATE = datetime(2026, 7, 25, 19, 10, tzinfo=_UTC)

    def test_claim_exists_blocks_d4(self):
        action, sup = ui.decide_window_action(
            claim_exists=True, authoritative_cutoff=self._CUTOFF,
            authoritative_retrieved_at=self._EARLY, candidate_retrieved_at=self._LATE,
            decision_at=self._EARLY)
        assert action == ui.WINDOW_ACTION_BLOCKED_PRIOR_ADMISSION and sup is False

    def test_no_prior_window_establishes(self):
        action, sup = ui.decide_window_action(
            claim_exists=False, authoritative_cutoff=None,
            authoritative_retrieved_at=None, candidate_retrieved_at=self._LATE,
            decision_at=self._LATE)
        assert action == ui.WINDOW_ACTION_ESTABLISHED and sup is False

    def test_expired_prior_window_blocks_d5(self):
        # 18:45 cutoff, decision at 19:10 (after) → expired unused → no reopen.
        action, sup = ui.decide_window_action(
            claim_exists=False, authoritative_cutoff=self._CUTOFF,
            authoritative_retrieved_at=self._EARLY,
            candidate_retrieved_at=self._LATE, decision_at=self._LATE)
        assert action == ui.WINDOW_ACTION_BLOCKED_PRIOR_EXPIRED and sup is False

    def test_equality_at_cutoff_is_expired_d5(self):
        action, sup = ui.decide_window_action(
            claim_exists=False, authoritative_cutoff=self._CUTOFF,
            authoritative_retrieved_at=self._EARLY,
            candidate_retrieved_at=self._LATE, decision_at=self._CUTOFF)
        assert action == ui.WINDOW_ACTION_BLOCKED_PRIOR_EXPIRED

    def test_unexpired_strictly_newer_supersedes(self):
        action, sup = ui.decide_window_action(
            claim_exists=False, authoritative_cutoff=self._CUTOFF,
            authoritative_retrieved_at=self._EARLY,
            candidate_retrieved_at=self._LATE, decision_at=self._EARLY)
        assert action == ui.WINDOW_ACTION_ESTABLISHED and sup is True

    def test_unexpired_not_newer_is_stale_observation(self):
        # Candidate retrieved earlier than the authoritative window → cannot supersede.
        action, sup = ui.decide_window_action(
            claim_exists=False, authoritative_cutoff=self._CUTOFF,
            authoritative_retrieved_at=self._LATE,
            candidate_retrieved_at=self._EARLY, decision_at=self._EARLY)
        assert action == ui.WINDOW_ACTION_BLOCKED_STALE_OBSERVATION and sup is False

    def test_unexpired_equal_retrieved_at_does_not_supersede(self):
        t = self._EARLY
        action, sup = ui.decide_window_action(
            claim_exists=False, authoritative_cutoff=self._CUTOFF,
            authoritative_retrieved_at=t, candidate_retrieved_at=t,
            decision_at=self._EARLY)
        assert action == ui.WINDOW_ACTION_BLOCKED_STALE_OBSERVATION


class TestStage8Precheck:
    def test_claim_blocks_d4(self):
        assert ui.stage8_precheck(claim_exists=True,
                                  run_window_action=ui.WINDOW_ACTION_ESTABLISHED,
                                  run_is_superseded=False) == ui.STAGE8_INELIGIBLE_ALREADY_ADMITTED

    def test_superseded_blocked(self):
        assert ui.stage8_precheck(claim_exists=False,
                                  run_window_action=ui.WINDOW_ACTION_ESTABLISHED,
                                  run_is_superseded=True) == ui.STAGE8_INELIGIBLE_SUPERSEDED

    def test_prior_expired_blocked_d5(self):
        assert ui.stage8_precheck(claim_exists=False,
                                  run_window_action=ui.WINDOW_ACTION_BLOCKED_PRIOR_EXPIRED,
                                  run_is_superseded=False) == ui.STAGE8_INELIGIBLE_PRIOR_EXPIRED

    def test_stale_observation_not_authoritative(self):
        assert ui.stage8_precheck(claim_exists=False,
                                  run_window_action=ui.WINDOW_ACTION_BLOCKED_STALE_OBSERVATION,
                                  run_is_superseded=False) == ui.STAGE8_INELIGIBLE_NOT_AUTHORITATIVE

    def test_established_authoritative_ok(self):
        assert ui.stage8_precheck(claim_exists=False,
                                  run_window_action=ui.WINDOW_ACTION_ESTABLISHED,
                                  run_is_superseded=False) == ui.STAGE8_OK

    def test_missing_window_not_authoritative(self):
        assert ui.stage8_precheck(claim_exists=False, run_window_action=None,
                                  run_is_superseded=False) == ui.STAGE8_INELIGIBLE_NOT_AUTHORITATIVE
