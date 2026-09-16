"""Oracle — Closing-Line Selector (pure read-side).

Finalized by PM-1221 (policy) / PM-1223 (technical contract & scope) / PM-1225
(historical-lineage correction) / PM-1227 (integrity-query completion) /
PM-1229 (cycle-closure boundary correction), implemented under PM-1231.

Selects a per-side American moneyline "closing line" for a single fixture sportsbook
(FanDuel Ontario) from the append-only market-odds observation store, relative to a
caller-supplied SCHEDULED start. It asserts NO Oracle Edge, computes NO CLV, performs NO
settlement, touches NO play, and makes NO durable/authenticity claim. Scope: TEST_FIXTURE
observations only.

Transaction ownership: the CALLER supplies the connection (autocommit disabled) and owns
the transaction and connection lifecycle. This module manages cursors only and issues ONE
read-only query statement. It performs NO commit, rollback, connection close, SAVEPOINT,
advisory lock, write, or hidden/implicit connection creation.

Historical selection is a NEW read across many observed_at values; it does NOT reuse the
current-head reader read_coordinate() (single-instant, no as_of). The complete corrected
single-statement query (PM-1227 + PM-1229) is embedded below unchanged in semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.oracle.identifier_manager import (
    InvalidConnectionStateError,
    is_valid_game_run_id,
)

# --- Frozen fixture identity / vocabulary (PM-1221/1223) ---------------------
SPORTSBOOK_FANDUEL_ON = "FANDUEL_ON"      # FanDuel, Ontario jurisdiction; no conflation, no provider assumption
MARKET_ML = "ML"
PRICE_FORMAT_AMERICAN = "american"
FIXTURE_SOURCE = "market_odds_fixture"
DATA_ORIGIN_TEST_FIXTURE = "TEST_FIXTURE"
_SIDES = frozenset({"home", "away"})

POLICY_VERSION = "PM-1223-v1"             # policy label defined by the controlling records
MAX_DEPTH = 256                           # fixed technical bound (PM-1227/1229); node-counting convention

# --- Outcomes / classes / reason tokens --------------------------------------
STATUS_SELECTED = "SELECTED"
STATUS_UNAVAILABLE = "UNAVAILABLE"

AS_OF_CONTEMPORANEOUS = "contemporaneous"
AS_OF_RETROSPECTIVE = "retrospective"

REASON_NO_ELIGIBLE = "no_eligible_observation"
REASON_NO_START = "no_authoritative_start"
REASON_POSTPONED = "postponed_no_start"
REASON_AS_OF_BEFORE_START = "as_of_before_start"
REASON_UNRESOLVED_CONFLICT = "unresolved_conflict"
REASON_INCOMPLETE_PROJECTION = "incomplete_historical_projection"
REASON_MALFORMED = "malformed_history"
REASON_TRAVERSAL_EXHAUSTED = "traversal_exhausted"

# Outcome tokens the query itself can emit (all others are decided before the query).
_QUERY_OUTCOMES = frozenset({
    STATUS_SELECTED, REASON_NO_ELIGIBLE, REASON_MALFORMED,
    REASON_TRAVERSAL_EXHAUSTED, REASON_INCOMPLETE_PROJECTION, REASON_UNRESOLVED_CONFLICT,
})


class ClosingLineError(Exception):
    """Base class for closing-line selector errors."""


class ClosingLineValidationError(ClosingLineError):
    """Structural/vocabulary/identity/timestamp input invalid (fail closed)."""


@dataclass(frozen=True)
class ClosingLineResult:
    status: str
    reason: str | None = None
    observation_id: int | None = None
    price: int | None = None
    observed_at: datetime | None = None
    sportsbook: str | None = None
    market: str | None = None
    selected_side: str | None = None
    authoritative_start: datetime | None = None
    start_version: str | None = None
    start_provenance: str | None = None
    start_is_verified_first_pitch: bool = False
    as_of: datetime | None = None
    as_of_class: str | None = None
    observation_to_start_age_seconds: int | None = None
    observation_to_start_age_iso: str | None = None
    provenance: str = "fixture"
    real_clv_eligible: bool = False
    policy_version: str = POLICY_VERSION


# --- Helpers -----------------------------------------------------------------

def _is_tz_aware(dt: object) -> bool:
    return (
        isinstance(dt, datetime)
        and dt.tzinfo is not None
        and dt.tzinfo.utcoffset(dt) is not None
    )


def _iso_seconds(seconds: int) -> str:
    return f"PT{seconds}S"


# --- Complete corrected single-statement query (PM-1227 §3 + PM-1229 §3) -----
# All-family integrity traversal; integrated branch/predecessor checks; per-row
# closing-edge cycle detection using that row's current path (boundary-safe);
# proven cycle precedes traversal_exhausted; incomplete distinct from malformed;
# visible-only price selection; no greatest-ID / arbitrary-row winner.
_SELECTION_SQL = """
WITH RECURSIVE
coord AS (
  SELECT observation_id, supersedes_observation_id, observed_at, ingested_at, price
  FROM oracle_market_odds_observations
  WHERE game_run_id = %(g)s AND sportsbook = %(book)s AND market = %(mkt)s
    AND selected_side = %(side)s AND price_format = %(fmt)s
    AND source = %(src)s AND data_origin = %(do)s
),
eligible AS (
  SELECT * FROM coord WHERE ingested_at <= %(as_of)s AND observed_at < %(start)s
),
latest AS (SELECT max(observed_at) AS t FROM eligible),
family AS (
  SELECT c.* FROM coord c JOIN latest ON latest.t IS NOT NULL AND c.observed_at = latest.t
),
visible AS (
  SELECT * FROM family WHERE ingested_at <= %(as_of)s
),
mism AS (
  SELECT f.observation_id FROM family f
  WHERE f.supersedes_observation_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM family p WHERE p.observation_id = f.supersedes_observation_id)
),
branch AS (
  SELECT supersedes_observation_id AS parent_id FROM family
  WHERE supersedes_observation_id IS NOT NULL
  GROUP BY supersedes_observation_id HAVING count(*) > 1
),
walk AS (
  SELECT f.observation_id AS start_id, f.observation_id AS node_id,
         f.supersedes_observation_id AS pred_id,
         1 AS depth, ARRAY[f.observation_id] AS path,
         (f.supersedes_observation_id IS NOT NULL
          AND f.supersedes_observation_id = ANY(ARRAY[f.observation_id])) AS closes_cycle
  FROM family f
  UNION ALL
  SELECT w.start_id, p.observation_id, p.supersedes_observation_id,
         w.depth + 1, w.path || p.observation_id,
         (p.supersedes_observation_id IS NOT NULL
          AND p.supersedes_observation_id = ANY(w.path || p.observation_id)) AS closes_cycle
  FROM walk w JOIN family p ON p.observation_id = w.pred_id
  WHERE w.pred_id IS NOT NULL AND NOT w.closes_cycle AND w.depth < %(maxdepth)s
),
wagg AS (
  SELECT start_id,
         bool_or(closes_cycle) AS has_cycle,
         bool_or(pred_id IS NOT NULL AND NOT closes_cycle AND depth >= %(maxdepth)s) AS exhausted
  FROM walk GROUP BY start_id
),
heads AS (
  SELECT v.* FROM visible v
  WHERE NOT EXISTS (SELECT 1 FROM visible c WHERE c.supersedes_observation_id = v.observation_id)
),
vwalk AS (
  SELECT h.observation_id AS head_id, h.observation_id AS node_id,
         h.supersedes_observation_id AS pred_id,
         1 AS depth, ARRAY[h.observation_id] AS path,
         (h.supersedes_observation_id IS NOT NULL
          AND h.supersedes_observation_id = ANY(ARRAY[h.observation_id])) AS closes_cycle
  FROM heads h
  UNION ALL
  SELECT vw.head_id, p.observation_id, p.supersedes_observation_id,
         vw.depth + 1, vw.path || p.observation_id,
         (p.supersedes_observation_id IS NOT NULL
          AND p.supersedes_observation_id = ANY(vw.path || p.observation_id)) AS closes_cycle
  FROM vwalk vw JOIN visible p ON p.observation_id = vw.pred_id
  WHERE vw.pred_id IS NOT NULL AND NOT vw.closes_cycle AND vw.depth < %(maxdepth)s
),
vagg AS (
  SELECT head_id, bool_or(pred_id IS NULL) AS reached_visible_root
  FROM vwalk GROUP BY head_id
),
head_root AS (
  SELECT head_id, node_id AS root_id FROM vwalk WHERE pred_id IS NULL
),
sel AS (
  SELECT observation_id, price, observed_at FROM heads
  WHERE (SELECT count(*) FROM heads) = 1
),
flags AS (
  SELECT
    (SELECT latest.t IS NOT NULL FROM latest)                             AS has_eligible,
    (SELECT EXISTS(SELECT 1 FROM mism))                                   AS any_mism,
    (SELECT EXISTS(SELECT 1 FROM branch))                                 AS any_branch,
    (SELECT COALESCE(bool_or(has_cycle), FALSE) FROM wagg)                AS any_cycle,
    (SELECT COALESCE(bool_or(exhausted),  FALSE) FROM wagg)               AS any_exhausted,
    (SELECT count(*) FROM heads)                                          AS n_heads,
    (SELECT COALESCE(bool_or(NOT reached_visible_root), FALSE) FROM vagg) AS any_incomplete,
    (SELECT count(DISTINCT root_id) FROM head_root)                       AS n_roots
)
SELECT
  CASE
    WHEN NOT has_eligible                                   THEN 'no_eligible_observation'
    WHEN any_mism OR any_branch OR any_cycle OR n_heads = 0 THEN 'malformed_history'
    WHEN any_exhausted                                     THEN 'traversal_exhausted'
    WHEN any_incomplete                                    THEN 'incomplete_historical_projection'
    WHEN n_roots >= 2                                      THEN 'unresolved_conflict'
    ELSE 'SELECTED'
  END                                    AS outcome,
  (SELECT observation_id FROM sel)       AS sel_observation_id,
  (SELECT price FROM sel)                AS sel_price,
  (SELECT observed_at FROM sel)          AS sel_observed_at
