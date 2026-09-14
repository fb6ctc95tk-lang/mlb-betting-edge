"""Oracle — Market-Odds Observation recording (PM-1183 / PM-1185 / PM-1187, implemented under PM-1189).

Records durable, append-only, play-independent market-odds observations into
oracle_market_odds_observations. This module asserts NO Oracle Edge, performs NO
settlement, computes NO CLV, and touches NO play. Scope of this increment:
TEST_FIXTURE observations only (source='market_odds_fixture', data_origin='TEST_FIXTURE');
the reserved AUTHENTICATED_HISTORICAL / LIVE_PROVIDER classes are inert.

Identity is the eight-field coordinate:
    (game_run_id, sportsbook, market, selected_side, price_format, observed_at, source, data_origin)

Write model (per coordinate, under a transaction-scoped advisory lock):
  * ROOT (supersedes_observation_id is None):
      - identical root (coordinate + price) already present  -> ROOT_REPLAY (no write)
      - otherwise                                            -> ROOT_RECORDED (may coexist as an
                                                                independent root when price differs)
  * CORRECTION (supersedes_observation_id set): classified in this order —
      1. predecessor missing            -> MalformedLineageError   (fail closed)
      2. coordinate mismatch            -> CrossLineageError       (fail closed)
      3. identical child already present -> CORRECTION_REPLAY       (no write; BEFORE stale-head)
      4. differing competing child      -> CorrectionConflictError (fail closed; covers stale head)
      5. head price == incoming price   -> CORRECTION_NOOP          (no write)
      6. otherwise                      -> CORRECTION_RECORDED

A winner is NEVER chosen by greatest observation_id. ingested_at is FORCED by the
database trigger to clock_timestamp(); this module never supplies it.

TRANSACTION OWNERSHIP (PM-1191): the caller owns the connection and transaction
(autocommit disabled). This module NEVER commits, rolls back, or closes the caller's
transaction — on success, replay, no-op, or failure. It uses only an INTERNAL SAVEPOINT
for uniqueness/insert recovery and rolls back solely to that savepoint, leaving prior
caller work intact and the transaction fully caller-controllable. Final commit/rollback
is exclusively the caller's. The per-coordinate advisory lock is transaction-scoped and
is released only when the caller ends the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.oracle.identifier_manager import (
    InvalidConnectionStateError,
    _require_manual_transaction,
    is_valid_game_run_id,
)
from backend.oracle.kill_switch import is_autonomous_run_enabled

# --- Frozen provenance / vocabulary (this increment) -------------------------
FIXTURE_SOURCE = "market_odds_fixture"
DATA_ORIGIN_TEST_FIXTURE = "TEST_FIXTURE"
_RESERVED_INERT = frozenset({"AUTHENTICATED_HISTORICAL", "LIVE_PROVIDER"})

_MARKETS = frozenset({"ML"})
_SIDES = frozenset({"home", "away"})
_PRICE_FORMATS = frozenset({"american"})

# --- Caller-visible outcomes -------------------------------------------------
ROOT_RECORDED = "ROOT_RECORDED"
ROOT_REPLAY = "ROOT_REPLAY"
CORRECTION_RECORDED = "CORRECTION_RECORDED"
CORRECTION_REPLAY = "CORRECTION_REPLAY"
CORRECTION_NOOP = "CORRECTION_NOOP"

# --- Coordinate read status --------------------------------------------------
COORD_EMPTY = "EMPTY"
COORD_RESOLVED = "RESOLVED"
COORD_CONFLICT = "CONFLICT"

# --- Advisory lock namespace (distinct from 1001 slate / 1002 play) ----------
_LOCK_NS_MOO = 1003

_PG_UNIQUE_VIOLATION = "23505"


class OddsObservationError(Exception):
    """Base class for market-odds observation errors."""


class OddsObservationValidationError(OddsObservationError):
    """Invalid input (vocabulary, domain, provenance, identity, or timestamp)."""


class KillSwitchHaltError(OddsObservationError):
    """Kill switch inactive; nothing is read or written."""


class CorrectionConflictError(OddsObservationError):
    """A differing competing child (or stale-head supersession) was refused."""


class MalformedLineageError(OddsObservationError):
    """The referenced predecessor does not exist."""


class CrossLineageError(OddsObservationError):
    """A correction's coordinate does not match its predecessor's coordinate."""


@dataclass(frozen=True)
class ObservationResult:
    outcome: str
    observation_id: int
    supersedes_observation_id: int | None = None


@dataclass(frozen=True)
class CoordinateRead:
    status: str
    heads: tuple[tuple[int, int], ...]  # ((observation_id, price), ...) across independent lineages


# --- Pure validators / normalizers -------------------------------------------

def normalize_sportsbook(value: object) -> str:
    if not isinstance(value, str):
        raise OddsObservationValidationError(
            f"sportsbook must be str, got {type(value).__name__!r}"
        )
    token = value.strip().upper()
    if not token or any(c not in _SPORTSBOOK_CHARS for c in token):
        raise OddsObservationValidationError(
            f"sportsbook must match ^[A-Z0-9_]+$, got {value!r}"
        )
    return token


_SPORTSBOOK_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def normalize_market(value: object) -> str:
    if not isinstance(value, str):
        raise OddsObservationValidationError(f"market must be str, got {type(value).__name__!r}")
    token = value.strip().upper()
    if token not in _MARKETS:
        raise OddsObservationValidationError(
            f"unsupported market {value!r} (allowed: {sorted(_MARKETS)})"
        )
    return token


def normalize_side(value: object) -> str:
    if not isinstance(value, str):
        raise OddsObservationValidationError(
            f"selected_side must be str, got {type(value).__name__!r}"
        )
    token = value.strip().lower()
    if token not in _SIDES:
        raise OddsObservationValidationError(
            f"unsupported selected_side {value!r} (allowed: {sorted(_SIDES)})"
        )
    return token


def normalize_price_format(value: object) -> str:
    if not isinstance(value, str):
        raise OddsObservationValidationError(
            f"price_format must be str, got {type(value).__name__!r}"
        )
    token = value.strip().lower()
    if token not in _PRICE_FORMATS:
        raise OddsObservationValidationError(
            f"unsupported price_format {value!r} (allowed: {sorted(_PRICE_FORMATS)})"
        )
    return token


def is_valid_american_odds(value: object) -> bool:
    # bool is a subclass of int; type(value) is int rejects True/False by design.
    return type(value) is int and (value >= 100 or value <= -100)


def _is_tz_aware(dt: object) -> bool:
    return (
        isinstance(dt, datetime)
        and dt.tzinfo is not None
        and dt.tzinfo.utcoffset(dt) is not None
    )


def _validate_source_and_origin(source: object, data_origin: object) -> tuple[str, str]:
    if data_origin in _RESERVED_INERT:
        raise OddsObservationValidationError(
            f"data_origin {data_origin!r} is reserved and inert in this increment; "
            f"only {DATA_ORIGIN_TEST_FIXTURE!r} is admitted"
        )
    if data_origin != DATA_ORIGIN_TEST_FIXTURE:
        raise OddsObservationValidationError(
            f"data_origin must be {DATA_ORIGIN_TEST_FIXTURE!r}, got {data_origin!r}"
        )
    if source != FIXTURE_SOURCE:
        raise OddsObservationValidationError(
            f"source must be {FIXTURE_SOURCE!r}, got {source!r}"
        )
    return source, data_origin


def _coordinate_key(
    game_run_id: str, sportsbook: str, market: str, selected_side: str,
    price_format: str, observed_at: datetime, source: str, data_origin: str,
) -> str:
    return "\x1f".join((
        game_run_id, sportsbook, market, selected_side, price_format,
        observed_at.isoformat(), source, data_origin,
    ))


# --- SQL (recognizable clauses) ----------------------------------------------

_SQL_FIND_ROOT_EXACT = (
    "SELECT observation_id FROM oracle_market_odds_observations "
    "WHERE supersedes_observation_id IS NULL "
    "AND game_run_id = %s AND sportsbook = %s AND market = %s AND selected_side = %s "
    "AND price_format = %s AND observed_at = %s AND source = %s AND data_origin = %s "
    "AND price = %s"
)
_SQL_LOAD_PREDECESSOR = (
    "SELECT observation_id, game_run_id, sportsbook, market, selected_side, "
    "price_format, observed_at, source, data_origin, price "
    "FROM oracle_market_odds_observations WHERE observation_id = %s"
)
_SQL_FIND_CHILD = (
    "SELECT observation_id, price FROM oracle_market_odds_observations "
    "WHERE supersedes_observation_id = %s"
)
_SQL_INSERT = (
    "INSERT INTO oracle_market_odds_observations "
    "(game_run_id, sportsbook, market, selected_side, price_format, price, source, "
    "data_origin, observed_at, supersedes_observation_id, correction_reason) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "RETURNING observation_id"
)
_SQL_COORDINATE_HEADS = (
    "SELECT o.observation_id, o.price FROM oracle_market_odds_observations o "
    "WHERE o.game_run_id = %s AND o.sportsbook = %s AND o.market = %s "
    "AND o.selected_side = %s AND o.price_format = %s AND o.observed_at = %s "
    "AND o.source = %s AND o.data_origin = %s "
    "AND NOT EXISTS (SELECT 1 FROM oracle_market_odds_observations c "
    "WHERE c.supersedes_observation_id = o.observation_id) "
    "ORDER BY o.observation_id"
)


def _acquire_coordinate_lock(conn, coordinate_key: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
            (_LOCK_NS_MOO, coordinate_key),
        )
    finally:
        cur.close()


def _fetchone(conn, sql: str, params: tuple):
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()


def _insert(conn, params: tuple) -> int:
    cur = conn.cursor()
    try:
        cur.execute(_SQL_INSERT, params)
        return cur.fetchone()[0]
    finally:
        cur.close()


def _savepoint(conn, stmt: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute(stmt)
    finally:
        cur.close()


def record_market_odds_observation(
    conn: object,
    *,
    game_run_id: str,
    sportsbook: str,
    market: str,
    selected_side: str,
    price_format: str,
    price: int,
    source: str,
    data_origin: str,
    observed_at: datetime,
    supersedes_observation_id: int | None = None,
    correction_reason: str | None = None,
    env: dict | None = None,
) -> ObservationResult:
    """Record one market-odds observation (root or correction). See module docstring.

    Never supplies ingested_at (the database trigger forces clock_timestamp()).
    """
    # (1) Kill-switch FIRST — before any read, write, or lock.
    if not is_autonomous_run_enabled(env):
        raise KillSwitchHaltError("kill switch inactive: observation not recorded")

    # (2) Connection state.
    _require_manual_transaction(conn)

    # (3) Input validation / normalization.
    if not is_valid_game_run_id(game_run_id):
        raise OddsObservationValidationError(
            f"game_run_id is not a valid Game Analysis Run ID: {game_run_id!r}"
        )
    book_n = normalize_sportsbook(sportsbook)
    market_n = normalize_market(market)
    side_n = normalize_side(selected_side)
    fmt_n = normalize_price_format(price_format)
    if not is_valid_american_odds(price):
        raise OddsObservationValidationError(
            f"price must be a non-boolean int with |price| >= 100, got {price!r}"
        )
    source_n, origin_n = _validate_source_and_origin(source, data_origin)
    if not _is_tz_aware(observed_at):
        raise OddsObservationValidationError("observed_at must be timezone-aware")
    if supersedes_observation_id is not None and (
        type(supersedes_observation_id) is not int or supersedes_observation_id <= 0
    ):
        raise OddsObservationValidationError(
            f"supersedes_observation_id must be a positive int or None, "
            f"got {supersedes_observation_id!r}"
        )
    if correction_reason is not None and not isinstance(correction_reason, str):
        raise OddsObservationValidationError("correction_reason must be str or None")

    coordinate = (game_run_id, book_n, market_n, side_n, fmt_n, observed_at, source_n, origin_n)
    insert_params = (
        game_run_id, book_n, market_n, side_n, fmt_n, price, source_n, origin_n,
        observed_at, supersedes_observation_id, correction_reason,
    )

    # (4) Per-coordinate advisory lock: serialize writers to this coordinate. Transaction
    # scoped — released only when the CALLER commits/rolls back. This module never commits,
    # rolls back, or closes the caller's transaction; recovery is savepoint-scoped only.
    _acquire_coordinate_lock(conn, _coordinate_key(*coordinate))

    if supersedes_observation_id is None:
        return _record_root(conn, coordinate, price, insert_params)
    return _record_correction(
        conn, coordinate, price, supersedes_observation_id, insert_params
    )


def _record_root(conn, coordinate, price, insert_params) -> ObservationResult:
    existing = _fetchone(conn, _SQL_FIND_ROOT_EXACT, (*coordinate, price))
    if existing is not None:
        return ObservationResult(ROOT_REPLAY, existing[0])

    _savepoint(conn, "SAVEPOINT sp_moo")
    try:
        new_id = _insert(conn, insert_params)
    except Exception as exc:  # concurrency backstop: exact-root uniqueness (23505)
        # Roll back ONLY to the savepoint first: un-abort the caller's transaction so it
        # stays usable whether we reconcile (unique) or re-raise (any other error).
        _savepoint(conn, "ROLLBACK TO SAVEPOINT sp_moo")
        if getattr(exc, "pgcode", None) != _PG_UNIQUE_VIOLATION:
            raise
        now = _fetchone(conn, _SQL_FIND_ROOT_EXACT, (*coordinate, price))
        if now is None:
            raise OddsObservationError("root unique conflict with no committed row")
        return ObservationResult(ROOT_REPLAY, now[0])
    _savepoint(conn, "RELEASE SAVEPOINT sp_moo")
    return ObservationResult(ROOT_RECORDED, new_id)


def _record_correction(conn, coordinate, price, predecessor_id, insert_params) -> ObservationResult:
    predecessor = _fetchone(conn, _SQL_LOAD_PREDECESSOR, (predecessor_id,))
    if predecessor is None:
        raise MalformedLineageError(f"predecessor {predecessor_id} not found")

    # predecessor columns: 0=id,1..8=coordinate fields (game..data_origin),9=price
    pred_coordinate = (
        predecessor[1], predecessor[2], predecessor[3], predecessor[4],
        predecessor[5], predecessor[6], predecessor[7], predecessor[8],
    )
    if pred_coordinate != coordinate:
        raise CrossLineageError(
            f"correction coordinate does not match predecessor {predecessor_id}"
        )

    child = _fetchone(conn, _SQL_FIND_CHILD, (predecessor_id,))
    if child is not None:
        # Identical-child replay classified BEFORE stale-head/branch handling.
        if int(child[1]) == price:
            return ObservationResult(CORRECTION_REPLAY, child[0], predecessor_id)
        raise CorrectionConflictError(
            f"differing competing child for predecessor {predecessor_id}"
        )

    # Predecessor is the current head. A price-preserving correction is a no-op.
    if int(predecessor[9]) == price:
        return ObservationResult(CORRECTION_NOOP, predecessor_id, predecessor_id)

    _savepoint(conn, "SAVEPOINT sp_moo")
    try:
        new_id = _insert(conn, insert_params)
    except Exception as exc:  # concurrency backstop: one-child uniqueness (23505)
        # Roll back ONLY to the savepoint first: un-abort the caller's transaction so it
        # stays usable whether we reconcile (unique) or re-raise (any other error).
        _savepoint(conn, "ROLLBACK TO SAVEPOINT sp_moo")
        if getattr(exc, "pgcode", None) != _PG_UNIQUE_VIOLATION:
            raise
        now = _fetchone(conn, _SQL_FIND_CHILD, (predecessor_id,))
        if now is None:
            raise OddsObservationError("child unique conflict with no committed row")
        if int(now[1]) == price:
            return ObservationResult(CORRECTION_REPLAY, now[0], predecessor_id)
        raise CorrectionConflictError(
            f"differing competing child for predecessor {predecessor_id}"
        )
    _savepoint(conn, "RELEASE SAVEPOINT sp_moo")
    return ObservationResult(CORRECTION_RECORDED, new_id, predecessor_id)


def read_coordinate(
    conn: object,
    *,
    game_run_id: str,
    sportsbook: str,
    market: str,
    selected_side: str,
    price_format: str,
    observed_at: datetime,
    source: str,
    data_origin: str,
) -> CoordinateRead:
    """Return the non-superseded head of each independent lineage at a coordinate.

    Status is EMPTY (no rows), RESOLVED (one head), or CONFLICT (>1 head — retained
    independent roots with differing prices). A winner is never chosen by greatest ID.
    """
    book_n = normalize_sportsbook(sportsbook)
    market_n = normalize_market(market)
    side_n = normalize_side(selected_side)
    fmt_n = normalize_price_format(price_format)
    source_n, origin_n = _validate_source_and_origin(source, data_origin)
    rows = _fetchall(
        conn, _SQL_COORDINATE_HEADS,
        (game_run_id, book_n, market_n, side_n, fmt_n, observed_at, source_n, origin_n),
    )
    heads = tuple((int(r[0]), int(r[1])) for r in rows)
    if not heads:
        status = COORD_EMPTY
    elif len(heads) == 1:
        status = COORD_RESOLVED
    else:
        status = COORD_CONFLICT
    return CoordinateRead(status, heads)


def _fetchall(conn, sql: str, params: tuple):
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
