"""Oracle — fixture-context MANUAL paper-play settlement (PM-1161/1163/1165/1167 + addendum; PM-1169).

Settles a manually-recorded paper play (origin='MANUAL') against an explicit, caller-supplied,
VALIDATED fixture result. Moneyline only. This is the fixture-context MANUAL-settlement track — it is
NOT Stage-10 activation and does not touch the orchestrator/game/slate Stage-10 lifecycle.

Contract (accepted):
- Kill-switch FIRST. Validate the caller `result_record`, then build a FRESH canonical copy (never
  mutate caller input); normalize `game_status` via strip().lower(); map result_source := source.
- Verify persisted game/slate membership, unambiguous external-game binding, MANUAL origin, and
  TEST_FIXTURE provenance before settlement/replay.
- Canonical identity over 15 fields; full canonical-payload equality decides EXACT_REPLAY vs
  CHANGED_RESULT; the short `MSET-<play_id>-<digest>` is only a label. Caller `settled_at` is tz-aware,
  excluded from identity, and preserved on replay.
- Authoritative append-only `settlement_completed` event audit; fail-closed on missing/malformed/
  multiple/projection-conflicting history. One atomic play UPDATE + exactly one event; conditional-update
  losers reconcile against the winner's committed event.
- Decimal math, 4dp ROUND_HALF_UP canonical fixed-point strings; F7 dispositions; DEFER may settle later;
  explicit CLV-unavailable reason (clv/closing_odds stay NULL).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from backend.oracle import results_fixtures as rf
from backend.oracle.event_store import record_event
from backend.oracle.identifier_manager import InvalidConnectionStateError
from backend.oracle.kill_switch import is_autonomous_run_enabled

ORIGIN_MANUAL = "MANUAL"
CONTEXT_TEST_FIXTURE = rf.TEST_DATA_ORIGIN          # "TEST_FIXTURE"
FIXTURE_SOURCE = rf.FIXTURE_SOURCE                  # "results_fixture"
SETTLEMENT_EVENT = "settlement_completed"
CLV_UNAVAILABLE_REASON = "closing_line_not_captured"
_QUANT = Decimal("0.0001")

# Caller-visible outcomes
SETTLED_WIN = "SETTLED_WIN"
SETTLED_LOSS = "SETTLED_LOSS"
VOIDED = "VOIDED"
DEFERRED = "DEFERRED"
REJECTED_TIE = "REJECTED_TIE"
EXACT_REPLAY = "EXACT_REPLAY"
CHANGED_RESULT = "CHANGED_RESULT"

# 15 canonical identity fields (order documented; canonical JSON sorts keys)
IDENTITY_FIELDS = (
    "game_run_id", "slate_run_id", "play_id", "external_game_id", "market",
    "selected_side", "origin", "odds_at_nomination", "stake_units", "game_status",
    "home_score", "away_score", "result_source", "data_origin", "result_observed_at",
)


class ManualSettlementError(Exception):
    """Base class for manual settlement errors."""


class ManualSettlementValidationError(ManualSettlementError):
    """Invalid inputs (result_record, settled_at, market/side, tied-final rejection)."""


class ManualSettlementBindingError(ManualSettlementError):
    """Missing play, non-MANUAL origin, or game/slate/external-game binding mismatch."""


class ManualSettlementAuditError(ManualSettlementError):
    """Fail-closed: missing/malformed/multiple/projection-conflicting settlement history."""


class KillSwitchHaltError(ManualSettlementError):
    """Kill switch inactive; nothing read or written."""


@dataclass(frozen=True)
class ManualSettlementResult:
    outcome: str
    play_id: str
    settlement_result: str | None = None
    mock_pnl: str | None = None
    settlement_label: str | None = None
    settled_at: datetime | None = None
    divergence: dict = field(default_factory=dict)


# --- pure helpers ------------------------------------------------------------

def _decimal_str(value: object) -> str:
    return str(Decimal(value).quantize(_QUANT, rounding=ROUND_HALF_UP))


def _is_tz_aware(dt: object) -> bool:
    return isinstance(dt, datetime) and dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None


def american_profit(odds: int, stake: Decimal) -> Decimal:
    """Profit on a winning bet at American odds for a flat stake (Decimal, unrounded)."""
    if odds > 0:
        return stake * (Decimal(odds) / Decimal(100))
    return stake * (Decimal(100) / Decimal(abs(odds)))


def canonical_result_copy(result_record: dict) -> dict:
    """Validate (fail-closed) then return a FRESH canonical copy; caller input is never mutated.

    Only game_status is normalized (strip().lower()); other fields are copied as-is (already
    exact/typed by the validator). result_source is exposed as canonical_result['source'].
    """
    rf.validate_result_fixture_record(result_record)  # fail-closed; does not mutate
    canonical = dict(result_record)
    canonical["game_status"] = str(result_record["game_status"]).strip().lower()
    return canonical


def build_identity(play: dict, canonical: dict) -> dict:
    """The 15-field canonical identity dict (values normalized/canonicalized)."""
    return {
        "game_run_id": play["game_run_id"],
        "slate_run_id": play["slate_run_id"],
        "play_id": play["play_id"],
        "external_game_id": canonical["external_game_id"],
        "market": play["market"],
        "selected_side": play["selected_side"],
        "origin": play["origin"],
        "odds_at_nomination": int(play["odds_at_nomination"]),
        "stake_units": _decimal_str(play["stake_units"]),
        "game_status": canonical["game_status"],
        "home_score": canonical["home_score"],
        "away_score": canonical["away_score"],
        "result_source": canonical["source"],
        "data_origin": canonical["data_origin"],
        "result_observed_at": canonical["result_observed_at"],
    }


def canonical_identity_payload(identity: dict) -> str:
    """Canonical JSON string used for authoritative full-payload equality (sorted, compact)."""
    if set(identity) != set(IDENTITY_FIELDS):
        raise ManualSettlementValidationError(
            f"identity must have exactly the 15 canonical fields; got {sorted(identity)}"
        )
    return json.dumps(identity, sort_keys=True, separators=(",", ":"))


def mset_label(play_id: str, payload: str) -> str:
    """Short label ONLY (not authoritative for equality)."""
    return f"MSET-{play_id}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


# --- DB helpers --------------------------------------------------------------

_SQL_PLAY = (
    "SELECT game_run_id, slate_run_id, market, selected_side, origin, odds_at_nomination, "
    "stake_units, settlement_result, mock_pnl, play_status FROM oracle_plays WHERE play_id = %s"
)
_SQL_GAME_MATCHES = (
    "SELECT game_run_id FROM oracle_game_analyses "
    "WHERE slate_run_id = %s AND external_game_id = %s"
)
_SQL_EVENTS = (
    "SELECT event_payload FROM oracle_play_events "
    "WHERE play_id = %s AND event_type = 'settlement_completed' ORDER BY event_id"
)
_SQL_UPDATE = (
    "UPDATE oracle_plays SET settlement_result = %s, mock_pnl = %s, settled_at = %s, "
    "play_status = %s WHERE play_id = %s AND settlement_result IS NULL"
)


def _fetch_one(conn, sql, params):
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()


def _fetch_all(conn, sql, params):
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()


def _validate_identity_payload(s: object) -> dict:
    """Parse + validate a stored identity_payload against the complete 15-field canonical contract.

    Any deviation (bad JSON, missing/extra fields, wrong type/value, non-canonical serialization) is an
    AUDIT-INTEGRITY failure — never a CHANGED_RESULT.
    """
    if not isinstance(s, str):
        raise ManualSettlementAuditError("stored identity_payload is not a string")
    try:
        obj = json.loads(s)
    except Exception as exc:
        raise ManualSettlementAuditError(f"stored identity_payload is invalid JSON: {exc}")
    if not isinstance(obj, dict) or set(obj) != set(IDENTITY_FIELDS):
        raise ManualSettlementAuditError("stored identity_payload does not have exactly the 15 fields")
    try:
        if not (isinstance(obj["external_game_id"], str) and obj["external_game_id"].isdigit()):
            raise ValueError("external_game_id")
        if obj["origin"] != ORIGIN_MANUAL:
            raise ValueError("origin")
        if obj["market"] != "ML":
            raise ValueError("market")
        if obj["selected_side"] not in ("home", "away"):
            raise ValueError("selected_side")
        if type(obj["odds_at_nomination"]) is not int \
                or not (obj["odds_at_nomination"] >= 100 or obj["odds_at_nomination"] <= -100):
            raise ValueError("odds_at_nomination")
        if not isinstance(obj["stake_units"], str) or obj["stake_units"] != _decimal_str(obj["stake_units"]):
            raise ValueError("stake_units")
        if obj["game_status"] not in rf.RESULT_STATUSES:
            raise ValueError("game_status")
        for k in ("home_score", "away_score"):
            v = obj[k]
            if not (v is None or (type(v) is int and v >= 0)):
                raise ValueError(k)
        if obj["result_source"] != FIXTURE_SOURCE:
            raise ValueError("result_source")
        if obj["data_origin"] != CONTEXT_TEST_FIXTURE:
            raise ValueError("data_origin")
        if not (isinstance(obj["result_observed_at"], str) and rf._UTC_SYNTAX.match(obj["result_observed_at"])):
            raise ValueError("result_observed_at")
        for k in ("game_run_id", "slate_run_id", "play_id"):
            if not isinstance(obj[k], str) or not obj[k]:
                raise ValueError(k)
    except ValueError as exc:
        raise ManualSettlementAuditError(f"stored identity field invalid: {exc}")
    # Reuse the accepted fixture validator for the status/score relationship + real-date timestamp.
    try:
        rf.validate_result_fixture_record({
            "external_game_id": obj["external_game_id"], "game_status": obj["game_status"],
            "home_score": obj["home_score"], "away_score": obj["away_score"],
            "result_observed_at": obj["result_observed_at"], "source": obj["result_source"],
            "data_origin": obj["data_origin"],
        })
    except rf.ResultFixtureValidationError as exc:
        raise ManualSettlementAuditError(f"stored identity is not a valid fixture record: {exc}")
    # Must be able to represent an ACTUAL settlement under the finalized dispositions.
    st = obj["game_status"]
    if st in ("postponed", "suspended"):
        raise ManualSettlementAuditError(f"stored identity status {st!r} settles nothing (defer)")
    if st == "final" and obj["home_score"] == obj["away_score"]:
        raise ManualSettlementAuditError("stored identity is a tied final (no settlement possible)")
    if json.dumps(obj, sort_keys=True, separators=(",", ":")) != s:
        raise ManualSettlementAuditError("stored identity_payload is not canonical")
    return obj


def _authoritative_settlement(conn, play_id: str, play_row: dict, expected_external: str) -> dict:
    """Read the single authoritative settlement event; fail-closed on bad/inconsistent history."""
    rows = _fetch_all(conn, _SQL_EVENTS, (play_id,))
    if len(rows) == 0:
        raise ManualSettlementAuditError(
            f"play {play_id} is settled in projection but has NO settlement_completed event")
    if len(rows) > 1:
        raise ManualSettlementAuditError(
            f"play {play_id} has {len(rows)} settlement_completed events (conflicting history)")
    raw = rows[0][0]
    payload = raw if isinstance(raw, dict) else (json.loads(raw) if raw else None)
    if not isinstance(payload, dict) or "identity_payload" not in payload \
            or "settlement_result" not in payload or "settled_at" not in payload:
        raise ManualSettlementAuditError(f"play {play_id} settlement event payload is malformed")
    stored = _validate_identity_payload(payload["identity_payload"])  # structure/domain/fixture/settleable
    # Cross-check immutable identity fields against the ACTUAL persisted play + game binding.
    for k in ("play_id", "game_run_id", "slate_run_id", "origin", "market", "selected_side"):
        if stored[k] != play_row[k]:
            raise ManualSettlementAuditError(
                f"stored identity {k}={stored[k]!r} != persisted play {play_row[k]!r}")
    if int(stored["odds_at_nomination"]) != int(play_row["odds_at_nomination"]):
        raise ManualSettlementAuditError("stored identity odds_at_nomination != persisted play")
    if stored["stake_units"] != _decimal_str(play_row["stake_units"]):
        raise ManualSettlementAuditError("stored identity stake_units != persisted play")
    if str(stored["external_game_id"]) != str(expected_external):
        raise ManualSettlementAuditError("stored identity external_game_id != persisted game binding")
    # projection-conflict: stored audit must agree with oracle_plays current state.
    if payload.get("settlement_result") != play_row["settlement_result"]:
        raise ManualSettlementAuditError(f"play {play_id} audit/projection settlement_result conflict")
    stored_pnl = payload.get("mock_pnl")
    if play_row["mock_pnl"] is not None and stored_pnl is not None \
            and Decimal(stored_pnl) != Decimal(play_row["mock_pnl"]):
        raise ManualSettlementAuditError(f"play {play_id} audit/projection mock_pnl conflict")
    return payload


def _reconcile(conn, play_id: str, play_row: dict, expected_external: str,
               new_payload: str, new_identity: dict) -> ManualSettlementResult:
    """Compare the new canonical identity against the committed authoritative event (full payload)."""
    stored = _authoritative_settlement(conn, play_id, play_row, expected_external)
    stored_payload = stored["identity_payload"]
    stored_settled_at = stored["settled_at"]
    if stored_payload == new_payload:                      # full-payload equality (label irrelevant)
        return ManualSettlementResult(
            EXACT_REPLAY, play_id, settlement_result=stored.get("settlement_result"),
            mock_pnl=stored.get("mock_pnl"), settlement_label=stored.get("mset_label"),
            settled_at=stored_settled_at)
    return ManualSettlementResult(
        CHANGED_RESULT, play_id, settlement_result=stored.get("settlement_result"),
        mock_pnl=stored.get("mock_pnl"), settlement_label=stored.get("mset_label"),
        settled_at=stored_settled_at,
        divergence={"stored_identity": stored_payload, "supplied_identity": new_payload})


def _disposition(canonical: dict, selected_side: str, odds: int, stake: Decimal):
    """Return (outcome, settlement_result, mock_pnl_str, play_status) or a no-write sentinel outcome.

    Returns (outcome, None, None, None) for DEFERRED / REJECTED_TIE (no write).
    """
    status = canonical["game_status"]
    if status in ("postponed", "suspended"):
        return (DEFERRED, None, None, None)
    if status == "cancelled":
        return (VOIDED, "void", _decimal_str(Decimal(0)), "voided")
    if status == "final":
        home, away = canonical["home_score"], canonical["away_score"]
        if home == away:
            return (REJECTED_TIE, None, None, None)          # ML has no tie → reject, no-write
        winner = "home" if home > away else "away"
        if selected_side == winner:
            return (SETTLED_WIN, "win", _decimal_str(american_profit(odds, stake)), "settled")
        return (SETTLED_LOSS, "loss", _decimal_str(-stake), "settled")
    raise ManualSettlementValidationError(f"unhandled game_status {status!r}")


def settle_manual_play(conn, *, play_id: str, result_record: dict, settled_at: datetime,
                       env: dict | None = None) -> ManualSettlementResult:
    """Settle one MANUAL paper play against a validated fixture result. See module docstring."""
    # (1) Kill switch FIRST.
    if not is_autonomous_run_enabled(env):
        raise KillSwitchHaltError("kill switch inactive: manual settlement not performed")

    # (2) Input validation + fresh canonical copy (caller input never mutated).
    if getattr(conn, "autocommit", False):
        raise InvalidConnectionStateError("connection must have autocommit disabled")
    if not _is_tz_aware(settled_at):
        raise ManualSettlementValidationError("settled_at must be timezone-aware")
    canonical = canonical_result_copy(result_record)

    try:
        # (3) Bind by explicit play_id (unambiguous), verify origin + membership + external-game binding.
        prow = _fetch_one(conn, _SQL_PLAY, (play_id,))
        if prow is None:
            raise ManualSettlementBindingError(f"play {play_id} not found")
        play = {
            "play_id": play_id, "game_run_id": prow[0], "slate_run_id": prow[1], "market": prow[2],
            "selected_side": prow[3], "origin": prow[4], "odds_at_nomination": prow[5],
            "stake_units": prow[6], "settlement_result": prow[7], "mock_pnl": prow[8],
            "play_status": prow[9],
        }
        if play["origin"] != ORIGIN_MANUAL:
            raise ManualSettlementBindingError(f"play {play_id} origin {play['origin']!r} is not MANUAL")
        # Unambiguous binding: exactly one game in the play's slate matches the fixture external_game_id,
        # and it must be the play's game. Zero/multiple → reject, no writes.
        matches = _fetch_all(conn, _SQL_GAME_MATCHES,
                             (play["slate_run_id"], str(canonical["external_game_id"])))
        if len(matches) != 1:
            raise ManualSettlementBindingError(
                f"external_game_id {canonical['external_game_id']!r} matched {len(matches)} games in "
                f"slate {play['slate_run_id']!r}; require exactly one")
        if matches[0][0] != play["game_run_id"]:
            raise ManualSettlementBindingError(
                f"matched game {matches[0][0]!r} != play game {play['game_run_id']!r}")

        # (4) Provenance (validator already enforces exact source/data_origin; assert defensively).
        if canonical["source"] != FIXTURE_SOURCE or canonical["data_origin"] != CONTEXT_TEST_FIXTURE:
            raise ManualSettlementValidationError("result provenance is not TEST_FIXTURE/results_fixture")

        identity = build_identity(play, canonical)
        new_payload = canonical_identity_payload(identity)

        # (5) Already-settled → reconcile from the authoritative committed event (fail-closed).
        if play["settlement_result"] is not None:
            return _reconcile(conn, play_id, play, str(canonical["external_game_id"]),
                              new_payload, identity)

        # (6) Disposition.
        outcome, sr, pnl, pstatus = _disposition(
            canonical, play["selected_side"], int(play["odds_at_nomination"]), Decimal(play["stake_units"]))
        if outcome in (DEFERRED, REJECTED_TIE):
            return ManualSettlementResult(outcome, play_id)   # no write, no event

        # (7) Atomic settle: conditional UPDATE (concurrency guard) + exactly one event, commit once.
        payload_str = canonical_identity_payload(identity)     # recompute seam (pre-UPDATE)
        label = mset_label(play_id, payload_str)
        cur = conn.cursor()
        try:
            cur.execute(_SQL_UPDATE, (sr, pnl, settled_at, pstatus, play_id))
            affected = cur.rowcount
        finally:
            cur.close()
        if affected == 0:
            # conditional-update loser: another connection settled first. Re-read the WINNER's committed
            # projection (never substitute the loser's outcome/P&L) and reconcile it with the winner's
            # committed authoritative event.
            wrow = _fetch_one(conn, _SQL_PLAY, (play_id,))
            if wrow is None:
                raise ManualSettlementAuditError(f"play {play_id} disappeared during contention")
            winner = {
                "play_id": play_id, "game_run_id": wrow[0], "slate_run_id": wrow[1], "market": wrow[2],
                "selected_side": wrow[3], "origin": wrow[4], "odds_at_nomination": wrow[5],
                "stake_units": wrow[6], "settlement_result": wrow[7], "mock_pnl": wrow[8],
                "play_status": wrow[9],
            }
            return _reconcile(conn, play_id, winner, str(canonical["external_game_id"]),
                              payload_str, identity)
        record_event(
            conn, SETTLEMENT_EVENT, play["slate_run_id"], settled_at,
            game_run_id=play["game_run_id"], play_id=play_id,
            payload={
                "track": "manual", "real_performance": False,
                "origin": ORIGIN_MANUAL, "data_origin": CONTEXT_TEST_FIXTURE,
                "settlement_result": sr, "mock_pnl": pnl,
                "settled_at": settled_at.isoformat(),
                "result_observed_at": canonical["result_observed_at"],
                "identity_payload": payload_str, "mset_label": label,
                "clv_unavailable_reason": CLV_UNAVAILABLE_REASON,
            },
        )
        conn.commit()
        return ManualSettlementResult(outcome, play_id, settlement_result=sr, mock_pnl=pnl,
                                      settlement_label=label, settled_at=settled_at)
    except Exception:
        conn.rollback()
        raise
