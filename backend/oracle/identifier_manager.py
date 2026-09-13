"""Oracle Phase 1 — Identifier Lifecycle Manager.

Generates and validates the five Oracle Phase 1 identifiers:

  Slate Run ID    ORACLE-YYYYMMDD-NNN          database-backed, advisory-locked
  Game Run ID     ORACLE-YYYYMMDD-NNN-AW-HM-G  deterministic
  Evaluation ID   EVAL-{game_run_id}-ML-v{n}   deterministic, ML-only
  Candidate ID    CAND-{game_run_id}-ML         deterministic, ML-only
  Play ID         EO-YYYY-NNN                  database-backed, advisory-locked, governed-path

DATABASE CONNECTION CONTRACT
  Database-backed generators (Slate Run ID, Play ID) accept an existing
  psycopg2 connection with autocommit DISABLED. The caller owns the connection
  lifecycle, transaction lifecycle, commit, and rollback. The Identifier Manager
  creates and closes cursors only; all exceptions propagate to the caller.

ADVISORY LOCK KEY CONSTRUCTION
  Locks are transaction-scoped (released automatically on COMMIT or ROLLBACK).
  Keys are packed into a single PostgreSQL bigint using bit-shifting:

    Slate Run ID:  key = (_LOCK_NS_SLATE << 32) | date_yyyymmdd
                   _LOCK_NS_SLATE = 1001 (fixed namespace constant)
                   date_yyyymmdd  = YYYYMMDD integer, e.g. 20260720

    Play ID:       key = (_LOCK_NS_PLAY << 32) | year
                   _LOCK_NS_PLAY = 1002 (fixed namespace constant)
                   year           = YYYY integer, e.g. 2026

  Namespace constants 1001 and 1002 are arbitrary, fixed, and distinct.
  All values fit in PostgreSQL bigint range. Python hash() is never used.
"""

from __future__ import annotations

import re
from datetime import date


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class IdentifierError(Exception):
    """Base class for all Oracle Identifier Manager errors."""


class InvalidIdentifierInputError(IdentifierError):
    """Raised when a generator or validator receives an invalid input value."""


class InvalidConnectionStateError(IdentifierError):
    """Raised when the caller-supplied connection has autocommit enabled.

    The Identifier Manager requires autocommit=False because it relies on
    transaction-scoped advisory locks. Enabling autocommit would cause the
    lock to release immediately after acquisition, defeating its purpose.
    """


class UnauthorizedPlayIdGenerationError(IdentifierError):
    """Raised when generate_play_id() is invoked without a valid capability.

    Checked before any database interaction. Not a cryptographic boundary;
    prevents accidental invocation from call sites other than the governed
    Orchestrator nomination function.
    """


# ---------------------------------------------------------------------------
# Supported markets (Phase 1: ML only)
# ---------------------------------------------------------------------------

_SUPPORTED_MARKETS: frozenset[str] = frozenset({"ML"})


# ---------------------------------------------------------------------------
# Advisory lock namespace constants
# ---------------------------------------------------------------------------

_LOCK_NS_SLATE: int = 1001  # Namespace for Slate Run ID sequence locks
_LOCK_NS_PLAY: int = 1002   # Namespace for Play ID sequence locks


# ---------------------------------------------------------------------------
# Validation patterns — full-string matching via re.fullmatch()
# ---------------------------------------------------------------------------

_RE_SLATE_RUN_ID = re.compile(
    r"ORACLE-\d{8}-\d{3}"
)
_RE_GAME_RUN_ID = re.compile(
    r"ORACLE-\d{8}-\d{3}-[A-Z]{2,3}-[A-Z]{2,3}-\d+"
)
_RE_EVALUATION_ID = re.compile(
    r"EVAL-ORACLE-\d{8}-\d{3}-[A-Z]{2,3}-[A-Z]{2,3}-\d+-ML-v\d+"
)
_RE_CANDIDATE_ID = re.compile(
    r"CAND-ORACLE-\d{8}-\d{3}-[A-Z]{2,3}-[A-Z]{2,3}-\d+-ML"
)
_RE_PLAY_ID = re.compile(
    r"EO-\d{4}-\d{3}"
)

_RE_TEAM_ABBR = re.compile(r"[A-Z]{2,3}")


# ---------------------------------------------------------------------------
# Governed-path capability for Play ID generation
# ---------------------------------------------------------------------------

class _PlayIdCapability:
    """Opaque capability token required by generate_play_id().

    Not a cryptographic or security boundary. Prevents accidental invocation
    of Play ID generation from call sites other than the designated Orchestrator
    nomination function. Instances are created only via _create_play_id_capability().
    """

    __slots__ = ()


