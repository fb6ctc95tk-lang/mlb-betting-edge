"""Offline unit tests for backend.oracle.daily_ranking (PM-1287 §D / PM-1289 §4).

Pure — no DB, no network, no clock. Builds real assessments via the evaluator on
synthetic contract inputs, then verifies deterministic ranking, full-SUI identity
(duplicates, conflicts, cross-namespace separation), tie-breaking, input-order
invariance, empty input, absence of any three-play cap, and the price-bearing
split. Expected orderings are reasoned from the contract, not read back from the
ranker.
"""

from __future__ import annotations

import dataclasses
import itertools
from datetime import datetime, timedelta, timezone

import pytest

from backend.oracle import daily_ranking as dr
from backend.oracle import moneyline_evaluator as me

_UTC = timezone.utc
_ASOF = datetime(2024, 6, 15, 18, 0, tzinfo=_UTC)


def _inp(game_pk, ns="mlb-statsapi", **kw):
    base = dict(
        source_namespace=ns, sport_id=1, game_pk=game_pk, home_team="HOME", away_team="AWAY",
        home_sp_era=2.80, away_sp_era=4.90, home_sp_ip=180.0, away_sp_ip=180.0,
        home_off_rpg=5.2, away_off_rpg=4.0, home_off_games=60, away_off_games=60,
        home_bp_rest=0.7, away_bp_rest=0.5,
    )
    base.update(kw)
    return me.MoneylineInputs(**base)


def high(game_pk, ns="mlb-statsapi", quote=None):
    # E1 -> High, margin 0.8100, coverage 1.00
    return me.evaluate(_inp(game_pk, ns), _ASOF, quote_context=quote)


