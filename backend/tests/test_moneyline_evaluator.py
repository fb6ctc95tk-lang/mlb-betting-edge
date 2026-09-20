"""Offline unit tests for backend.oracle.moneyline_evaluator (PM-1287 / PM-1289).

Pure — no DB, no network, no process clock. Expected values are independently
hand-computed from the corrected contract (not produced by calling the evaluator).
Covers the PM-1287 worked examples with PM-1289 corrections/relabelling, factor
direction/saturation/rounding, selection and band boundaries, downward caps,
required/invalid evidence, the missing-F3 conservative interval and its
monotonicity, balanced-vs-uncertainty, the time/quote contract, neutrality and
official_status, and determinism/no-mutation.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.oracle import moneyline_evaluator as me

_UTC = timezone.utc
_ASOF = datetime(2024, 6, 15, 18, 0, tzinfo=_UTC)


def mk(**kw):
    """Build MoneylineInputs with a valid, above-minimum, OBSERVED_FULL baseline."""
    base = dict(
        source_namespace="mlb-statsapi", sport_id=1, game_pk="700001",
        home_team="HOME", away_team="AWAY",
        home_sp_era=2.80, away_sp_era=4.90, home_sp_ip=180.0, away_sp_ip=180.0,
        home_off_rpg=5.2, away_off_rpg=4.0, home_off_games=60, away_off_games=60,
        home_bp_rest=0.7, away_bp_rest=0.5,
    )
    base.update(kw)
    return me.MoneylineInputs(**base)


# --- Q4 half-up rounding (positive and negative boundaries) -------------------
class TestQ4Rounding:
    def test_half_up_positive(self):
        assert me.q4(0.12345) == Decimal("0.1235")
        assert me.q4(0.123449) == Decimal("0.1234")
        assert me.q4(0.00005) == Decimal("0.0001")

    def test_half_up_negative_away_from_zero(self):
        assert me.q4(-0.12345) == Decimal("-0.1235")
        assert me.q4(-0.00005) == Decimal("-0.0001")
        assert me.q4(-0.123449) == Decimal("-0.1234")

    def test_exact_values_stable(self):
        assert me.q4(0.81) == Decimal("0.8100")
        assert me.q4(0.155) == Decimal("0.1550")


# --- Factor direction, saturation, aggregation --------------------------------
class TestFactorsAndAggregation:
    def test_e1_substantive_high(self):
        # s1=clamp(2.10/2.00)=1.0000; s2=clamp(1.20/1.50)=0.8000; s3=0.2000
        # A=0.50*1+0.35*0.8+0.15*0.2 = 0.8100
        a = me.evaluate(mk(), _ASOF)
        assert a.analysis_state == me.ASSESSED
        assert a.directional_selection == me.HOME
        assert a.assessment_confidence == me.HIGH
        assert a.aggregate_score == pytest.approx(0.8100)
        assert a.directional_margin == pytest.approx(0.8100)
        assert a.coverage == pytest.approx(1.00)

    def test_e2_moderate_mid(self):
        # era 3.50/4.30 -> s1=0.40; off 4.5/4.2 -> s2=0.20; rest equal -> s3=0; A=0.2700
        a = me.evaluate(mk(home_sp_era=3.50, away_sp_era=4.30, home_off_rpg=4.5, away_off_rpg=4.2,
                           home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)
        assert a.directional_selection == me.HOME
        assert a.assessment_confidence == me.MODERATE
        assert a.aggregate_score == pytest.approx(0.2700)

    def test_saturation_clamps_to_one(self):
        # away-home ERA gap 8.0 -> raw 4.0 -> clamp to 1.0
        a = me.evaluate(mk(home_sp_era=2.0, away_sp_era=10.0, home_off_rpg=4.0, away_off_rpg=4.0,
                           home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)
        # A = 0.50*1.0 + 0 + 0 = 0.5000
        assert a.aggregate_score == pytest.approx(0.5000)

    def test_direction_away_when_away_stronger(self):
        a = me.evaluate(mk(home_sp_era=4.90, away_sp_era=2.80, home_off_rpg=4.0, away_off_rpg=5.2,
                           home_bp_rest=0.5, away_bp_rest=0.7), _ASOF)
        assert a.directional_selection == me.AWAY
        assert a.aggregate_score < 0


# --- Selection threshold & band boundaries (equality cases) -------------------
class TestSelectionAndBands:
    def test_e4_threshold_inclusive_low(self):
        # s1=0.2 (era 3.0/3.4), s2=0, s3=0 -> A=0.1000 -> select, Low
        a = me.evaluate(mk(home_sp_era=3.0, away_sp_era=3.4, home_off_rpg=4.0, away_off_rpg=4.0,
                           home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)
        assert a.aggregate_score == pytest.approx(0.1000)
        assert a.directional_selection == me.HOME
        assert a.assessment_confidence == me.LOW

    def test_e4_just_below_threshold_balanced(self):
        # s1=0.18 (era 3.0/3.36) -> A=0.0900 -> NO_SELECTION balanced (F3 observed)
        a = me.evaluate(mk(home_sp_era=3.0, away_sp_era=3.36, home_off_rpg=4.0, away_off_rpg=4.0,
                           home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)
        assert a.aggregate_score == pytest.approx(0.0900)
        assert a.analysis_state == me.NO_SELECTION
        assert a.directional_selection is None
        assert a.no_selection_reason == me.REASON_BALANCED_OBSERVED
        assert a.assessment_confidence is None

    def test_moderate_lower_boundary_equms(self):
        # A=0.2500 (s1=0.5 via era 3.0/4.0) -> Moderate (inclusive)
        a = me.evaluate(mk(home_sp_era=3.0, away_sp_era=4.0, home_off_rpg=4.0, away_off_rpg=4.0,
                           home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)
        assert a.aggregate_score == pytest.approx(0.2500)
        assert a.assessment_confidence == me.MODERATE

    def test_high_lower_boundary_equals(self):
        # A=0.4500 (s1=0.9 via era 3.0/4.8) -> High (inclusive)
        a = me.evaluate(mk(home_sp_era=3.0, away_sp_era=4.8, home_off_rpg=4.0, away_off_rpg=4.0,
                           home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)
        assert a.aggregate_score == pytest.approx(0.4500)
        assert a.assessment_confidence == me.HIGH

    def test_just_below_moderate_is_low(self):
        # A=0.2400 (s1=0.48 via era 3.0/3.96) -> Low
        a = me.evaluate(mk(home_sp_era=3.0, away_sp_era=3.96, home_off_rpg=4.0, away_off_rpg=4.0,
                           home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)
        assert a.aggregate_score == pytest.approx(0.2400)
        assert a.assessment_confidence == me.LOW


# --- Downward caps ------------------------------------------------------------
class TestCaps:
    def test_coverage_cap_when_f3_missing(self):
        # E1 inputs but F3 absent -> base High capped to Moderate
        a = me.evaluate(mk(home_bp_rest=None, away_bp_rest=None), _ASOF)
        assert a.coverage == pytest.approx(0.85)
        assert a.assessment_confidence == me.MODERATE
        assert a.missingness_treatment == me.MISSINGNESS_F3_RESERVED

    def test_lineup_cap(self):
        a = me.evaluate(mk(home_lineup_status=me.PARTIAL), _ASOF)
        assert a.assessment_confidence == me.MODERATE  # base High capped by lineup

    def test_at_min_sample_cap(self):
        a = me.evaluate(mk(home_sp_ip=20.0, away_sp_ip=20.0), _ASOF)
        assert a.assessment_confidence == me.MODERATE  # base High capped by at-min-sample

    def test_caps_only_lower_never_raise(self):
        # Low base (A=0.1000, F3 observed) stays Low even with lineup + at-min-sample caps active.
        a = me.evaluate(mk(home_sp_era=3.0, away_sp_era=3.4, home_off_rpg=4.0, away_off_rpg=4.0,
                           home_bp_rest=0.5, away_bp_rest=0.5, home_lineup_status=me.PARTIAL,
                           home_sp_ip=20.0, away_sp_ip=20.0), _ASOF)
        assert a.directional_selection == me.HOME
        assert a.assessment_confidence == me.LOW


# --- Required / invalid evidence & insufficient handling ----------------------
class TestRequiredEvidence:
    def test_insufficient_when_ip_below_min(self):
        a = me.evaluate(mk(away_sp_ip=12.0), _ASOF)
        assert a.analysis_state == me.INSUFFICIENT_EVIDENCE
        assert a.directional_selection is None
        assert a.assessment_confidence is None
        assert "F1_starting_pitcher_run_prevention" in a.missing_or_invalid_inputs

    def test_insufficient_when_games_below_min(self):
        a = me.evaluate(mk(home_off_games=19), _ASOF)
        assert a.analysis_state == me.INSUFFICIENT_EVIDENCE
        assert "F2_team_offense" in a.missing_or_invalid_inputs

    def test_era_out_of_range_invalid(self):
        a = me.evaluate(mk(home_sp_era=25.0), _ASOF)
        assert a.analysis_state == me.INSUFFICIENT_EVIDENCE

    def test_rpg_out_of_range_invalid(self):
        a = me.evaluate(mk(home_off_rpg=20.0), _ASOF)
        assert a.analysis_state == me.INSUFFICIENT_EVIDENCE

    def test_none_required_input_invalid(self):
        a = me.evaluate(mk(home_sp_era=None), _ASOF)
        assert a.analysis_state == me.INSUFFICIENT_EVIDENCE

    def test_innings_display_token_dot1_rejected(self):
        a = me.evaluate(mk(home_sp_ip=20.1), _ASOF)
        assert a.analysis_state == me.INSUFFICIENT_EVIDENCE

    def test_innings_display_token_dot2_rejected(self):
        a = me.evaluate(mk(away_sp_ip=33.2), _ASOF)
        assert a.analysis_state == me.INSUFFICIENT_EVIDENCE

    def test_true_innings_thirds_accepted(self):
        a = me.evaluate(mk(home_sp_ip=180.3333, away_sp_ip=180.6667), _ASOF)
        assert a.analysis_state == me.ASSESSED

    def test_presence_gate_fails_closed(self):
        a = me.evaluate(mk(home_probable_present=False), _ASOF)
        assert a.analysis_state == me.INSUFFICIENT_EVIDENCE
        assert "home_probable_starter" in a.missing_or_invalid_inputs

    def test_bool_games_rejected(self):
        a = me.evaluate(mk(home_off_games=True), _ASOF)
        assert a.analysis_state == me.INSUFFICIENT_EVIDENCE


# --- Missing-F3 conservative interval (PM-1289) -------------------------------
class TestMissingF3Interval:
    def _base(self, s1_era, s2_rpg, **kw):
        return mk(home_sp_era=s1_era[0], away_sp_era=s1_era[1],
                  home_off_rpg=s2_rpg[0], away_off_rpg=s2_rpg[1], **kw)

    def test_ce1_observed_balanced_vs_missing_uncertainty(self):
        # s1=+0.20 (era 4.9/5.3), s2=+0.20 (rpg 4.3/4.0) => B=0.1700
        base = dict(home_sp_era=4.9, away_sp_era=5.3, home_off_rpg=4.3, away_off_rpg=4.0)
        obs = me.evaluate(mk(**base, home_bp_rest=0.0, away_bp_rest=1.0), _ASOF)  # s3=-1 -> A=0.0200
        assert obs.analysis_state == me.NO_SELECTION
        assert obs.no_selection_reason == me.REASON_BALANCED_OBSERVED
        assert obs.aggregate_score == pytest.approx(0.0200)
        miss = me.evaluate(mk(**base, home_bp_rest=None, away_bp_rest=None), _ASOF)  # L=0.02,U=0.32,D=0.02
        assert miss.analysis_state == me.NO_SELECTION
        assert miss.no_selection_reason == me.REASON_OPTIONAL_UNCERTAINTY
        assert miss.aggregate_score == pytest.approx(0.0200)
        assert miss.coverage == pytest.approx(0.85)

    def test_ce2_missing_matches_worst_case(self):
        # s1=+0.40 (era 3.3/4.1), s2=+0.30 (rpg 4.45/4.0) => B=0.3050
        base = dict(home_sp_era=3.3, away_sp_era=4.1, home_off_rpg=4.45, away_off_rpg=4.0)
        obs = me.evaluate(mk(**base, home_bp_rest=0.0, away_bp_rest=1.0), _ASOF)  # A=0.1550 Low
        assert obs.directional_selection == me.HOME
        assert obs.assessment_confidence == me.LOW
        assert obs.aggregate_score == pytest.approx(0.1550)
        miss = me.evaluate(mk(**base, home_bp_rest=None, away_bp_rest=None), _ASOF)  # D=L=0.1550
        assert miss.directional_selection == me.HOME
        assert miss.assessment_confidence == me.LOW
        assert miss.aggregate_score == pytest.approx(0.1550)
        assert miss.coverage == pytest.approx(0.85)

    def test_away_side_mirror(self):
        # s1=-0.40, s2=-0.30 -> B=-0.3050 ; missing U=-0.1550 -> away Low
        base = dict(home_sp_era=4.1, away_sp_era=3.3, home_off_rpg=4.0, away_off_rpg=4.45)
        miss = me.evaluate(mk(**base, home_bp_rest=None, away_bp_rest=None), _ASOF)
        assert miss.directional_selection == me.AWAY
        assert miss.assessment_confidence == me.LOW
        assert miss.aggregate_score == pytest.approx(-0.1550)

    def test_strong_case_still_selects_missing(self):
        # s1=1.0, s2=0.8 -> B=0.7800 ; missing L=0.6300 -> base High capped Moderate
        miss = me.evaluate(mk(home_bp_rest=None, away_bp_rest=None), _ASOF)
        assert miss.directional_selection == me.HOME
        assert miss.assessment_confidence == me.MODERATE
        assert miss.aggregate_score == pytest.approx(0.6300)

    def test_interval_spanning_zero_is_uncertainty(self):
        # B=0.1000 (s1=0.10 era 3.0/3.2, s2~0.1429) -> L=-0.0500,U=0.2500 -> D=0 -> NO_SELECTION uncertainty
        base = dict(home_sp_era=3.0, away_sp_era=3.2, home_off_rpg=4.2143, away_off_rpg=4.0)
        miss = me.evaluate(mk(**base, home_bp_rest=None, away_bp_rest=None), _ASOF)
        assert miss.analysis_state == me.NO_SELECTION
        assert miss.no_selection_reason == me.REASON_OPTIONAL_UNCERTAINTY
        assert miss.aggregate_score == pytest.approx(0.0)

    def test_missing_threshold_inclusive(self):
        # B=0.2500 (s1=0.5 era 3.0/4.0, s2=0) -> L=0.1000 -> select Low (inclusive)
        base = dict(home_sp_era=3.0, away_sp_era=4.0, home_off_rpg=4.0, away_off_rpg=4.0)
        miss = me.evaluate(mk(**base, home_bp_rest=None, away_bp_rest=None), _ASOF)
        assert miss.aggregate_score == pytest.approx(0.1000)
        assert miss.directional_selection == me.HOME
        assert miss.assessment_confidence == me.LOW

    def test_missing_just_below_threshold(self):
        # B=0.2499 -> L=0.0999 -> NO_SELECTION. Use s1=0.4998 (era 3.0/3.9996)
        base = dict(home_sp_era=3.0, away_sp_era=3.9996, home_off_rpg=4.0, away_off_rpg=4.0)
        miss = me.evaluate(mk(**base, home_bp_rest=None, away_bp_rest=None), _ASOF)
        assert miss.aggregate_score == pytest.approx(0.0999)
        assert miss.analysis_state == me.NO_SELECTION

    def test_missing_f3_named_and_capped(self):
        a = me.evaluate(mk(home_bp_rest=None, away_bp_rest=None), _ASOF)
        assert any("F3" in x for x in a.missing_or_invalid_inputs)
        assert a.assessment_confidence in (me.LOW, me.MODERATE)  # never High while F3 missing

    def test_invalid_f3_treated_absent(self):
        # out-of-range bullpen rest -> treated absent -> coverage 0.85
        a = me.evaluate(mk(home_bp_rest=1.5, away_bp_rest=0.5), _ASOF)
        assert a.coverage == pytest.approx(0.85)
        assert a.missingness_treatment == me.MISSINGNESS_F3_RESERVED


# --- Missingness monotonicity (finite deterministic sweep) --------------------
class TestMissingnessMonotonicity:
    """Finite coverage of the invariant. NOT the contract's general mathematical
    argument (PM-1289 §2); this exercises many edge cases deterministically."""

    def _grid(self):
        eras = [2.5, 3.0, 3.5, 4.0, 4.6]
        rpgs = [3.8, 4.0, 4.4, 5.0]
        rests = [(0.0, 0.0), (0.5, 0.5), (1.0, 0.0), (0.0, 1.0), (0.7, 0.5), (0.5, 0.7), (1.0, 1.0)]
        for he in eras:
            for ae in eras:
                for hr in rpgs:
                    for ar in rpgs:
                        yield he, ae, hr, ar, rests

    def test_removing_f3_never_improves(self):
        checked = 0
        for he, ae, hr, ar, rests in self._grid():
            base = dict(home_sp_era=he, away_sp_era=ae, home_off_rpg=hr, away_off_rpg=ar)
            miss = me.evaluate(mk(**base, home_bp_rest=None, away_bp_rest=None), _ASOF)
            miss_rank = me._BAND_RANK[miss.assessment_confidence]
            for hb, ab in rests:
                obs = me.evaluate(mk(**base, home_bp_rest=hb, away_bp_rest=ab), _ASOF)
                checked += 1
                # coverage cannot increase when removing F3
                assert miss.coverage <= obs.coverage + 1e-12
                # displayed confidence cannot increase
                assert miss_rank <= me._BAND_RANK[obs.assessment_confidence]
                # conservative margin cannot exceed the observed margin
                assert (miss.directional_margin or 0.0) <= (obs.directional_margin or 0.0) + 1e-9
                # removing F3 cannot create a selection the observed case lacked
                if obs.directional_selection is None:
                    assert miss.directional_selection is None
                # if missing selects, observed selects the SAME side (no reversal)
                if miss.directional_selection is not None:
                    assert obs.directional_selection == miss.directional_selection
        assert checked > 500  # meaningful finite coverage


# --- Balanced vs uncertainty distinction --------------------------------------
class TestNoSelectionReasons:
    def test_balanced_requires_observed_f3(self):
        a = me.evaluate(mk(home_sp_era=3.0, away_sp_era=3.36, home_off_rpg=4.0, away_off_rpg=4.0,
                           home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)
        assert a.no_selection_reason == me.REASON_BALANCED_OBSERVED
        assert a.coverage == pytest.approx(1.00)

    def test_uncertainty_requires_missing_f3(self):
        a = me.evaluate(mk(home_sp_era=3.0, away_sp_era=3.2, home_off_rpg=4.2143, away_off_rpg=4.0,
                           home_bp_rest=None, away_bp_rest=None), _ASOF)
        assert a.no_selection_reason == me.REASON_OPTIONAL_UNCERTAINTY
        assert a.coverage == pytest.approx(0.85)


# --- Time contract & neutral quotes -------------------------------------------
class TestTimeAndQuotes:
    def test_naive_as_of_raises(self):
        with pytest.raises(me.MoneylineEvaluatorError):
            me.evaluate(mk(), datetime(2024, 6, 15, 18, 0))

    def test_future_required_evidence_excluded_insufficient(self):
        a = me.evaluate(mk(f2_observed_at=_ASOF + timedelta(hours=1)), _ASOF)
        assert a.analysis_state == me.INSUFFICIENT_EVIDENCE
        assert any("F2_excluded_future" in x for x in a.missing_or_invalid_inputs)

    def test_naive_evidence_excluded_insufficient(self):
        a = me.evaluate(mk(f1_observed_at=datetime(2024, 6, 15, 1, 0)), _ASOF)
        assert a.analysis_state == me.INSUFFICIENT_EVIDENCE
        assert any("F1_excluded_naive" in x for x in a.missing_or_invalid_inputs)

    def test_future_optional_f3_excluded_treated_missing(self):
        a = me.evaluate(mk(f3_observed_at=_ASOF + timedelta(hours=1)), _ASOF)
        assert a.analysis_state in (me.ASSESSED, me.NO_SELECTION)
        assert a.coverage == pytest.approx(0.85)

    def test_quote_present(self):
        q = me.QuoteContext(game_pk="700001", side="home", american_odds=-120,
                            observed_at=_ASOF - timedelta(hours=1), sportsbook="FANDUEL_ON",
                            jurisdiction="Ontario")
        a = me.evaluate(mk(), _ASOF, quote_context=[q])
        assert a.quote_context.status == me.Q_PRESENT
        assert a.quote_context.american_odds == -120

    def test_quote_age_boundary_inclusive_24h(self):
        q = me.QuoteContext(game_pk="700001", side="home", american_odds=-120,
                            observed_at=_ASOF - timedelta(hours=24))
        assert me.evaluate(mk(), _ASOF, quote_context=[q]).quote_context.status == me.Q_PRESENT
        q2 = me.QuoteContext(game_pk="700001", side="home", american_odds=-120,
                             observed_at=_ASOF - timedelta(hours=24, seconds=1))
        assert me.evaluate(mk(), _ASOF, quote_context=[q2]).quote_context.status == me.Q_STALE

    def test_quote_future(self):
        q = me.QuoteContext(game_pk="700001", side="home", american_odds=-120,
                            observed_at=_ASOF + timedelta(minutes=1))
        assert me.evaluate(mk(), _ASOF, quote_context=[q]).quote_context.status == me.Q_FUTURE

    def test_quote_malformed_odds(self):
        q = me.QuoteContext(game_pk="700001", side="home", american_odds=50,
                            observed_at=_ASOF - timedelta(hours=1))
        assert me.evaluate(mk(), _ASOF, quote_context=[q]).quote_context.status == me.Q_MALFORMED

    def test_quote_contradictory(self):
        q1 = me.QuoteContext(game_pk="700001", side="home", american_odds=-120,
                             observed_at=_ASOF - timedelta(hours=1))
        q2 = me.QuoteContext(game_pk="700001", side="home", american_odds=100,
                             observed_at=_ASOF - timedelta(hours=1))
        a = me.evaluate(mk(), _ASOF, quote_context=[q1, q2])
        assert a.quote_context.status == me.Q_CONTRADICTORY
        assert a.quote_context.american_odds is None  # none attached

    def test_quote_absent(self):
        a = me.evaluate(mk(), _ASOF)
        assert a.quote_context.status == me.Q_ABSENT

    def test_quote_does_not_change_analysis(self):
        base = me.evaluate(mk(), _ASOF)
        for odds in (-120, 100, 250, -300):
            q = me.QuoteContext(game_pk="700001", side="home", american_odds=odds,
                                observed_at=_ASOF - timedelta(hours=1))
            a = me.evaluate(mk(), _ASOF, quote_context=[q])
            assert (a.directional_selection, a.assessment_confidence, a.aggregate_score) == \
                   (base.directional_selection, base.assessment_confidence, base.aggregate_score)


# --- Neutrality, official status, no invented probability ---------------------
class TestNeutralityAndOfficialStatus:
    def test_official_status_not_evaluated_everywhere(self):
        for a in (me.evaluate(mk(), _ASOF),
                  me.evaluate(mk(away_sp_ip=12.0), _ASOF),
                  me.evaluate(mk(home_sp_era=3.0, away_sp_era=3.36, home_off_rpg=4.0, away_off_rpg=4.0,
                                 home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)):
            assert a.official_status == "NOT_EVALUATED — not an official paper bet"

    def test_no_probability_or_price_fields(self):
        a = me.evaluate(mk(), _ASOF)
        for banned in ("implied_probability", "win_probability", "fair_odds", "ev",
                       "expected_value", "clv", "favorable"):
            assert not hasattr(a, banned)

    def test_no_selection_not_a_pass(self):
        a = me.evaluate(mk(home_sp_era=3.0, away_sp_era=3.36, home_off_rpg=4.0, away_off_rpg=4.0,
                           home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)
        assert a.analysis_state == me.NO_SELECTION
        assert a.official_status.startswith("NOT_EVALUATED")

    def test_method_version(self):
        assert me.evaluate(mk(), _ASOF).method_version == "ml-eval-v0"


# --- Determinism & no input mutation ------------------------------------------
class TestDeterminismAndPurity:
    def test_deterministic_repeat(self):
        a1 = me.evaluate(mk(), _ASOF)
        a2 = me.evaluate(mk(), _ASOF)
        assert a1 == a2

    def test_inputs_not_mutated(self):
        inp = mk()
        snapshot = dataclasses.asdict(inp)
        me.evaluate(inp, _ASOF)
        assert dataclasses.asdict(inp) == snapshot

    def test_frozen_inputs(self):
        inp = mk()
        with pytest.raises(dataclasses.FrozenInstanceError):
            inp.home_sp_era = 1.0  # type: ignore[misc]