FROM flags;
"""


def select_closing_line(
    conn: object,
    *,
    game_run_id: str,
    selected_side: str,
    authoritative_start: datetime | None,
    start_version: str,
    start_provenance: str,
    postponed: bool = False,
    as_of: datetime | None = None,
    sportsbook: str = SPORTSBOOK_FANDUEL_ON,
    market: str = MARKET_ML,
    price_format: str = PRICE_FORMAT_AMERICAN,
    source: str = FIXTURE_SOURCE,
    data_origin: str = DATA_ORIGIN_TEST_FIXTURE,
) -> ClosingLineResult:
    """Select the closing line, or return a truthful Unavailable(reason). See module docstring.

    Never writes; issues one read-only query on the caller's connection.
    """
    # (1) Connection state — caller-owned transaction, autocommit disabled.
    if getattr(conn, "autocommit", False):
        raise InvalidConnectionStateError("connection must have autocommit disabled")

    # (2) Structural identity / vocabulary (fail closed).
    if not is_valid_game_run_id(game_run_id):
        raise ClosingLineValidationError(f"invalid game_run_id: {game_run_id!r}")
    side_n = selected_side.strip().lower() if isinstance(selected_side, str) else None
    if side_n not in _SIDES:
        raise ClosingLineValidationError(f"selected_side must be home|away, got {selected_side!r}")
    book_n = sportsbook.strip().upper() if isinstance(sportsbook, str) else None
    if book_n != SPORTSBOOK_FANDUEL_ON:
        raise ClosingLineValidationError(
            f"sportsbook must be {SPORTSBOOK_FANDUEL_ON!r} (no jurisdiction conflation), got {sportsbook!r}"
        )
    if not isinstance(market, str) or market.strip().upper() != MARKET_ML:
        raise ClosingLineValidationError(f"market must be {MARKET_ML!r}, got {market!r}")
    if not isinstance(price_format, str) or price_format.strip().lower() != PRICE_FORMAT_AMERICAN:
        raise ClosingLineValidationError(f"price_format must be {PRICE_FORMAT_AMERICAN!r}, got {price_format!r}")
    if source != FIXTURE_SOURCE:
        raise ClosingLineValidationError(f"source must be {FIXTURE_SOURCE!r}, got {source!r}")
    if data_origin != DATA_ORIGIN_TEST_FIXTURE:
        raise ClosingLineValidationError(f"data_origin must be {DATA_ORIGIN_TEST_FIXTURE!r}, got {data_origin!r}")
    if not isinstance(start_version, str) or not start_version.strip():
        raise ClosingLineValidationError("start_version must be a non-empty str")
    if not isinstance(start_provenance, str) or not start_provenance.strip():
        raise ClosingLineValidationError("start_provenance must be a non-empty str")

    # (3) Start designation.
    if postponed:
        return _unavailable(REASON_POSTPONED, side_n, authoritative_start, start_version, None, None)
    if authoritative_start is None:
        return _unavailable(REASON_NO_START, side_n, None, start_version, None, None)

    # (4) Start type.
    if not _is_tz_aware(authoritative_start):
        raise ClosingLineValidationError("authoritative_start must be timezone-aware")

    # (5) as_of resolution / classification.
    if as_of is None:
        as_of_value = authoritative_start
        as_of_class = AS_OF_CONTEMPORANEOUS
    else:
        if not _is_tz_aware(as_of):
            raise ClosingLineValidationError("as_of must be timezone-aware")
        if as_of < authoritative_start:
            return _unavailable(REASON_AS_OF_BEFORE_START, side_n, authoritative_start,
                                start_version, as_of, AS_OF_RETROSPECTIVE if as_of > authoritative_start else None)
        as_of_value = as_of
        as_of_class = AS_OF_CONTEMPORANEOUS if as_of == authoritative_start else AS_OF_RETROSPECTIVE

    # (6) Execute the single read-only query on the caller's connection.
    params = {
        "g": game_run_id, "book": SPORTSBOOK_FANDUEL_ON, "mkt": MARKET_ML,
        "side": side_n, "fmt": PRICE_FORMAT_AMERICAN, "src": FIXTURE_SOURCE,
        "do": DATA_ORIGIN_TEST_FIXTURE, "start": authoritative_start,
        "as_of": as_of_value, "maxdepth": MAX_DEPTH,
    }
    cur = conn.cursor()
    try:
        cur.execute(_SELECTION_SQL, params)
        outcome, sel_id, sel_price, sel_obs = cur.fetchone()
    finally:
        cur.close()

    if outcome == STATUS_SELECTED:
        age = int((authoritative_start - sel_obs).total_seconds())
        return ClosingLineResult(
            status=STATUS_SELECTED,
            observation_id=int(sel_id),
            price=int(sel_price),
            observed_at=sel_obs,
            sportsbook=SPORTSBOOK_FANDUEL_ON,
            market=MARKET_ML,
            selected_side=side_n,
            authoritative_start=authoritative_start,
            start_version=start_version,
            start_provenance=start_provenance,
            start_is_verified_first_pitch=False,
            as_of=as_of_value,
            as_of_class=as_of_class,
            observation_to_start_age_seconds=age,
            observation_to_start_age_iso=_iso_seconds(age),
        )

    # Any other outcome is a truthful Unavailable(reason) from the query.
    if outcome not in _QUERY_OUTCOMES:
        raise ClosingLineError(f"unexpected query outcome: {outcome!r}")
    return _unavailable(outcome, side_n, authoritative_start, start_version, as_of_value, as_of_class,
                        start_provenance=start_provenance)


def _unavailable(reason, side_n, start, version, as_of_value, as_of_class, start_provenance=None):
    return ClosingLineResult(
        status=STATUS_UNAVAILABLE,
        reason=reason,
        sportsbook=SPORTSBOOK_FANDUEL_ON,
        market=MARKET_ML,
        selected_side=side_n,
        authoritative_start=start,
        start_version=version,
        start_provenance=start_provenance,
        start_is_verified_first_pitch=False,
        as_of=as_of_value,
        as_of_class=as_of_class,
    )
