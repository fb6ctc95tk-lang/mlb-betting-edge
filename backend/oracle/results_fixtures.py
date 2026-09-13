"""Oracle Phase 1 — fixture-only ResultsProvider contract (PM-1115 frozen exact scope).

Pure, network/DB/provider/clock-FREE test fixtures for final-game results, mirroring the
schedule fixtures in ``fixtures.py``. Every record is explicitly test-labelled
(``data_origin == "TEST_FIXTURE"``) so it can never be mistaken for a live or authoritative
settlement input. This module asserts NO bet, edge, settlement, play, or CLV; it creates no
play and performs no persistence. Live Phase-2 integration later replaces the loader with a
real provider using the identical record shape (the ACR-1 principle).

Frozen field rules (PM-1115 §3):
    external_game_id   str, non-empty, all-digits (join key to the schedule fixture)
    game_status        normalized ``value.strip().lower()`` in RESULT_STATUSES
    home_score/away_score  nonnegative non-boolean int, present IFF game_status == "final",
                       otherwise exactly None
    result_observed_at canonical UTC ``%Y-%m-%dT%H:%M:%SZ`` (uppercase T/Z, seconds precision,
                       no fractional seconds, no numeric offset, no space separator)
    source             exactly FIXTURE_SOURCE
    data_origin        exactly TEST_DATA_ORIGIN (mandatory test label)

Set-level rules: external_game_id is unique across the dataset; each load returns fresh,
independent copies.
"""

from __future__ import annotations

import re
from datetime import datetime

RESULT_STATUSES: frozenset[str] = frozenset({
    "final",
    "postponed",
    "suspended",
    "cancelled",
})

TEST_DATA_ORIGIN: str = "TEST_FIXTURE"
FIXTURE_SOURCE: str = "results_fixture"

_REQUIRED_KEYS: frozenset[str] = frozenset({
    "external_game_id",
    "game_status",
    "home_score",
    "away_score",
    "result_observed_at",
    "source",
    "data_origin",
})

_UTC_SYNTAX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_PHASE_1_RESULT_FIXTURES: list[dict[str, object]] = [
    {
        "external_game_id": "746484",
        "game_status": "final",
        "home_score": 5,
        "away_score": 3,
        "result_observed_at": "2026-07-25T20:45:00Z",
        "source": FIXTURE_SOURCE,
        "data_origin": TEST_DATA_ORIGIN,
    },
    {
        "external_game_id": "746485",
        "game_status": "postponed",
        "home_score": None,
        "away_score": None,
        "result_observed_at": "2026-07-26T01:30:00Z",
        "source": FIXTURE_SOURCE,
        "data_origin": TEST_DATA_ORIGIN,
    },
]


class ResultFixtureValidationError(Exception):
    """Raised when a result fixture record or dataset violates the frozen contract."""


def _is_nonnegative_non_boolean_int(value: object) -> bool:
    # bool is a subclass of int; ``type(value) is int`` rejects True/False by design.
    return type(value) is int and value >= 0


def _canonical_utc(value: object) -> bool:
    if not isinstance(value, str) or _UTC_SYNTAX.match(value) is None:
        return False
    try:
        datetime.strptime(value, _UTC_FORMAT)
    except ValueError:
        return False
    return True


def validate_result_fixture_record(record: object) -> None:
    """Raise ResultFixtureValidationError unless record satisfies every frozen field rule."""
    if not isinstance(record, dict):
        raise ResultFixtureValidationError(
            f"Result fixture record must be a dict, got {type(record).__name__!r}"
        )

    keys = set(record.keys())
    missing = _REQUIRED_KEYS - keys
    extra = keys - _REQUIRED_KEYS
    if missing or extra:
        raise ResultFixtureValidationError(
            f"Result fixture record keys invalid: missing={sorted(missing)} "
            f"extra={sorted(extra)}"
        )

    eid = record["external_game_id"]
    if not isinstance(eid, str) or not eid.isdigit():
        raise ResultFixtureValidationError(
            f"external_game_id must be a non-empty numeric string, got {eid!r}"
        )

    status = record["game_status"]
    if not isinstance(status, str):
        raise ResultFixtureValidationError(
            f"game_status must be a str, got {type(status).__name__!r}"
        )
    normalized = status.strip().lower()
    if normalized not in RESULT_STATUSES:
        raise ResultFixtureValidationError(
            f"game_status {status!r} normalizes to {normalized!r}, not in {sorted(RESULT_STATUSES)}"
        )

    home = record["home_score"]
    away = record["away_score"]
    if normalized == "final":
        if not (_is_nonnegative_non_boolean_int(home) and _is_nonnegative_non_boolean_int(away)):
            raise ResultFixtureValidationError(
                f"final game requires nonnegative non-boolean int scores, got "
                f"home={home!r} away={away!r}"
            )
    else:
        if home is not None or away is not None:
            raise ResultFixtureValidationError(
                f"non-final game ({normalized}) requires None scores, got "
                f"home={home!r} away={away!r}"
            )

    observed = record["result_observed_at"]
    if not _canonical_utc(observed):
        raise ResultFixtureValidationError(
            f"result_observed_at must match {_UTC_FORMAT!r} (…Z), got {observed!r}"
        )

    source = record["source"]
    if source != FIXTURE_SOURCE:
        raise ResultFixtureValidationError(
            f"source must be exactly {FIXTURE_SOURCE!r}, got {source!r}"
        )

    data_origin = record["data_origin"]
    if data_origin != TEST_DATA_ORIGIN:
        raise ResultFixtureValidationError(
            f"data_origin must be exactly {TEST_DATA_ORIGIN!r}, got {data_origin!r}"
        )


def _reject_duplicate_ids(records: list) -> None:  # type: ignore[type-arg]
    seen: set[str] = set()
    for record in records:
        eid = record["external_game_id"]
        if eid in seen:
            raise ResultFixtureValidationError(
                f"duplicate external_game_id in dataset: {eid!r}"
            )
        seen.add(eid)


def load_phase1_result_fixtures() -> list[dict[str, object]]:
    """Return fresh, independent, validated copies of the Phase 1 result fixtures.

    Each call returns a new list of new dicts; caller mutation cannot affect the module
    constant or any other returned record. game_status is returned normalized.
    """
    loaded: list[dict[str, object]] = []
    for record in _PHASE_1_RESULT_FIXTURES:
        validate_result_fixture_record(record)
        copy = dict(record)
        copy["game_status"] = str(record["game_status"]).strip().lower()
        loaded.append(copy)
    _reject_duplicate_ids(loaded)
    return loaded