def _create_play_id_capability() -> _PlayIdCapability:
    """Return a capability token authorizing a Play ID generation call.

    In production, only the WP-4 Orchestrator's governed nomination function
    calls this. Tests may call it directly under the "tests may use an
    internal, narrowly scoped helper" provision.
    """
    return _PlayIdCapability()


def create_manual_play_id_capability() -> _PlayIdCapability:
    """Return a Play-ID capability token for the sanctioned MANUAL paper-play path.

    Sanctions backend/oracle/manual_play.py as an authorized caller of
    generate_play_id() for manually-recorded paper plays (origin='MANUAL').

    This token is an anti-accident guard ONLY. It is NOT a cryptographic or
    security boundary and enforces no authorization; it merely prevents
    accidental Play-ID generation from unrelated call sites.
    """
    return _create_play_id_capability()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_manual_transaction(conn: object) -> None:
    """Raise InvalidConnectionStateError if the connection has autocommit enabled."""
    if getattr(conn, "autocommit", False):
        raise InvalidConnectionStateError(
            "Connection must have autocommit=False. "
            "The Identifier Manager uses transaction-scoped advisory locks; "
            "the caller owns the transaction lifecycle."
        )


def _slate_run_lock_key(date_int: int) -> int:
    """Return the bigint advisory lock key for a Slate Run ID sequence lock.

    key = (_LOCK_NS_SLATE << 32) | date_yyyymmdd
    Namespace 1001 occupies the high 32 bits; the YYYYMMDD date occupies
    the low 32 bits. Result fits in PostgreSQL bigint range.
    """
    return (_LOCK_NS_SLATE << 32) | date_int


def _play_id_lock_key(year_int: int) -> int:
    """Return the bigint advisory lock key for a Play ID sequence lock.

    key = (_LOCK_NS_PLAY << 32) | year
    Namespace 1002 occupies the high 32 bits; the calendar year occupies
    the low 32 bits. Result fits in PostgreSQL bigint range.
    """
    return (_LOCK_NS_PLAY << 32) | year_int


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def generate_slate_run_id(current_date_et: date, conn: object) -> str:
    """Generate the next Slate Run ID for the given America/Toronto business date.

    Format:  ORACLE-YYYYMMDD-NNN
    Example: ORACLE-20260720-001

    Acquires a transaction-scoped advisory lock keyed on the business date
    before querying oracle_slate_runs. The caller must supply a psycopg2
    connection with autocommit=False and must own the transaction: this
    function does not INSERT, COMMIT, or ROLLBACK.

    The returned identifier is a proposal; it becomes final only after the
    caller successfully inserts it into oracle_slate_runs within the same
    transaction.

    Args:
        current_date_et: The America/Toronto business date for this slate run.
            Never derived internally — always supplied by the caller.
        conn: An existing psycopg2 connection with autocommit=False.

    Returns:
        A string formatted as ORACLE-YYYYMMDD-NNN.

    Raises:
        InvalidIdentifierInputError: If current_date_et is not a datetime.date.
        InvalidConnectionStateError: If conn has autocommit enabled.
        Any psycopg2 exception propagates unchanged.
    """
    if not isinstance(current_date_et, date):
        raise InvalidIdentifierInputError(
            f"current_date_et must be a datetime.date, "
            f"got {type(current_date_et).__name__!r}"
        )
    _require_manual_transaction(conn)

    date_str = current_date_et.strftime("%Y%m%d")
    date_int = int(date_str)
    lock_key = _slate_run_lock_key(date_int)
    like_prefix = f"ORACLE-{date_str}-%"

    cur = conn.cursor()
    try:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
        cur.execute(
            "SELECT COUNT(*) FROM oracle_slate_runs WHERE slate_run_id LIKE %s",
            (like_prefix,),
        )
        count: int = cur.fetchone()[0]
    finally:
        cur.close()

    return f"ORACLE-{date_str}-{count + 1:03d}"


