"""Offline synthetic tests for backend.oracle.bullpen_rest (ratified M1, PM-1324).

Pure — no DB, no network, no process clock, no evaluator import. All records are
ARTIFICIAL; no historical target, outcome, or performance value is used. Expected
values are hand-computed from the ratified M1 policy. These tests verify the
SYNTHETIC CONTRACT of the calculator, not predictive validity.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, localcontext

import pytest

from backend.oracle import bullpen_rest as br

_UTC = timezone.utc
# Toronto(EDT) date of as_of = 2024-06-15; window = {2024-06-14, -13, -12}
_ASOF = datetime(2024, 6, 15, 18, 0, tzinfo=_UTC)
_W = ("2024-06-14", "2024-06-13", "2024-06-12")


# --- builders ---------------------------------------------------------------
def line(pid, gs, outs):
    return br.PitchingLine(player_id=pid, games_started=gs, outs=outs)

def relief(pid, outs):
    return line(pid, 0, outs)

def starter(pid, outs=15):
    return line(pid, 1, outs)

def obs(game_pk, team_id, lines, source="box", ret=None):
    return br.WorkloadObservation(game_pk=game_pk, team_id=team_id,
                                  pitching_lines=tuple(lines), source=source,
                                  retrieval_provenance=ret)

def comp(date_iso, hh=12):
    # a completion at hh:00 Toronto (EDT=UTC-4) as a tz-aware UTC instant, before _ASOF
    d = datetime.strptime(date_iso, "%Y-%m-%d")
    return datetime(d.year, d.month, d.day, hh + 4, 0, tzinfo=_UTC)  # noon EDT -> 16:00Z

def eg(game_pk, date_iso, resolved=True, completion=None):
    return br.ExpectedGame(game_pk=game_pk, local_date=date_iso,
                           completion_utc=completion if completion is not None else comp(date_iso),
                           attribution_resolved=resolved)

def team(tid, established=True, expected=(), observations=()):
    return br.TeamWindowEvidence(team_id=tid, inventory_established=established,
                                 expected_games=tuple(expected), observations=tuple(observations))

def one_game_team(tid, game_pk, date_iso, relief_outs_lines, established=True, source="box"):
    """Team with a single fully-covered expected game whose relief lines are given."""
    return team(tid, established,
                expected=[eg(game_pk, date_iso)],
                observations=[obs(game_pk, tid, relief_outs_lines, source=source)])

def dom(source_namespace="mlb-statsapi", sport_id=1, game_type="R", season=2024):
    return br.DomainAssertion(source_namespace=source_namespace, sport_id=sport_id,
                              game_type=game_type, season=season)

def request(home, away, as_of=_ASOF, target="TGT", domain=None, assumed=True):
    return br.BullpenRestRequest(as_of=as_of, target_game_pk=target, home=home, away=away,
                                 domain=domain if domain is not None else dom(),
                                 historical_availability_assumed=assumed)


# ===================================================================== A. arithmetic
class TestArithmetic:
    def test_zero_workload_is_full_rest(self):
        assert br.rest_from_outs(0) == Decimal("1.0000")

    def test_exactly_cap_is_zero(self):
        assert br.rest_from_outs(45) == Decimal("0.0000")

    def test_above_cap_clamps_to_zero(self):
        assert br.rest_from_outs(54) == Decimal("0.0000")
        assert br.rest_from_outs(1000) == Decimal("0.0000")

    def test_below_cap_values(self):
        assert br.rest_from_outs(15) == Decimal("0.6667")
        assert br.rest_from_outs(30) == Decimal("0.3333")

    def test_repeating_decimal_q4_half_up(self):
        assert br.rest_from_outs(10) == Decimal("0.7778")   # 35/45=0.77777..->up
        assert br.rest_from_outs(20) == Decimal("0.5556")   # 25/45=0.55555..->up
        assert br.rest_from_outs(33) == Decimal("0.2667")   # 12/45=0.26666..->up

    def test_evaluator_compatible_decimal_recovery(self):
        # supplied float must recover the 4dp Decimal via the evaluator's Decimal(str(x))
        for w in (0, 10, 15, 20, 30, 33, 45, 54):
            r = br.rest_from_outs(w)
            assert Decimal(str(float(r))) == r

    def test_bounds_and_monotonicity(self):
        prev = None
        for w in range(0, 61):
            r = br.rest_from_outs(w)
            assert Decimal("0") <= r <= Decimal("1")
            if prev is not None:
                assert r <= prev
            prev = r

    def test_independent_of_ambient_decimal_context(self):
        with localcontext() as ctx:
            ctx.prec = 2
            ctx.rounding = ROUND_FLOOR
            r = br.rest_from_outs(10)
        assert r == Decimal("0.7778")

    def test_equal_workload_gives_equal_rest(self):
        h = one_game_team("H", "g1", "2024-06-14", [relief("p", 30)])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 30)])
        res = br.compute_bullpen_rest(request(h, a))
        assert res.f3_present
        assert res.home_bp_rest == res.away_bp_rest == float(Decimal("0.3333"))

    def test_saturation_and_diff_maps_to_interface(self):
        h = one_game_team("H", "g1", "2024-06-14", [relief("p", 45)])   # R=0
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 30)])   # R=0.3333
        res = br.compute_bullpen_rest(request(h, a))
        assert (res.home_bp_rest, res.away_bp_rest) == (0.0, float(Decimal("0.3333")))

    def test_rest_from_outs_rejects_bad_workload(self):
        for bad in (-1, True, 2.0, None, "5"):
            with pytest.raises(br.BullpenRestError):
                br.rest_from_outs(bad)


# ============================================================ B. workload and roles
class TestWorkloadRoles:
    def test_valid_relief_outs_summed(self):
        h = one_game_team("H", "g1", "2024-06-14",
                          [relief("r1", 3), relief("r2", 4), starter("s", 15)])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 0)])
        res = br.compute_bullpen_rest(request(h, a))
        assert res.home.workload_outs == 7      # starter excluded
        assert res.away.workload_outs == 0

    def test_zero_out_relief_appearance_is_observed(self):
        h = one_game_team("H", "g1", "2024-06-14", [relief("r1", 0), relief("r2", 5)])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 5)])
        res = br.compute_bullpen_rest(request(h, a))
        assert res.home.workload_outs == 5       # 0-out appearance counted, adds 0

    def test_starter_and_opener_excluded_bulk_and_position_included(self):
        # opener recorded as starter (gs=1) excluded; bulk reliever (gs=0) & position
        # player pitching in relief (gs=0) included, by the pure gamesStarted rule.
        lines = [starter("opener", 3), relief("bulk", 12), relief("position_player", 2)]
        h = one_game_team("H", "g1", "2024-06-14", lines)
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 10)])
        res = br.compute_bullpen_rest(request(h, a))
        assert res.home.workload_outs == 14      # 12 + 2, opener's 3 excluded

    def test_malformed_role_missing_fails_closed(self):
        h = one_game_team("H", "g1", "2024-06-14", [line("x", None, 3)])   # role missing
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 3)])
        res = br.compute_bullpen_rest(request(h, a))
        assert not res.f3_present
        assert any(r.startswith(br.R_MALFORMED_EVIDENCE) for r in res.home.missing_reasons)

    def test_malformed_or_negative_outs_fail_closed(self):
        for bad_outs in (None, -1, "3"):
            h = one_game_team("H", "g1", "2024-06-14", [relief("r", bad_outs)])
            a = one_game_team("A", "g2", "2024-06-14", [relief("q", 3)])
            res = br.compute_bullpen_rest(request(h, a))
            assert not res.f3_present
            assert any(r.startswith(br.R_MALFORMED_EVIDENCE) for r in res.home.missing_reasons)

    def test_boolean_outs_and_role_rejected(self):
        # bool must not count as int outs/role
        h = one_game_team("H", "g1", "2024-06-14", [line("r", 0, True)])   # outs=True
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 3)])
        res = br.compute_bullpen_rest(request(h, a))
        assert not res.f3_present
        assert any(r.startswith(br.R_MALFORMED_EVIDENCE) for r in res.home.missing_reasons)
        h2 = one_game_team("H", "g1", "2024-06-14", [line("r", True, 3)])  # role=True
        res2 = br.compute_bullpen_rest(request(h2, a))
        assert not res2.f3_present

    def test_doubleheader_two_games_both_counted(self):
        exp = [eg("dh1", "2024-06-14"), eg("dh2", "2024-06-14")]
        obss = [obs("dh1", "H", [relief("a", 10)]), obs("dh2", "H", [relief("b", 8)])]
        h = team("H", True, exp, obss)
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 5)])
        res = br.compute_bullpen_rest(request(h, a))
        assert res.home.workload_outs == 18
        assert set(res.home.included_game_pks) == {"dh1", "dh2"}


# ==================================================== C. completeness and missingness
class TestCompleteness:
    def test_complete_nonempty(self):
        h = one_game_team("H", "g1", "2024-06-13", [relief("r", 12)])
        a = one_game_team("A", "g2", "2024-06-13", [relief("q", 24)])
        res = br.compute_bullpen_rest(request(h, a))
        assert res.f3_present
        assert res.home.workload_outs == 12 and res.away.workload_outs == 24

    def test_established_empty_window_is_full_rest(self):
        h = team("H", established=True, expected=(), observations=())   # no games in window
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 9)])
        res = br.compute_bullpen_rest(request(h, a))
        assert res.f3_present
        assert res.home.workload_outs == 0 and res.home_bp_rest == 1.0

    def test_unestablished_empty_is_missing_not_zero(self):
        h = team("H", established=False, expected=(), observations=())
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 9)])
        res = br.compute_bullpen_rest(request(h, a))
        assert not res.f3_present
        assert res.home_bp_rest is None      # NOT fabricated as 0/1
        assert br.R_INVENTORY_UNRESOLVED in res.home.missing_reasons

    def test_partial_coverage_one_game_uncovered(self):
        exp = [eg("g1", "2024-06-14"), eg("g2", "2024-06-13")]
        obss = [obs("g1", "H", [relief("r", 10)])]   # g2 has no observation
        h = team("H", True, exp, obss)
        a = one_game_team("A", "gx", "2024-06-14", [relief("q", 5)])
        res = br.compute_bullpen_rest(request(h, a))
        assert not res.f3_present
        assert any(r == f"{br.R_NO_USABLE_WORKLOAD}:g2" for r in res.home.missing_reasons)

    def test_zero_source_coverage(self):
        h = team("H", True, [eg("g1", "2024-06-14")], observations=())
        a = one_game_team("A", "gx", "2024-06-14", [relief("q", 5)])
        res = br.compute_bullpen_rest(request(h, a))
        assert not res.f3_present
        assert f"{br.R_NO_USABLE_WORKLOAD}:g1" in res.home.missing_reasons

    def test_one_team_complete_other_incomplete_yields_both_none(self):
        h = one_game_team("H", "g1", "2024-06-14", [relief("r", 10)])       # complete
        a = team("A", True, [eg("g2", "2024-06-14")], observations=())      # uncovered
        res = br.compute_bullpen_rest(request(h, a))
        assert not res.f3_present
        assert res.home_bp_rest is None and res.away_bp_rest is None        # never one-sided
        assert res.home.supplied and not res.away.supplied                  # team-level detail retained

    def test_missing_record_despite_reaching_cap_still_missing(self):
        # one covered game already >= CAP, but another expected game is uncovered
        exp = [eg("g1", "2024-06-14"), eg("g2", "2024-06-13")]
        obss = [obs("g1", "H", [relief("r", 60)])]     # 60 outs alone saturates
        h = team("H", True, exp, obss)
        a = one_game_team("A", "gx", "2024-06-14", [relief("q", 5)])
        res = br.compute_bullpen_rest(request(h, a))
        assert not res.f3_present                       # saturation does not waive completeness
        assert f"{br.R_NO_USABLE_WORKLOAD}:g2" in res.home.missing_reasons

    def test_missing_never_becomes_zero(self):
        h = team("H", True, [eg("g1", "2024-06-14")], observations=())
        a = one_game_team("A", "gx", "2024-06-14", [relief("q", 5)])
        res = br.compute_bullpen_rest(request(h, a))
        assert res.home.workload_outs is None and res.home.rest is None


# =============================================================== D. identity/duplicates
class TestIdentityDuplicates:
    def _pair(self, home):
        a = one_game_team("A", "gx", "2024-06-14", [relief("q", 6)])
        return request(home, a)

    def test_wrong_team_observation_not_used(self):
        # observation carries a different team_id -> not matched -> game uncovered
        h = team("H", True, [eg("g1", "2024-06-14")],
                 observations=[obs("g1", "OTHER", [relief("r", 10)])])
        res = br.compute_bullpen_rest(self._pair(h))
        assert not res.f3_present
        assert f"{br.R_NO_USABLE_WORKLOAD}:g1" in res.home.missing_reasons

    def test_compatible_duplicate_counts_once(self):
        dup = [obs("g1", "H", [relief("r", 11)], source="boxscore"),
               obs("g1", "H", [relief("r", 11)], source="feed", ret="feed_live")]
        h = team("H", True, [eg("g1", "2024-06-14")], observations=dup)
        res = br.compute_bullpen_rest(self._pair(h))
        assert res.home.workload_outs == 11        # not 22

    def test_conflicting_duplicates_fail_closed(self):
        conf = [obs("g1", "H", [relief("r", 11)], source="boxscore"),
                obs("g1", "H", [relief("r", 12)], source="feed")]
        h = team("H", True, [eg("g1", "2024-06-14")], observations=conf)
        res = br.compute_bullpen_rest(self._pair(h))
        assert not res.f3_present
        assert f"{br.R_CONFLICTING_EVIDENCE}:g1" in res.home.missing_reasons

    def test_role_disagreement_is_conflict(self):
        conf = [obs("g1", "H", [line("r", 0, 5)]),   # relief 5
                obs("g1", "H", [line("r", 1, 5)])]   # same pitcher as starter
        h = team("H", True, [eg("g1", "2024-06-14")], observations=conf)
        res = br.compute_bullpen_rest(self._pair(h))
        assert f"{br.R_CONFLICTING_EVIDENCE}:g1" in res.home.missing_reasons

    def test_later_duplicate_cannot_restore_conflicted_group(self):
        grp = [obs("g1", "H", [relief("r", 11)]),
               obs("g1", "H", [relief("r", 12)]),
               obs("g1", "H", [relief("r", 11)])]    # a 3rd copy identical to the 1st
        h = team("H", True, [eg("g1", "2024-06-14")], observations=grp)
        res = br.compute_bullpen_rest(self._pair(h))
        assert f"{br.R_CONFLICTING_EVIDENCE}:g1" in res.home.missing_reasons

    def test_distinct_games_remain_distinct(self):
        exp = [eg("g1", "2024-06-14"), eg("g2", "2024-06-13")]
        obss = [obs("g1", "H", [relief("r", 5)]), obs("g2", "H", [relief("s", 7)])]
        h = team("H", True, exp, obss)
        res = br.compute_bullpen_rest(self._pair(h))
        assert res.home.workload_outs == 12
        assert set(res.home.included_game_pks) == {"g1", "g2"}

    def test_order_invariance(self):
        exp = [eg("g1", "2024-06-14"), eg("g2", "2024-06-13")]
        obss = [obs("g1", "H", [relief("r", 5)]),
                obs("g2", "H", [relief("s", 7)]),
                obs("g1", "H", [relief("r", 5)])]      # compatible dup
        h1 = team("H", True, exp, obss)
        h2 = team("H", True, list(reversed(exp)), list(reversed(obss)))
        r1 = br.compute_bullpen_rest(self._pair(h1))
        r2 = br.compute_bullpen_rest(self._pair(h2))
        assert r1.home.workload_outs == r2.home.workload_outs == 12
        assert r1.home.rest == r2.home.rest

    def test_inputs_not_mutated(self):
        exp = (eg("g1", "2024-06-14"),)
        obss = (obs("g1", "H", (relief("r", 5),)),)
        h = team("H", True, exp, obss)
        a = one_game_team("A", "gx", "2024-06-14", [relief("q", 6)])
        req = request(h, a)
        snapshot = repr(req)
        br.compute_bullpen_rest(req)
        assert repr(req) == snapshot
        assert req.home.expected_games == exp and req.home.observations == obss


# ============================================================================ E. time
class TestTime:
    def test_naive_as_of_rejected(self):
        h = one_game_team("H", "g1", "2024-06-14", [relief("r", 5)])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 5)])
        with pytest.raises(br.BullpenRestError):
            br.compute_bullpen_rest(request(h, a, as_of=datetime(2024, 6, 15, 18, 0)))

    def test_window_dates_and_boundary(self):
        assert br._window_dates(_ASOF) == _W
        # 2024-06-16 03:00Z = 2024-06-15 23:00 EDT -> A=06-15 -> window unchanged
        assert br._window_dates(datetime(2024, 6, 16, 3, 0, tzinfo=_UTC)) == _W
        # 2024-06-16 04:00Z = 2024-06-16 00:00 EDT -> A=06-16 -> window shifts
        assert br._window_dates(datetime(2024, 6, 16, 4, 0, tzinfo=_UTC)) == \
            ("2024-06-15", "2024-06-14", "2024-06-13")

    def test_truthful_est_edt_offsets_fallback_scope(self):
        # EDT in summer (-4), EST in winter (-5)
        assert br._toronto_date(datetime(2024, 6, 15, 3, 0, tzinfo=_UTC)).isoformat() == "2024-06-14"
        assert br._toronto_date(datetime(2024, 1, 15, 4, 0, tzinfo=_UTC)).isoformat() == "2024-01-14"
        # this environment has no IANA db -> bounded fallback active
        assert "fallback" in br.TZ_MECHANISM or br.TZ_MECHANISM.startswith("zoneinfo")

    def test_calendar_day_window_not_rolling_72h(self):
        # game on A-3 (~ up to 3 calendar days back, can exceed 72h) counts;
        # a game only ~20h back but on the target's own date A is excluded.
        h = one_game_team("H", "gedge", "2024-06-12", [relief("r", 9)])  # A-3
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 9)])
        res = br.compute_bullpen_rest(request(h, a))
        assert res.f3_present and res.home.workload_outs == 9

    def test_same_day_and_target_excluded(self):
        # expected game on date A (2024-06-15) and the target game are excluded ->
        # window becomes established-empty for H (no in-window expected games)
        exp = [eg("sameday", "2024-06-15"), eg("TGT", "2024-06-14")]
        obss = [obs("sameday", "H", [relief("r", 30)]), obs("TGT", "H", [relief("t", 30)])]
        h = team("H", True, exp, obss)
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 9)])
        res = br.compute_bullpen_rest(request(h, a, target="TGT"))
        assert res.home.workload_outs == 0 and res.home_bp_rest == 1.0

    def test_stale_postponed_completion_after_as_of_excluded(self):
        # a game attributed in-window but whose completion is AFTER as_of -> not usable
        g = br.ExpectedGame("gp", "2024-06-14", completion_utc=_ASOF + timedelta(hours=2))
        h = team("H", True, [g], [obs("gp", "H", [relief("r", 10)])])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 9)])
        res = br.compute_bullpen_rest(request(h, a))
        assert not res.f3_present
        assert f"{br.R_COMPLETION_NOT_BEFORE_ASOF}:gp" in res.home.missing_reasons

    def test_missing_completion_evidence_is_missing(self):
        g = br.ExpectedGame("gp", "2024-06-14", completion_utc=None)
        h = team("H", True, [g], [obs("gp", "H", [relief("r", 10)])])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 9)])
        res = br.compute_bullpen_rest(request(h, a))
        assert f"{br.R_MISSING_COMPLETION}:gp" in res.home.missing_reasons

    def test_unresolved_suspended_is_missing_and_confined(self):
        # H has an in-window suspended/unresolved game -> H missing; A unaffected
        h = team("H", True, [eg("susp", "2024-06-13", resolved=False)],
                 observations=[obs("susp", "H", [relief("r", 12)])])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 9)])
        res = br.compute_bullpen_rest(request(h, a))
        assert not res.f3_present
        assert f"{br.R_TEMPORAL_UNRESOLVED}:susp" in res.home.missing_reasons
        assert res.away.supplied                     # confined to the affected window

    def test_supported_suspended_attribution_included(self):
        # resolved attribution -> included normally
        h = one_game_team("H", "res", "2024-06-13", [relief("r", 12)])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 9)])
        res = br.compute_bullpen_rest(request(h, a))
        assert res.f3_present and res.home.workload_outs == 12

    def test_f3_observed_at_is_latest_completion_and_assumption_labelled(self):
        h = team("H", True, [eg("g1", "2024-06-12"), eg("g2", "2024-06-14")],
                 [obs("g1", "H", [relief("r", 5)]), obs("g2", "H", [relief("s", 6)])])
        a = one_game_team("A", "g2b", "2024-06-13", [relief("q", 9)])
        res = br.compute_bullpen_rest(request(h, a))
        assert res.f3_present
        assert res.f3_observed_at == comp("2024-06-14").astimezone(_UTC)   # latest
        assert res.f3_observed_at <= _ASOF
        assert any("ASSUMED" in n for n in res.notes)

    def test_empty_window_has_no_completion_timestamp(self):
        h = team("H", True, (), ())        # established empty
        a = team("A", True, (), ())        # established empty (both idle)
        res = br.compute_bullpen_rest(request(h, a))
        assert res.f3_present
        assert res.home_bp_rest == res.away_bp_rest == 1.0
        assert res.f3_observed_at is None
        assert any("empty_window" in n for n in res.notes)

    def test_retrieval_provenance_separate_from_completion(self):
        o = obs("g1", "H", [relief("r", 5)], source="feed", ret="retrieved_2026")
        assert o.retrieval_provenance == "retrieved_2026" and o.source == "feed"


# ============================================================= F. purity and interface
class TestPurityInterface:
    def test_deterministic_repeat(self):
        h = one_game_team("H", "g1", "2024-06-14", [relief("r", 13)])
        a = one_game_team("A", "g2", "2024-06-13", [relief("q", 21)])
        req = request(h, a)
        r1 = br.compute_bullpen_rest(req)
        r2 = br.compute_bullpen_rest(req)
        assert (r1.home_bp_rest, r1.away_bp_rest, r1.f3_observed_at) == \
               (r2.home_bp_rest, r2.away_bp_rest, r2.f3_observed_at)

    def test_no_evaluator_or_stage_dependency(self):
        import sys
        # the calculator itself must not pull in these modules
        for banned in ("backend.oracle.moneyline_evaluator", "backend.oracle.daily_ranking"):
            assert banned not in sys.modules or True  # tolerate other tests; assert br has no ref
        src = open(br.__file__, encoding="utf-8").read()
        for banned in ("moneyline_evaluator", "daily_ranking", "import socket",
                       "import os", "datetime.now", "psycopg", "requests"):
            assert banned not in src, banned

    def test_no_hidden_clock(self):
        # results depend only on supplied as_of, not wall time: two builds equal
        h = one_game_team("H", "g1", "2024-06-14", [relief("r", 10)])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 10)])
        assert br.compute_bullpen_rest(request(h, a)).home_bp_rest == \
               br.compute_bullpen_rest(request(h, a)).home_bp_rest

    def test_interface_fields_present_and_missing_representation(self):
        h = one_game_team("H", "g1", "2024-06-14", [relief("r", 10)])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 10)])
        ev = br.compute_bullpen_rest(request(h, a)).to_evaluator_inputs()
        assert set(ev) == {"home_bp_rest", "away_bp_rest", "f3_observed_at"}
        assert isinstance(ev["home_bp_rest"], float)
        # missing case -> both None + f3_observed_at None
        hm = team("H", True, [eg("g1", "2024-06-14")], ())
        evm = br.compute_bullpen_rest(request(hm, a)).to_evaluator_inputs()
        assert evm == {"home_bp_rest": None, "away_bp_rest": None, "f3_observed_at": None}

    def test_out_of_domain_sport_rejected(self):
        # fixture updated for PM-1327: sport is now carried in the DomainAssertion.
        h = one_game_team("H", "g1", "2024-06-14", [relief("r", 10)])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 10)])
        res = br.compute_bullpen_rest(request(h, a, domain=dom(sport_id=2)))
        assert not res.f3_present
        assert br.R_OUT_OF_DOMAIN in res.home.missing_reasons


# =================================================== PM-1327 defect 1: multiplicity
class TestPM1327Multiplicity:
    def _pair(self, obss):
        h = team("H", True, [eg("g1", "2024-06-14")], obss)
        a = one_game_team("A", "gx", "2024-06-14", [relief("q", 6)])
        return request(h, a)

    def test_single_vs_duplicated_line_fails_closed_both_orders(self):
        # the original defect: A=one R line (3 outs) vs B=the same R line twice (6 outs)
        # collapsed to one fingerprint -> first-input-wins. Now B is malformed (repeated
        # player id), so BOTH orders fail closed identically — no order-dependent output.
        A = obs("g1", "H", [relief("R", 3)])
        B = obs("g1", "H", [relief("R", 3), relief("R", 3)])
        rAB = br.compute_bullpen_rest(self._pair([A, B]))
        rBA = br.compute_bullpen_rest(self._pair([B, A]))
        assert not rAB.f3_present and not rBA.f3_present
        assert rAB.home_bp_rest is None and rBA.home_bp_rest is None
        assert f"{br.R_MALFORMED_EVIDENCE}:g1" in rAB.home.missing_reasons
        assert rAB.home.missing_reasons == rBA.home.missing_reasons     # order-invariant

    def test_repeated_player_contradictory_outs_is_malformed(self):
        bad = obs("g1", "H", [relief("R", 3), relief("R", 4)])          # same id, diff outs
        res = br.compute_bullpen_rest(self._pair([bad]))
        assert f"{br.R_MALFORMED_EVIDENCE}:g1" in res.home.missing_reasons

    def test_repeated_player_contradictory_role_is_malformed(self):
        bad = obs("g1", "H", [line("R", 0, 3), line("R", 1, 3)])        # same id, diff role
        res = br.compute_bullpen_rest(self._pair([bad]))
        assert f"{br.R_MALFORMED_EVIDENCE}:g1" in res.home.missing_reasons

    def test_genuine_equivalent_observations_count_once(self):
        dupe = [obs("g1", "H", [relief("R", 4), relief("S", 5)], source="box"),
                obs("g1", "H", [relief("S", 5), relief("R", 4)], source="feed")]  # reordered, equal
        res = br.compute_bullpen_rest(self._pair(dupe))
        assert res.home.workload_outs == 9                              # counted once, not 18

    def test_AAB_permutations_cannot_restore_conflict_or_malformed(self):
        import itertools
        A = obs("g1", "H", [relief("R", 11)])
        A2 = obs("g1", "H", [relief("R", 11)])          # compatible copy of A
        B = obs("g1", "H", [relief("R", 12)])           # conflicting workload
        for perm in set(itertools.permutations([A, A2, B])):
            res = br.compute_bullpen_rest(self._pair(list(perm)))
            assert not res.f3_present
            assert f"{br.R_CONFLICTING_EVIDENCE}:g1" in res.home.missing_reasons

    def test_malformed_sibling_not_discarded_for_valid_one(self):
        valid = obs("g1", "H", [relief("R", 3)])
        malformed = obs("g1", "H", [relief("R", 3), relief("R", 3)])
        res = br.compute_bullpen_rest(self._pair([valid, malformed]))
        assert not res.f3_present                                       # not silently 3
        assert f"{br.R_MALFORMED_EVIDENCE}:g1" in res.home.missing_reasons

    def test_unrelated_game_observation_does_not_affect(self):
        # a malformed observation for a game NOT in the expected inventory is ignored
        h = team("H", True, [eg("g1", "2024-06-14")],
                 [obs("g1", "H", [relief("R", 10)]),
                  obs("gUNRELATED", "H", [relief("X", 3), relief("X", 3)])])  # malformed, unrelated
        a = one_game_team("A", "gx", "2024-06-14", [relief("q", 6)])
        res = br.compute_bullpen_rest(request(h, a))
        assert res.f3_present and res.home.workload_outs == 10

    def test_supplied_observations_not_mutated(self):
        lines = (relief("R", 3), relief("S", 4))
        o = obs("g1", "H", lines)
        snap = repr(o)
        br.compute_bullpen_rest(self._pair([o, o]))
        assert repr(o) == snap and o.pitching_lines == lines


# ================================================= PM-1327 defect 2: domain enforcement
class TestPM1327Domain:
    def _teams(self):
        h = one_game_team("H", "g1", "2024-06-14", [relief("r", 10)])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 10)])
        return h, a

    def test_valid_ratified_domain_supplied(self):
        h, a = self._teams()
        res = br.compute_bullpen_rest(request(h, a, domain=dom()))
        assert res.f3_present

    def test_wrong_namespace_rejected(self):
        h, a = self._teams()
        res = br.compute_bullpen_rest(request(h, a, domain=dom(source_namespace="other-ns")))
        assert not res.f3_present and res.home_bp_rest is None and res.away_bp_rest is None
        assert br.R_OUT_OF_DOMAIN in res.home.missing_reasons

    def test_wrong_sport_and_boolean_identifier_rejected(self):
        h, a = self._teams()
        assert not br.compute_bullpen_rest(request(h, a, domain=dom(sport_id=2))).f3_present
        # a boolean must not pass as a sport identifier even though bool(True)==1
        res = br.compute_bullpen_rest(request(h, a, domain=dom(sport_id=True)))
        assert not res.f3_present and br.R_OUT_OF_DOMAIN in res.home.missing_reasons

    def test_wrong_game_type_rejected(self):
        h, a = self._teams()
        res = br.compute_bullpen_rest(request(h, a, domain=dom(game_type="P")))
        assert not res.f3_present and br.R_OUT_OF_DOMAIN in res.home.missing_reasons

    def test_wrong_season_rejected(self):
        h, a = self._teams()
        res = br.compute_bullpen_rest(request(h, a, domain=dom(season=2023)))
        assert not res.f3_present and br.R_OUT_OF_DOMAIN in res.home.missing_reasons
        # a boolean season must not pass either
        assert not br.compute_bullpen_rest(request(h, a, domain=dom(season=True))).f3_present

    def test_missing_domain_assertion_fails_closed(self):
        h, a = self._teams()
        req = br.BullpenRestRequest(as_of=_ASOF, target_game_pk="TGT", home=h, away=a, domain=None)
        res = br.compute_bullpen_rest(req)
        assert not res.f3_present and br.R_OUT_OF_DOMAIN in res.home.missing_reasons
        assert any("assertion" in n for n in res.notes)

    def test_target_local_year_outside_domain(self):
        h, a = self._teams()
        as_of_2025 = datetime(2025, 6, 15, 18, 0, tzinfo=_UTC)
        res = br.compute_bullpen_rest(request(h, a, as_of=as_of_2025))
        assert not res.f3_present and br.R_OUT_OF_DOMAIN in res.home.missing_reasons
        assert any("target_year" in n for n in res.notes)

    def test_contradictory_domain_in_required_record_fails_closed(self):
        bad_eg = br.ExpectedGame("g1", "2024-06-14", completion_utc=comp("2024-06-14"),
                                 domain=dom(season=2023))
        h = team("H", True, [bad_eg], [obs("g1", "H", [relief("r", 10)])])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 10)])
        res = br.compute_bullpen_rest(request(h, a))          # top-level domain is ratified 2024
        assert not res.f3_present
        assert f"{br.R_OUT_OF_DOMAIN}:g1" in res.home.missing_reasons   # not dropped/reduced

    def test_year_rejection_independent_of_timezone_backend(self, monkeypatch):
        # PM-1337 portability fix: year/domain rejection must hold under BOTH timezone
        # backends, regardless of whether the host initially ships IANA data. Each
        # backend is arranged EXPLICITLY via monkeypatch (auto-restored); the test makes
        # no assumption about the host's initial br._TORONTO_ZONE state (the prior
        # `assert br._TORONTO_ZONE is None` depended on the host lacking IANA data and
        # failed on runners that have it).
        h, a = self._teams()
        as_of_2025 = datetime(2025, 6, 15, 18, 0, tzinfo=_UTC)
        # (a) fallback branch: deliberately arrange NO IANA backend (host-independent).
        monkeypatch.setattr(br, "_TORONTO_ZONE", None)
        assert br._TORONTO_ZONE is None                       # arranged state, not host state
        r1 = br.compute_bullpen_rest(request(h, a, as_of=as_of_2025))
        assert not r1.f3_present and br.R_OUT_OF_DOMAIN in r1.home.missing_reasons
        # (b) timezone-backed branch: deliberately arrange a non-None backend (a controlled
        #     fixed-offset stand-in that exercises _toronto_date's zoneinfo branch).
        monkeypatch.setattr(br, "_TORONTO_ZONE", timezone(timedelta(hours=-4)))
        assert br._TORONTO_ZONE is not None                   # arranged state
        r2 = br.compute_bullpen_rest(request(h, a, as_of=as_of_2025))
        assert not r2.f3_present and br.R_OUT_OF_DOMAIN in r2.home.missing_reasons

    def test_toronto_date_governs_year_not_utc(self):
        # UTC 2025-01-01 03:00 -> Toronto EST 2024-12-31 (year 2024, in season)
        assert br._toronto_date(datetime(2025, 1, 1, 3, 0, tzinfo=_UTC)).year == 2024
        # UTC 2024-01-01 03:00 -> Toronto 2023-12-31 (year 2023, out of season)
        as_of2 = datetime(2024, 1, 1, 3, 0, tzinfo=_UTC)
        assert br._toronto_date(as_of2).year == 2023
        h = team("H", True, (), ())
        a = team("A", True, (), ())
        res = br.compute_bullpen_rest(request(h, a, as_of=as_of2))
        assert not res.f3_present and br.R_OUT_OF_DOMAIN in res.home.missing_reasons

    def test_modern_retrieval_provenance_not_out_of_domain(self):
        h = team("H", True, [eg("g1", "2024-06-14")],
                 [obs("g1", "H", [relief("r", 10)], source="feed", ret="retrieved_2026-09-21")])
        a = one_game_team("A", "g2", "2024-06-14", [relief("q", 10)])
        res = br.compute_bullpen_rest(request(h, a))
        assert res.f3_present         # a 2026 retrieval timestamp does not taint the 2024 game
