"""Oracle — MANUAL paper-play recording (PM-1131 / PM-1133 / PM-1135 / PM-1137).

Records a human-selected paper bet as one `oracle_plays` row with authoritative
`origin='MANUAL'` provenance and a `TEST_FIXTURE` game context. It asserts NO Oracle
Edge, uses NO live data, performs NO settlement, and captures only `odds_at_nomination`
(the closing line / CLV are a separate, later, independent observation).

Ordering (PM-1137 K3): kill-switch FIRST → input validation → persisted membership →
TEST_FIXTURE validation → replay classification → atomic write. Replay is existence-first
with a partial-unique-index backstop; EXACT_REPLAY and CHANGED_INPUT are BOTH no-write and
preserve the first persisted `nomination_timestamp`.

The Play-ID capability is obtained from the sanctioned
`identifier_manager.create_manual_play_id_capability()` (an anti-accident guard, not a
security boundary). The caller owns the connection and transaction (autocommit=False).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from backend.oracle.event_store import record_event
from backend.oracle.identifier_manager import (
    InvalidConnectionStateError,
    create_manual_play_id_capability,
    generate_play_id,
)
from backend.oracle.kill_switch import is_autonomous_run_enabled

# --- Provenance sentinels (authoritative) ------------------------------------
ORIGIN_MANUAL = "MANUAL"
CONTEXT_TEST_FIXTURE = "TEST_FIXTURE"

# --- Accepted vocabularies (Phase 1: ML only) --------------------------------
_MARKETS = frozenset({"ML"})
_SIDES = frozenset({"home", "away"})

# --- Caller-visible outcomes -------------------------------------------------
RECORDED = "RECORDED"
EXACT_REPLAY = "EXACT_REPLAY"
CHANGED_INPUT = "CHANGED_INPUT"

_PG_UNIQUE_VIOLATION = "23505"


class ManualPlayError(Exception):
    """Base class for manual paper-play recording errors."""


class ManualPlayValidationError(ManualPlayError):
    """Raised on invalid inputs (market/side/odds/stake/context/timestamp)."""


class ManualPlayMembershipError(ManualPlayError):
    """Raised when the game does not exist or is not a member of the slate."""


class KillSwitchHaltError(ManualPlayError):
    """Raised when the kill switch is inactive; no row or event is written."""


@dataclass(frozen=True)
class ManualPlayResult:
    outcome: str
    play_id: str
    candidate_id: str
    nomination_timestamp: datetime
    divergence: dict = field(default_factory=dict)


# --- Pure validators ---------------------------------------------------------

def normalize_market(market: object) -> str:
    if not isinstance(market, str):
        raise ManualPlayValidationError(f"market must be str, got {type(market).__name__!r}")
    value = market.strip().upper()
    if value not in _MARKETS:
        raise ManualPlayValidationError(f"unsupported market {market!r} (allowed: {sorted(_MARKETS)})")
    return value


def normalize_side(side: object) -> str:
    if not isinstance(side, str):
        raise ManualPlayValidationError(f"selected_side must be str, got {type(side).__name__!r}")
    value = side.strip().lower()
    if value not in _SIDES:
        raise ManualPlayValidationError(f"unsupported selected_side {side!r} (allowed: {sorted(_SIDES)})")
    return value


def is_valid_american_odds(value: object) -> bool:
    # bool is a subclass of int; type(value) is int rejects True/False by design.
    return type(value) is int and (value >= 100 or value <= -100)


def normalize_stake(stake: object) -> Decimal:
    if isinstance(stake, bool) or not isinstance(stake, (int, Decimal)):
        raise ManualPlayValidationError(f"stake_units must be a non-boolean int or Decimal, got {stake!r}")
    value = Decimal(stake)
    if value <= 0:
        raise ManualPlayValidationError(f"stake_units must be > 0, got {stake!r}")
    return value


def _is_tz_aware(dt: object) -> bool:
    return isinstance(dt, datetime) and dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None


def build_manual_candidate_id(game_run_id: str, market: str, selected_side: str) -> str:
    """Deterministic manual candidate label (distinct from analytical CAND-ORACLE-…-ML)."""
    return f"MANUAL-CAND-{game_run_id}-{market}-{selected_side}"


# --- SQL (recognizable clauses) ----------------------------------------------
_SQL_MEMBERSHIP = (
    "SELECT slate_run_id, game_status FROM oracle_game_analyses WHERE game_run_id = %s"
)
_SQL_REPLAY = (
    "SELECT play_id, odds_at_nomination, stake_units, nomination_timestamp "
    "FROM oracle_plays "
    "WHERE origin = 'MANUAL' AND game_run_id = %s AND market = %s AND selected_side = %s"
)
_SQL_INSERT = (
    "INSERT INTO oracle_plays "
    "(play_id, candidate_id, slate_run_id, game_run_id, market, selected_side, "
    "odds_at_nomination, stake_units, nomination_timestamp, play_status, origin) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


def _fetch_membership(conn: object, game_run_id: str):
    cur = conn.cursor()
    try:
        cur.execute(_SQL_MEMBERSHIP, (game_run_id,))
        return cur.fetchone()
    finally:
        cur.close()


def _fetch_manual_play(conn: object, game_run_id: str, market: str, selected_side: str):
    cur = conn.cursor()
    try:
        cur.execute(_SQL_REPLAY, (game_run_id, market, selected_side))
        return cur.fetchone()
    finally:
        cur.close()


def _classify_replay(existing, odds: int, stake: Decimal, candidate_id: str) -> ManualPlayResult:
    # existing = (play_id, odds_at_nomination, stake_units, nomination_timestamp)
    stored_play_id, stored_odds, stored_stake, stored_ts = existing
    same = int(stored_odds) == odds and Decimal(stored_stake) == stake
    if same:
        return ManualPlayResult(EXACT_REPLAY, stored_play_id, candidate_id, stored_ts)
    return ManualPlayResult(
        CHANGED_INPUT, stored_play_id, candidate_id, stored_ts,
        divergence={
            "stored_odds_at_nomination": int(stored_odds),
            "supplied_odds_at_nomination": odds,
            "stored_stake_units": str(Decimal(stored_stake)),
            "supplied_stake_units": str(stake),
        },
    )


def record_manual_play(
    conn: object,
    *,
    slate_run_id: str,
    game_run_id: str,
    market: str,
    selected_side: str,
    odds_at_nomination: int,
    nomination_timestamp: datetime,
    current_date_et: date,
    data_origin: str,
    stake_units: object = Decimal("1.0"),
    env: dict | None = None,
) -> ManualPlayResult:
    """Record one MANUAL paper play (or reconcile a replay). See module docstring.

    Returns a ManualPlayResult; writes exactly one row + one `play_id_assigned` event
    only on RECORDED, in a single caller-owned transaction (commit-once).
    """
    # (1) Kill-switch FIRST — before any read, write, or Play-ID generation.
    if not is_autonomous_run_enabled(env):
        raise KillSwitchHaltError("kill switch inactive: manual play not recorded")

    # (2) Input validation.
    if getattr(conn, "autocommit", False):
        raise InvalidConnectionStateError("connection must have autocommit disabled")
    market_n = normalize_market(market)
    side_n = normalize_side(selected_side)
    if not is_valid_american_odds(odds_at_nomination):
        raise ManualPlayValidationError(
            f"odds_at_nomination must be a non-boolean int with |odds| >= 100, "
            f"got {odds_at_nomination!r}"
        )
    stake = normalize_stake(stake_units)
    if not _is_tz_aware(nomination_timestamp):
        raise ManualPlayValidationError("nomination_timestamp must be timezone-aware")
    if not isinstance(current_date_et, date):
        raise ManualPlayValidationError("current_date_et must be a datetime.date")

    try:
        # (3) Persisted membership — actual state, not FK assumption.
        membership = _fetch_membership(conn, game_run_id)
        if membership is None or membership[0] != slate_run_id:
            raise ManualPlayMembershipError(
                f"game_run_id {game_run_id!r} is not a member of slate {slate_run_id!r}"
            )

        # (4) TEST_FIXTURE context validation — the only authorized context now.
        if data_origin != CONTEXT_TEST_FIXTURE:
            raise ManualPlayValidationError(
                f"data_origin must be {CONTEXT_TEST_FIXTURE!r}, got {data_origin!r}"
            )

        candidate_id = build_manual_candidate_id(game_run_id, market_n, side_n)

        # (5) Replay classification — existence-first (no-write EXACT_REPLAY / CHANGED_INPUT).
        existing = _fetch_manual_play(conn, game_run_id, market_n, side_n)
        if existing is not None:
            return _classify_replay(existing, odds_at_nomination, stake, candidate_id)

        # (6) RECORDED — atomic row + event in one transaction.
        capability = create_manual_play_id_capability()
        play_id = generate_play_id(current_date_et, conn, capability)

        cur = conn.cursor()
        try:
            cur.execute("SAVEPOINT sp_manual_play")
        finally:
            cur.close()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    _SQL_INSERT,
                    (play_id, candidate_id, slate_run_id, game_run_id, market_n, side_n,
                     odds_at_nomination, stake, nomination_timestamp, "nominated", ORIGIN_MANUAL),
                )
            finally:
                cur.close()
        except Exception as exc:  # concurrency backstop: reconcile a verified committed row
            if getattr(exc, "pgcode", None) != _PG_UNIQUE_VIOLATION:
                raise
            cur = conn.cursor()
            try:
                cur.execute("ROLLBACK TO SAVEPOINT sp_manual_play")
            finally:
                cur.close()
            existing_now = _fetch_manual_play(conn, game_run_id, market_n, side_n)
            if existing_now is None:
                raise ManualPlayError(
                    f"unique conflict for {candidate_id} with no committed row"
                )
            return _classify_replay(existing_now, odds_at_nomination, stake, candidate_id)
        else:
            cur = conn.cursor()
            try:
                cur.execute("RELEASE SAVEPOINT sp_manual_play")
            finally:
                cur.close()

        record_event(
            conn, "play_id_assigned", slate_run_id, nomination_timestamp,
            game_run_id=game_run_id, play_id=play_id,
            payload={
                "origin": ORIGIN_MANUAL,
                "data_origin": CONTEXT_TEST_FIXTURE,
                "market": market_n,
                "selected_side": side_n,
                "odds_at_nomination": odds_at_nomination,
                "stake_units": str(stake),
                "candidate_id": candidate_id,
            },
        )
        conn.commit()
        return ManualPlayResult(RECORDED, play_id, candidate_id, nomination_timestamp)
    except Exception:
        conn.rollback()
        raise