def generate_game_run_id(
    slate_run_id: str,
    away_team_abbreviation: str,
    home_team_abbreviation: str,
    game_pk: int,
) -> str:
    """Generate a Game Analysis Run ID.

    Format:  {slate_run_id}-{AWAY}-{HOME}-{gamePk}
    Example: ORACLE-20260720-001-BOS-NYY-745001

    Deterministic from inputs. No database query. Away team is listed before
    home team. gamePk distinguishes doubleheaders between the same teams on
    the same date. The caller supplies canonical uppercase abbreviations;
    this function performs no alias normalization.

    Args:
        slate_run_id: A valid Slate Run ID (ORACLE-YYYYMMDD-NNN).
        away_team_abbreviation: 2–3 uppercase ASCII letters (e.g. "BOS").
        home_team_abbreviation: 2–3 uppercase ASCII letters (e.g. "NYY").
        game_pk: Positive integer. The MLB Stats API gamePk uniquely identifying
            the game; distinguishes doubleheaders from single games.

    Returns:
        A string formatted as ORACLE-YYYYMMDD-NNN-AWAY-HOME-gamePk.

    Raises:
        InvalidIdentifierInputError: For any invalid input value.
    """
    if not isinstance(slate_run_id, str) or not is_valid_slate_run_id(slate_run_id):
        raise InvalidIdentifierInputError(
            f"slate_run_id is not a valid Slate Run ID: {slate_run_id!r}"
        )
    if (
        not isinstance(away_team_abbreviation, str)
        or not _RE_TEAM_ABBR.fullmatch(away_team_abbreviation)
    ):
        raise InvalidIdentifierInputError(
            f"away_team_abbreviation must be 2–3 uppercase ASCII letters, "
            f"got {away_team_abbreviation!r}"
        )
    if (
        not isinstance(home_team_abbreviation, str)
        or not _RE_TEAM_ABBR.fullmatch(home_team_abbreviation)
    ):
        raise InvalidIdentifierInputError(
            f"home_team_abbreviation must be 2–3 uppercase ASCII letters, "
            f"got {home_team_abbreviation!r}"
        )
    if (
        not isinstance(game_pk, int)
        or isinstance(game_pk, bool)
        or game_pk <= 0
    ):
        raise InvalidIdentifierInputError(
            f"game_pk must be a positive integer, got {game_pk!r}"
        )

    return (
        f"{slate_run_id}-{away_team_abbreviation}-{home_team_abbreviation}-{game_pk}"
    )


def generate_evaluation_id(game_run_id: str, market: str, version: int) -> str:
    """Generate an Evaluation ID.

    Format:  EVAL-{game_run_id}-ML-v{version}
    Example: EVAL-ORACLE-20260720-001-BOS-NYY-745001-ML-v1

    Deterministic from inputs. No database query. Only market "ML" is
    supported in Phase 1. version must be a positive integer (>= 1).

    Args:
        game_run_id: A valid Game Analysis Run ID.
        market: Must be exactly "ML". Other values are rejected.
        version: Positive integer >= 1. v1 is the first evaluation version.

    Returns:
        A string formatted as EVAL-{game_run_id}-ML-v{version}.

    Raises:
        InvalidIdentifierInputError: For invalid game_run_id, unsupported
            market, or version < 1.
    """
    if not isinstance(game_run_id, str) or not is_valid_game_run_id(game_run_id):
        raise InvalidIdentifierInputError(
            f"game_run_id is not a valid Game Analysis Run ID: {game_run_id!r}"
        )
    if market not in _SUPPORTED_MARKETS:
        raise InvalidIdentifierInputError(
            f"Unsupported market {market!r}. "
            f"Phase 1 supports: {sorted(_SUPPORTED_MARKETS)}"
        )
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise InvalidIdentifierInputError(
            f"version must be a positive integer >= 1, got {version!r}"
        )

    return f"EVAL-{game_run_id}-{market}-v{version}"


def generate_candidate_id(game_run_id: str, market: str) -> str:
    """Generate a Candidate ID.

    Format:  CAND-{game_run_id}-ML
    Example: CAND-ORACLE-20260720-001-BOS-NYY-745001-ML

    Deterministic from inputs. No database query. Only market "ML" is
    supported in Phase 1. The Candidate ID is stable across re-evaluations.

    Args:
        game_run_id: A valid Game Analysis Run ID.
        market: Must be exactly "ML". Other values are rejected.

    Returns:
        A string formatted as CAND-{game_run_id}-ML.

    Raises:
        InvalidIdentifierInputError: For invalid game_run_id or unsupported market.
    """
    if not isinstance(game_run_id, str) or not is_valid_game_run_id(game_run_id):
        raise InvalidIdentifierInputError(
            f"game_run_id is not a valid Game Analysis Run ID: {game_run_id!r}"
        )
    if market not in _SUPPORTED_MARKETS:
        raise InvalidIdentifierInputError(
            f"Unsupported market {market!r}. "
            f"Phase 1 supports: {sorted(_SUPPORTED_MARKETS)}"
        )

    return f"CAND-{game_run_id}-{market}"