def high_mid(game_pk, ns="mlb-statsapi"):
    # s1=1.0 (era 3.0/5.0), s2=0, s3=0 -> A=0.5000 -> High, margin 0.5000
    return me.evaluate(_inp(game_pk, ns, home_sp_era=3.0, away_sp_era=5.0, home_off_rpg=4.0,
                            away_off_rpg=4.0, home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)


def moderate(game_pk, ns="mlb-statsapi"):
    # E2 -> Moderate 0.2700
    return me.evaluate(_inp(game_pk, ns, home_sp_era=3.50, away_sp_era=4.30, home_off_rpg=4.5,
                            away_off_rpg=4.2, home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)


def low(game_pk, ns="mlb-statsapi"):
    # E4 -> Low 0.1000
    return me.evaluate(_inp(game_pk, ns, home_sp_era=3.0, away_sp_era=3.4, home_off_rpg=4.0,
                            away_off_rpg=4.0, home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)


def no_sel(game_pk, ns="mlb-statsapi"):
    # balanced NO_SELECTION (A=0.0900)
    return me.evaluate(_inp(game_pk, ns, home_sp_era=3.0, away_sp_era=3.36, home_off_rpg=4.0,
                            away_off_rpg=4.0, home_bp_rest=0.5, away_bp_rest=0.5), _ASOF)


def insufficient(game_pk, ns="mlb-statsapi"):
    return me.evaluate(_inp(game_pk, ns, away_sp_ip=12.0), _ASOF)


class TestEligibilityFilter:
    def test_excludes_no_selection_and_insufficient(self):
        ranked = dr.rank([high("700001"), no_sel("700002"), insufficient("700003")])
        assert [a.game_pk for a in ranked] == ["700001"]

    def test_empty_input(self):
        assert dr.rank([]) == []

    def test_more_than_three_selections_no_cap(self):
        ranked = dr.rank([high("700001"), high("700002"), high("700003"),
                          high("700004"), high("700005")])
        assert len(ranked) == 5


class TestOrdering:
    def test_confidence_then_margin(self):
        ranked = dr.rank([low("700004"), moderate("700003"), high_mid("700002"), high("700001")])
        # High(0.81) > High(0.50) > Moderate(0.27) > Low(0.10)
        assert [a.game_pk for a in ranked] == ["700001", "700002", "700003", "700004"]
        assert [a.assessment_confidence for a in ranked] == [me.HIGH, me.HIGH, me.MODERATE, me.LOW]

    def test_margin_desc_within_band(self):
        ranked = dr.rank([high_mid("700002"), high("700001")])  # 0.50 vs 0.81
        assert [a.game_pk for a in ranked] == ["700001", "700002"]

    def test_coverage_tiebreak(self):
        # Both Moderate at margin 0.6300; observed coverage 1.00 outranks missing-F3 coverage 0.85.
        observed_mod = me.evaluate(_inp("700001", home_bp_rest=0.0, away_bp_rest=1.0,
                                        home_lineup_status=me.PARTIAL), _ASOF)  # A=0.63, capped Moderate
        missing_mod = me.evaluate(_inp("700002", home_bp_rest=None, away_bp_rest=None), _ASOF)  # D=0.63, Mod
        assert observed_mod.assessment_confidence == me.MODERATE
        assert missing_mod.assessment_confidence == me.MODERATE
        assert observed_mod.directional_margin == pytest.approx(0.63)
        assert missing_mod.directional_margin == pytest.approx(0.63)
        ranked = dr.rank([missing_mod, observed_mod])
        assert [a.game_pk for a in ranked] == ["700001", "700002"]  # coverage 1.00 first

    def test_gamepk_ascending_tiebreak(self):
        ranked = dr.rank([high("700002"), high("700001")])  # identical strength
        assert [a.game_pk for a in ranked] == ["700001", "700002"]

    def test_gamepk_numeric_not_lexicographic(self):
        ranked = dr.rank([high("70010"), high("7009")])  # numeric: 7009 < 70010
        assert [a.game_pk for a in ranked] == ["7009", "70010"]

    def test_input_order_invariance(self):
        entries = [high("700001"), high_mid("700002"), moderate("700003"), low("700004")]
        forward = [a.game_pk for a in dr.rank(entries)]
        backward = [a.game_pk for a in dr.rank(list(reversed(entries)))]
        assert forward == backward == ["700001", "700002", "700003", "700004"]


class TestFullSuiIdentity:
    def test_cross_namespace_not_merged(self):
        a = high("700001", ns="mlb-statsapi")
        b = high("700001", ns="fixture")
        ranked = dr.rank([a, b])
        # distinct SUIs -> both kept; tie on game_pk -> sui_string ASC ('fixture' < 'mlb-statsapi')
        assert len(ranked) == 2
        assert [x.source_namespace for x in ranked] == ["fixture", "mlb-statsapi"]

    def test_identical_duplicate_collapses(self):
        a = high("700001")
        b = high("700001")  # identical content, same SUI
        assert a == b
        ranked = dr.rank([a, b])
        assert len(ranked) == 1

    def test_conflicting_duplicate_fails_closed(self):
        a = high("700001")
        b = moderate("700001")  # same SUI, differing content
        ranked = dr.rank([a, b, high("700002")])
        assert [x.game_pk for x in ranked] == ["700002"]  # conflicted SUI excluded
        report = dr.dedupe_report([a, b, high("700002")])
        assert any(c["sui"]["game_pk"] == "700001" for c in report["conflicts"])

    def test_conflict_does_not_affect_others(self):
        ranked = dr.rank([high("700001"), moderate("700001"), high_mid("700002"), low("700003")])
        assert [x.game_pk for x in ranked] == ["700002", "700003"]


class TestPriceBearing:
    def _quote(self, gp, present=True):
        obs = _ASOF - timedelta(hours=1) if present else _ASOF + timedelta(hours=1)
        return [me.QuoteContext(game_pk=gp, side="home", american_odds=-120, observed_at=obs,
                                sportsbook="FANDUEL_ON", jurisdiction="Ontario")]

    def test_price_bearing_subset(self):
        with_price = high("700001", quote=self._quote("700001", present=True))
        no_price = high("700002")
        future_price = high("700003", quote=self._quote("700003", present=False))
        entries = [with_price, no_price, future_price]
        assert [a.game_pk for a in dr.rank(entries)] == ["700001", "700002", "700003"]
        assert [a.game_pk for a in dr.price_bearing(entries)] == ["700001"]

    def test_price_bearing_preserves_rank_order(self):
        a = high("700002", quote=self._quote("700002", present=True))
        b = high("700001", quote=self._quote("700001", present=True))
        pb = dr.price_bearing([a, b])
        assert [x.game_pk for x in pb] == ["700001", "700002"]


class TestModelVersion:
    def test_version(self):
        assert dr.MODEL_VERSION == "daily-rank-v0"


def _present_quote(gp="700001"):
    return [me.QuoteContext(game_pk=gp, side="home", american_odds=-120,
                            observed_at=_ASOF - timedelta(hours=1), sportsbook="FANDUEL_ON",
                            jurisdiction="Ontario", provenance="feedA")]


class TestDuplicateContentConflict:
    """PM-1301 regression: same-SUI assessments that differ in ANY decision-relevant
    content (quote, readiness, missing inputs, reasoning, timing, teams, method/
    provenance, official status) must fail closed as conflicting_duplicate rather
    than collapse first-input-wins. Genuinely identical assessments still collapse;
    contract-equivalent representations (dict key order, equal-instant datetimes)
    do not create a false conflict. Public paths (rank / price_bearing /
    dedupe_report) are exercised, not only the internal helper."""

    # --- A: quote presence (PRESENT vs ABSENT) ---
    def test_present_vs_absent_quote_conflicts_both_orders(self):
        a_present = high("700001", quote=_present_quote())
        a_absent = high("700001")
        assert a_present != a_absent
        for entries in ([a_present, a_absent], [a_absent, a_present]):
            assert [x.game_pk for x in dr.rank(entries)] == []
            assert any(c["sui"]["game_pk"] == "700001"
                       for c in dr.dedupe_report(entries)["conflicts"])

    def test_present_vs_absent_price_bearing_order_invariant(self):
        a_present = high("700001", quote=_present_quote())
        a_absent = high("700001")
        assert dr.price_bearing([a_present, a_absent]) == dr.price_bearing([a_absent, a_present]) == []

    # --- B: quote content, provenance, timestamp ---
    def _q(self, **kw):
        base = dict(game_pk="700001", side="home", american_odds=-120,
                    observed_at=_ASOF - timedelta(hours=1), sportsbook="FANDUEL_ON",
                    jurisdiction="Ontario", provenance="feedA")
        base.update(kw)
        return [me.QuoteContext(**base)]

    def test_quote_odds_difference_conflicts(self):
        a1 = high("700001", quote=self._q(american_odds=-120))
        a2 = high("700001", quote=self._q(american_odds=-140))
        assert a1.quote_context.status == me.Q_PRESENT == a2.quote_context.status
        assert a1 != a2
        for entries in ([a1, a2], [a2, a1]):
            assert dr.rank(entries) == []
            assert any(c["sui"]["game_pk"] == "700001"
                       for c in dr.dedupe_report(entries)["conflicts"])

    def test_quote_provenance_difference_conflicts(self):
        a1 = high("700001", quote=self._q(provenance="feedA"))
        a2 = high("700001", quote=self._q(provenance="feedB"))
        assert a1 != a2
        assert dr.rank([a1, a2]) == [] and dr.rank([a2, a1]) == []

    def test_quote_timestamp_difference_conflicts(self):
        a1 = high("700001", quote=self._q(observed_at=_ASOF - timedelta(hours=1)))
        a2 = high("700001", quote=self._q(observed_at=_ASOF - timedelta(hours=2)))
        assert a1.quote_context.status == me.Q_PRESENT == a2.quote_context.status
        assert a1 != a2
        assert dr.rank([a1, a2]) == [] and dr.rank([a2, a1]) == []

    # --- C: non-quote content (readiness, teams, timing, method/provenance) ---
    def test_readiness_difference_conflicts(self):
        # Low base stays Low under a lineup cap, so analytics are identical while readiness differs.
        common = dict(home_sp_era=3.0, away_sp_era=3.4, home_off_rpg=4.0, away_off_rpg=4.0,
                      home_bp_rest=0.5, away_bp_rest=0.5)
        full = me.evaluate(_inp("700001", **common), _ASOF)
        partial = me.evaluate(_inp("700001", **common, home_lineup_status=me.PARTIAL), _ASOF)
        assert full.assessment_confidence == partial.assessment_confidence == me.LOW
        assert full.aggregate_score == partial.aggregate_score
        assert full.directional_margin == partial.directional_margin
        assert full != partial  # readiness differs
        assert dr.rank([full, partial]) == [] and dr.rank([partial, full]) == []

    def test_team_identity_difference_conflicts(self):
        a1 = high("700001")
        a2 = me.evaluate(_inp("700001", home_team="OTHER"), _ASOF)
        assert a1 != a2
        assert dr.rank([a1, a2]) == [] and dr.rank([a2, a1]) == []

    def test_scheduled_start_difference_conflicts(self):
        a1 = me.evaluate(_inp("700001", scheduled_start_at=datetime(2024, 6, 15, 23, 5, tzinfo=_UTC)), _ASOF)
        a2 = me.evaluate(_inp("700001", scheduled_start_at=datetime(2024, 6, 16, 1, 5, tzinfo=_UTC)), _ASOF)
        assert a1 != a2
        assert dr.rank([a1, a2]) == [] and dr.rank([a2, a1]) == []

    def test_method_provenance_difference_conflicts(self):
        a1 = high("700001")
        a2 = dataclasses.replace(a1, method_version="ml-eval-vX")
        assert a1 != a2
        assert dr.rank([a1, a2]) == [] and dr.rank([a2, a1]) == []

    def test_official_status_difference_conflicts(self):
        a1 = high("700001")
        a2 = dataclasses.replace(a1, official_status="SOMETHING_ELSE")
        assert a1 != a2
        assert dr.rank([a1, a2]) == [] and dr.rank([a2, a1]) == []

    def test_missing_inputs_difference_conflicts(self):
        a1 = high("700001")
        a2 = dataclasses.replace(a1, missing_or_invalid_inputs=("synthetic_missing_marker",))
        assert a1 != a2
        assert dr.rank([a1, a2]) == [] and dr.rank([a2, a1]) == []

    # --- Contract-equivalent representations must NOT create a false conflict ---
    def test_equivalent_as_of_instant_collapses(self):
        a1 = high("700001")
        a2 = dataclasses.replace(high("700001"),
                                 as_of_time=_ASOF.astimezone(timezone(timedelta(0))))
        assert a1 == a2  # same instant, equal offset -> equivalent
        assert [x.game_pk for x in dr.rank([a1, a2])] == ["700001"]

    def test_readiness_key_order_does_not_conflict(self):
        a1 = high("700001")
        reordered = dict(reversed(list(a1.readiness.items())))
        a2 = dataclasses.replace(high("700001"), readiness=reordered)
        assert a1 == a2  # dict equality is order-insensitive
        assert [x.game_pk for x in dr.rank([a1, a2])] == ["700001"]

    # --- D: true duplicate ---
    def test_true_duplicate_collapses_with_price_bearing(self):
        q = _present_quote("700001")
        a1 = high("700001", quote=q)
        a2 = high("700001", quote=q)
        assert a1 == a2
        assert [x.game_pk for x in dr.rank([a1, a2])] == ["700001"]
        assert [x.game_pk for x in dr.price_bearing([a1, a2])] == ["700001"]

    def test_true_duplicate_no_input_mutation(self):
        a1 = high("700001")
        a2 = high("700001")
        snap = (dataclasses.asdict(a1), dataclasses.asdict(a2))
        dr.rank([a1, a2])
        dr.price_bearing([a1, a2])
        dr.dedupe_report([a1, a2])
        assert (dataclasses.asdict(a1), dataclasses.asdict(a2)) == snap

    # --- E: three-member group (A, A, B); no later record restores eligibility ---
    def test_three_member_conflict_all_permutations(self):
        a = high("700001")
        a_dup = high("700001")               # identical to a
        b = high("700001", quote=_present_quote("700001"))  # conflicts (PRESENT vs ABSENT)
        assert a == a_dup and a != b
        for perm in itertools.permutations([a, a_dup, b]):
            entries = list(perm)
            assert dr.rank(entries) == []
            assert dr.price_bearing(entries) == []
            assert any(c["sui"]["game_pk"] == "700001"
                       for c in dr.dedupe_report(entries)["conflicts"])

    # --- F: unrelated games / namespaces unaffected ---
    def test_conflict_does_not_affect_other_games(self):
        a = high("700001")
        a_q = high("700001", quote=_present_quote("700001"))  # conflict on SUI 700001
        ranked = dr.rank([a, a_q, high_mid("700002"), moderate("700003")])
        assert [x.game_pk for x in ranked] == ["700002", "700003"]

    def test_cross_namespace_quote_difference_stays_distinct(self):
        a_mlb = high("700001", ns="mlb-statsapi", quote=_present_quote("700001"))
        a_fix = high("700001", ns="fixture")
        ranked = dr.rank([a_mlb, a_fix])
        assert len(ranked) == 2  # different namespaces => different SUIs, not a conflict
        assert {x.source_namespace for x in ranked} == {"mlb-statsapi", "fixture"}
