"""Oracle Stage-2 — stable underlying game identity, content digest, and
observation/window ordering helpers (PM-1263 → PM-1269).

Pure functions only: no network, no database, no commit, no clock reads.
The authoritative decision instant is supplied by the caller from a
database clock sampled inside the locked transaction (PM-1269 §1); this
module never reads a process clock and never fabricates time.

Stable Underlying Identity (SUI), PM-1265 §1.1:
    SUI = (source_namespace, sport_id, game_pk)

`game_pk` is the numeric MLB Stats API gamePk as a string; it is kept as a
string so the namespaced triple is stable and comparable regardless of the
provider that produced it.  Only two namespaces exist in Phase 1:
`mlb-statsapi` (live) and `fixture` (deterministic tests / legacy fixture
history).  They never collide (PM-1267 §4.2 / PM-1269 §4).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

SOURCE_NAMESPACE_MLB = "mlb-statsapi"
SOURCE_NAMESPACE_FIXTURE = "fixture"
SPORT_ID_MLB = 1

# Window ledger actions (PM-1267 §1.4 / PM-1269 §2, §3).
WINDOW_ACTION_ESTABLISHED = "window_established"
WINDOW_ACTION_SUPERSEDED = "window_superseded"
WINDOW_ACTION_BLOCKED_PRIOR_EXPIRED = "window_blocked_prior_expired"
WINDOW_ACTION_BLOCKED_PRIOR_ADMISSION = "window_blocked_prior_admission"
# A candidate that is not strictly newer than the current unexpired authoritative
# window does not supersede it (PM-1269 §3.4): recorded as non-authoritative
# evidence, never silently promoted.
WINDOW_ACTION_BLOCKED_STALE_OBSERVATION = "window_blocked_stale_observation"

WINDOW_ACTIONS = frozenset({
    WINDOW_ACTION_ESTABLISHED,
    WINDOW_ACTION_SUPERSEDED,
    WINDOW_ACTION_BLOCKED_PRIOR_EXPIRED,
    WINDOW_ACTION_BLOCKED_PRIOR_ADMISSION,
    WINDOW_ACTION_BLOCKED_STALE_OBSERVATION,
})

# Stage-8 admission pre-check outcomes (pure; PM-1269 §1.7).
STAGE8_OK = "ok"
STAGE8_INELIGIBLE_ALREADY_ADMITTED = "already_admitted_for_underlying_game"   # D-4
STAGE8_INELIGIBLE_PRIOR_EXPIRED = "prior_window_expired_no_reopen"            # D-5
STAGE8_INELIGIBLE_SUPERSEDED = "superseded_by_newer_revision"
STAGE8_INELIGIBLE_NOT_AUTHORITATIVE = "not_authoritative_window"

_RE_GAME_PK = re.compile(r"[0-9]+")
# game_run_id format: {slate_run_id}-{AWAY}-{HOME}-{gamePk} (identifier_manager).
_RE_GAME_RUN_ID_TAIL = re.compile(r"-([0-9]+)$")


class IdentityError(Exception):
    """Raised when a stable-identity input is missing or malformed."""


def make_sui(source_namespace: str, sport_id: int, game_pk: object) -> tuple[str, int, str]:
    """Build a validated SUI triple. game_pk is normalized to a numeric string.

    Raises IdentityError on any malformed component. This never guesses a
    namespace: the caller supplies it explicitly (PM-1269 §4 forbids
    inferring live provenance).
    """
    if not isinstance(source_namespace, str) or not source_namespace:
        raise IdentityError(f"source_namespace must be a non-empty str, got {source_namespace!r}")
    if isinstance(sport_id, bool) or not isinstance(sport_id, int):
        raise IdentityError(f"sport_id must be an int, got {sport_id!r}")
    game_pk_str = str(game_pk)
    if not game_pk_str.isdigit():
        raise IdentityError(f"game_pk must be a numeric string, got {game_pk!r}")
    return (source_namespace, sport_id, game_pk_str)


def sui_string(sui: tuple[str, int, str]) -> str:
    """Canonical string form `"{namespace}:{sport_id}:{game_pk}"`.

    Also the canonical sort key for deterministic multi-SUI lock ordering
    (PM-1269 §3 / PM-1267 §3.1) and the advisory-lock key material.
    """
    source_namespace, sport_id, game_pk = sui
    return f"{source_namespace}:{sport_id}:{game_pk}"


def advisory_lock_key(sui: tuple[str, int, str]) -> str:
    """Advisory-lock key material for a SUI (serialization only; PM-1269 §3.3).

    A hash collision may serialize unrelated SUIs (harmless); it never
    establishes identity — the durable UNIQUE(SUI) claim does that.
    """
    return f"sui:{sui_string(sui)}"


def parse_game_pk_from_game_run_id(game_run_id: str) -> str | None:
    """Return the trailing gamePk segment of a game_run_id, or None if absent.

    Used only for trustworthy legacy backfill (PM-1269 §4.2). A value that
    does not parse forces fail-closed handling at the caller; it is never
    guessed.
    """
    if not isinstance(game_run_id, str):
        return None
    match = _RE_GAME_RUN_ID_TAIL.search(game_run_id)
    return match.group(1) if match else None


def normalize_utc_iso(value: object) -> str:
    """Normalize a timezone-aware datetime to `YYYY-MM-DDTHH:MM:SSZ` (UTC, seconds).

    Rejects naive datetimes and non-datetimes (fail-closed): content identity
    must never depend on an ambiguous local time.
    """
    if not isinstance(value, datetime) or value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise IdentityError(f"expected a timezone-aware datetime, got {value!r}")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Canonical content fields for the snapshot content digest (PM-1269 §4.2 /
# PM-1265 §4.2). retrieved_at, requested_slate_date, venue, event_id are
# deliberately EXCLUDED so equal schedule content observed at different times
# compares equal.
def content_digest(
    *,
    source_namespace: str,
    sport_id: int,
    game_pk: object,
    away_team: str,
    home_team: str,
    scheduled_start_at: object,
    game_status: str,
    source_game_date: str | None,
) -> str:
    """Deterministic SHA-256 content identity over normalized content fields only.

    Excludes retrieval time (PM-1269 §4.2): two retrievals with identical
    schedule content but different retrieved_at produce the SAME digest. This
    is a hash of retained normalized evidence, NOT of the raw provider
    response and NOT a retrieval timestamp.
    """
    sui = make_sui(source_namespace, sport_id, game_pk)
    material = {
        "source_namespace": sui[0],
        "sport_id": sui[1],
        "game_pk": sui[2],
        "away_team": away_team,
        "home_team": home_team,
        "scheduled_start_at": normalize_utc_iso(scheduled_start_at),
        "game_status": game_status,
        "source_game_date": source_game_date or "",
    }
    blob = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return "SC-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def window_identity(game_run_id: str, digest: str) -> str:
    """Deterministic authoritative-window identity for a run (PM-1269 §2.2)."""
    material = f"{game_run_id}|{digest}"
    return "S2W-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def is_timezone_aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.tzinfo.utcoffset(value) is not None
    )


def is_expired(decision_at: object, scheduled_cutoff_at: object) -> bool:
    """True iff decision_at is AT OR AFTER the cutoff (equality == expired).

    Consistent with the strict Stage-8 gate (only decision < cutoff admits).
    Both instants must be timezone-aware; otherwise IdentityError (never a
    silent coercion, PM-1269 §1.4).
    """
    if not (is_timezone_aware(decision_at) and is_timezone_aware(scheduled_cutoff_at)):
        raise IdentityError("expiry comparison requires two timezone-aware datetimes")
    return decision_at >= scheduled_cutoff_at


def is_strictly_newer(candidate_retrieved_at: object, current_retrieved_at: object) -> bool:
    """True iff the candidate observation is strictly newer by local retrieved_at.

    Establishes LOCAL observation order only (PM-1269 §3) — NOT proof of
    freshness inside the provider's system. Equal or unusable ordering values
    return False (the caller then fails closed / does not supersede).
    """
    if not (is_timezone_aware(candidate_retrieved_at) and is_timezone_aware(current_retrieved_at)):
        return False
    return candidate_retrieved_at > current_retrieved_at


def decide_window_action(
    *,
    claim_exists: bool,
    authoritative_cutoff: object,
    authoritative_retrieved_at: object,
    candidate_retrieved_at: object,
    decision_at: object,
) -> tuple[str, bool]:
    """Pure D-4 / D-5 / supersession / stale-observation decision (PM-1269 §1–§3).

    Returns (window_action, supersede_prior). `supersede_prior` is True only for
    a valid pre-expiry supersession, in which case the caller marks the prior
    authoritative window superseded and establishes this run's window.

    - claim exists                     → BLOCKED_PRIOR_ADMISSION (D-4)
    - no authoritative window          → ESTABLISHED (first window)
    - authoritative window expired     → BLOCKED_PRIOR_EXPIRED (D-5)
    - unexpired + candidate strictly newer → ESTABLISHED + supersede prior
    - unexpired + not strictly newer   → BLOCKED_STALE_OBSERVATION (retain prior)

    `decision_at` MUST be the database-derived authoritative instant sampled
    after locks (PM-1269 §1); this function never reads a clock.
    """
    if claim_exists:
        return (WINDOW_ACTION_BLOCKED_PRIOR_ADMISSION, False)
    if authoritative_cutoff is None:
        return (WINDOW_ACTION_ESTABLISHED, False)
    if is_expired(decision_at, authoritative_cutoff):
        return (WINDOW_ACTION_BLOCKED_PRIOR_EXPIRED, False)
    if is_strictly_newer(candidate_retrieved_at, authoritative_retrieved_at):
        return (WINDOW_ACTION_ESTABLISHED, True)
    return (WINDOW_ACTION_BLOCKED_STALE_OBSERVATION, False)


def stage8_precheck(*, claim_exists: bool, run_window_action: object, run_is_superseded: bool) -> str:
    """Pure Stage-8 admission pre-check over persisted window/claim state (PM-1269 §1.7).

    Returns one of the STAGE8_* outcomes. STAGE8_OK means the run is the
    current authoritative window and no SUI claim exists yet; the caller then
    applies the existing strict cutoff gate and the all-or-none claim+admission
    write. The durable UNIQUE(SUI) claim remains the final backstop.
    """
    if claim_exists:
        return STAGE8_INELIGIBLE_ALREADY_ADMITTED
    if run_is_superseded or run_window_action == WINDOW_ACTION_SUPERSEDED:
        return STAGE8_INELIGIBLE_SUPERSEDED
    if run_window_action == WINDOW_ACTION_BLOCKED_PRIOR_EXPIRED:
        return STAGE8_INELIGIBLE_PRIOR_EXPIRED
    if run_window_action == WINDOW_ACTION_BLOCKED_PRIOR_ADMISSION:
        return STAGE8_INELIGIBLE_ALREADY_ADMITTED
    if run_window_action == WINDOW_ACTION_BLOCKED_STALE_OBSERVATION:
        return STAGE8_INELIGIBLE_NOT_AUTHORITATIVE
    if run_window_action != WINDOW_ACTION_ESTABLISHED:
        return STAGE8_INELIGIBLE_NOT_AUTHORITATIVE
    return STAGE8_OK