def generate_play_id(
    current_date_et: date,
    conn: object,
    capability: object,
) -> str:
    """Generate the next Play ID for the current calendar year (governed-path only).

    Format:  EO-YYYY-NNN
    Example: EO-2026-001

    GOVERNED PATH: This function may only be called from the designated
    Orchestrator nomination function. Any other invocation raises
    UnauthorizedPlayIdGenerationError BEFORE any database interaction.
    Obtain a capability via _create_play_id_capability().

    Acquires a transaction-scoped advisory lock keyed on the calendar year
    before querying oracle_plays. The caller must supply a psycopg2 connection
    with autocommit=False and must own the transaction: this function does
    not INSERT, COMMIT, or ROLLBACK.

    The returned identifier is a proposal; it becomes final only after the
    caller successfully inserts it into oracle_plays within the same transaction.

    Args:
        current_date_et: The America/Toronto business date. The year component
            determines the calendar year for sequence scoping. Never derived
            internally — always supplied by the caller.
        conn: An existing psycopg2 connection with autocommit=False.
        capability: A _PlayIdCapability instance from _create_play_id_capability().

    Returns:
        A string formatted as EO-YYYY-NNN.

    Raises:
        UnauthorizedPlayIdGenerationError: If capability is not a _PlayIdCapability
            instance. Raised before any database or cursor interaction.
        InvalidIdentifierInputError: If current_date_et is not a datetime.date.
        InvalidConnectionStateError: If conn has autocommit enabled.
        Any psycopg2 exception propagates unchanged.
    """
    # Governed-path check: must be first, before any database interaction.
    if not isinstance(capability, _PlayIdCapability):
        raise UnauthorizedPlayIdGenerationError(
            "Play ID generation requires a _PlayIdCapability token. "
            "Only the governed Orchestrator nomination path may generate Play IDs. "
            "Obtain a capability via _create_play_id_capability()."
        )

    if not isinstance(current_date_et, date):
        raise InvalidIdentifierInputError(
            f"current_date_et must be a datetime.date, "
            f"got {type(current_date_et).__name__!r}"
        )
    _require_manual_transaction(conn)

    year = current_date_et.year
    lock_key = _play_id_lock_key(year)
    like_prefix = f"EO-{year}-%"

    cur = conn.cursor()
    try:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
        cur.execute(
            "SELECT COUNT(*) FROM oracle_plays WHERE play_id LIKE %s",
            (like_prefix,),
        )
        count: int = cur.fetchone()[0]
    finally:
        cur.close()

    return f"EO-{year}-{count + 1:03d}"


# ---------------------------------------------------------------------------
# Validation functions — structural format only, no database queries
# ---------------------------------------------------------------------------

def is_valid_slate_run_id(value: str) -> bool:
    """Return True if value exactly matches the Slate Run ID format.

    Pattern: ORACLE-\\d{8}-\\d{3}
    Full-string match. Non-string values return False.
    """
    if not isinstance(value, str):
        return False
    return _RE_SLATE_RUN_ID.fullmatch(value) is not None


def is_valid_game_run_id(value: str) -> bool:
    """Return True if value exactly matches the Game Analysis Run ID format.

    Pattern: ORACLE-\\d{8}-\\d{3}-[A-Z]{2,3}-[A-Z]{2,3}-\\d+
    Full-string match. Non-string values return False.
    """
    if not isinstance(value, str):
        return False
    return _RE_GAME_RUN_ID.fullmatch(value) is not None


def is_valid_evaluation_id(value: str) -> bool:
    """Return True if value exactly matches the Evaluation ID format.

    Pattern: EVAL-ORACLE-\\d{8}-\\d{3}-[A-Z]{2,3}-[A-Z]{2,3}-\\d+-ML-v\\d+
    Full-string match. Non-string values return False.
    """
    if not isinstance(value, str):
        return False
    return _RE_EVALUATION_ID.fullmatch(value) is not None


def is_valid_candidate_id(value: str) -> bool:
    """Return True if value exactly matches the Candidate ID format.

    Pattern: CAND-ORACLE-\\d{8}-\\d{3}-[A-Z]{2,3}-[A-Z]{2,3}-\\d+-ML
    Full-string match. Non-string values return False.
    """
    if not isinstance(value, str):
        return False
    return _RE_CANDIDATE_ID.fullmatch(value) is not None


def is_valid_play_id(value: str) -> bool:
    """Return True if value exactly matches the Play ID format.

    Pattern: EO-\\d{4}-\\d{3}
    Full-string match. Non-string values return False.
    """
    if not isinstance(value, str):
        return False
    return _RE_PLAY_ID.fullmatch(value) is not None
