"""Offline unit tests for backend.oracle.live_schedule (PM-1271).

Pure parser / normalizer tests using controlled inputs. No network is
performed: fetch_live_schedule()/retrieve(LIVE) are never called here; live
transport is validated in Layer 2 with an injected session (disposable-DB
cycle) or the separately-authorized bounded live-field gate.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.oracle import live_schedule as ls
from backend.oracle import underlying_identity as ui

_UTC = timezone.utc
_SLATE = "2026-07-25"
_RET = datetime(2026, 7, 25, 12, 0, tzinfo=_UTC)


def _game(**overrides):
    base = {
        "gamePk": 746484,
        "gameDate": "2026-07-25T17:10:00Z",
        "status": {"detailedState": "Scheduled"},
        "teams": {
            "home": {"team": {"abbreviation": "NYY"}},
            "away": {"team": {"abbreviation": "BOS"}},
        },
        "venue": {"name": "Yankee Stadium"},
    }
    base.update(overrides)
    return base


def _norm(raw, ns=ui.SOURCE_NAMESPACE_MLB, sgd="2026-07-25"):
    return ls.normalize_game(raw, _SLATE, ns, sgd)


class TestNormalizeGameAdmitted:
    def test_ordinary_game_admitted(self):
        r = _norm(_game())
        assert isinstance(r, ls.NormalizedGame)
        assert r.disposition == ls.DISPOSITION_ADMITTED
        assert r.game_pk == "746484"
        assert (r.away_team, r.home_team) == ("BOS", "NYY")
        assert r.game_status == ls.STATUS_SCHEDULED
        assert r.scheduled_start_at == datetime(2026, 7, 25, 17, 10, tzinfo=_UTC)

    def test_start_is_game_date_utc_not_slate_date(self):
        # Night game whose UTC calendar date rolls to the next day.
        r = _norm(_game(gameDate="2026-07-26T00:10:00Z"))
        assert isinstance(r, ls.NormalizedGame)
        assert r.scheduled_start_at == datetime(2026, 7, 26, 0, 10, tzinfo=_UTC)

    def test_eastern_offset_normalized_to_utc(self):
        r = _norm(_game(gameDate="2026-07-25T13:10:00-04:00"))
        assert isinstance(r, ls.NormalizedGame)
        assert r.scheduled_start_at == datetime(2026, 7, 25, 17, 10, tzinfo=_UTC)

    def test_pregame_and_warmup_are_eligible(self):
        for state in ("Pre-Game", "Warmup"):
            assert isinstance(_norm(_game(status={"detailedState": state})), ls.NormalizedGame)


class TestNormalizeGameExcluded:
    def test_unknown_status_fails_closed(self):
        r = _norm(_game(status={"detailedState": "Weather Watch"}))
        assert isinstance(r, ls.ExcludedGame)
        assert r.reason == ls.REASON_UNKNOWN_STATUS

    def test_ineligible_status_excluded(self):
        for state in ("Final", "In Progress", "Postponed", "Suspended", "Cancelled"):
            r = _norm(_game(status={"detailedState": state}))
            assert isinstance(r, ls.ExcludedGame)
            assert r.reason == ls.REASON_INELIGIBLE_STATUS

    def test_tbd_start_excluded(self):
        r = _norm(_game(status={"detailedState": "Scheduled", "startTimeTBD": True}))
        assert isinstance(r, ls.ExcludedGame)
        assert r.reason == ls.REASON_TBD_START

    def test_missing_identity_excluded(self):
        r = _norm(_game(gamePk=None))
        assert isinstance(r, ls.ExcludedGame)
        assert r.reason == ls.REASON_MISSING_IDENTITY

    def test_non_numeric_identity_excluded(self):
        r = _norm(_game(gamePk="74x"))
        assert isinstance(r, ls.ExcludedGame)
        assert r.reason == ls.REASON_MISSING_IDENTITY

    def test_missing_teams_excluded(self):
        r = _norm(_game(teams={"home": {}, "away": {}}))
        assert isinstance(r, ls.ExcludedGame)
        assert r.reason == ls.REASON_MISSING_TEAMS

    def test_invalid_start_excluded(self):
        r = _norm(_game(gameDate="not-a-date"))
        assert isinstance(r, ls.ExcludedGame)
        assert r.reason == ls.REASON_INVALID_START


class TestNormalizeResponse:
    def _resp(self, games, sgd="2026-07-25"):
        return {"dates": [{"date": sgd, "games": games}]}

    def test_empty_response_is_no_games_not_error(self):
        snap = ls.normalize_response(self._resp([]), _SLATE, _RET,
                                     mode=ls.MODE_LIVE, source="s")
        assert snap.empty is True
        assert snap.included == ()

    def test_no_dates_key_is_malformed_error(self):
        with pytest.raises(ls.ScheduleRetrievalError):
            ls.normalize_response({}, _SLATE, _RET, mode=ls.MODE_LIVE, source="s")

    def test_games_not_a_list_is_error(self):
        with pytest.raises(ls.ScheduleRetrievalError):
            ls.normalize_response({"dates": [{"date": "x", "games": "nope"}]},
                                  _SLATE, _RET, mode=ls.MODE_LIVE, source="s")

    def test_naive_retrieved_at_rejected(self):
        with pytest.raises(ls.ScheduleRetrievalError):
            ls.normalize_response(self._resp([]), _SLATE, datetime(2026, 7, 25, 12, 0),
                                  mode=ls.MODE_LIVE, source="s")

    def test_admitted_and_excluded_partition(self):
        snap = ls.normalize_response(
            self._resp([_game(), _game(gamePk=746485, status={"detailedState": "Final"},
                                       teams={"home": {"team": {"abbreviation": "LAD"}},
                                              "away": {"team": {"abbreviation": "SFG"}}})]),
            _SLATE, _RET, mode=ls.MODE_LIVE, source="s")
        assert len(snap.included) == 1
        assert len(snap.excluded) == 1
        assert snap.empty is False

    def test_identical_duplicate_deduped(self):
        snap = ls.normalize_response(self._resp([_game(), _game()]), _SLATE, _RET,
                                     mode=ls.MODE_LIVE, source="s")
        assert len(snap.included) == 1

    def test_conflicting_duplicate_excluded_failclosed(self):
        snap = ls.normalize_response(
            self._resp([_game(), _game(gameDate="2026-07-25T20:45:00Z")]),
            _SLATE, _RET, mode=ls.MODE_LIVE, source="s")
        assert snap.included == ()
        assert any(e.reason == ls.REASON_CONFLICTING_DUPLICATE for e in snap.excluded)

    def test_doubleheader_distinct_gamepks_remain_distinct(self):
        g1 = _game(gamePk=746484)
        g2 = _game(gamePk=746485, gameDate="2026-07-25T20:45:00Z")
        snap = ls.normalize_response(self._resp([g1, g2]), _SLATE, _RET,
                                     mode=ls.MODE_LIVE, source="s")
        assert {g.game_pk for g in snap.included} == {"746484", "746485"}

    def test_live_mode_uses_mlb_namespace(self):
        snap = ls.normalize_response(self._resp([_game()]), _SLATE, _RET,
                                     mode=ls.MODE_LIVE, source="s")
        assert snap.included[0].source_namespace == ui.SOURCE_NAMESPACE_MLB

    def test_fixture_mode_uses_fixture_namespace(self):
        snap = ls.normalize_response(self._resp([_game()]), _SLATE, _RET,
                                     mode=ls.MODE_FIXTURE, source="s")
        assert snap.included[0].source_namespace == ui.SOURCE_NAMESPACE_FIXTURE


class TestFixtureMode:
    def test_retrieve_fixture_snapshot(self):
        snap = ls.retrieve(ls.MODE_FIXTURE, _SLATE)
        assert snap.mode == ls.MODE_FIXTURE
        assert snap.source_namespace() == ui.SOURCE_NAMESPACE_FIXTURE
        assert len(snap.included) == 2
        assert {g.game_pk for g in snap.included} == {"746484", "746485"}

    def test_unknown_mode_raises(self):
        with pytest.raises(ls.ScheduleRetrievalError):
            ls.retrieve("bogus", _SLATE)


class TestLiveTransportInjectedSession:
    """Live path via an injected fake session — still no real network."""

    class _FakeResp:
        def __init__(self, payload, status_ok=True):
            self._payload = payload
            self._ok = status_ok

        def raise_for_status(self):
            if not self._ok:
                import requests
                raise requests.exceptions.HTTPError("boom")

        def json(self):
            return self._payload

    class _FakeSession:
        def __init__(self, resp):
            self._resp = resp

        def get(self, url, params=None, timeout=None):
            return self._resp

    def test_live_success_via_injected_session(self):
        payload = {"dates": [{"date": "2026-07-25", "games": [_game()]}]}
        session = self._FakeSession(self._FakeResp(payload))
        snap = ls.retrieve(ls.MODE_LIVE, _SLATE, session=session)
        assert snap.mode == ls.MODE_LIVE
        assert len(snap.included) == 1
        assert snap.source_namespace() == ui.SOURCE_NAMESPACE_MLB

    def test_live_http_error_fails_closed(self):
        session = self._FakeSession(self._FakeResp({}, status_ok=False))
        with pytest.raises(ls.ScheduleRetrievalError):
            ls.retrieve(ls.MODE_LIVE, _SLATE, session=session)
