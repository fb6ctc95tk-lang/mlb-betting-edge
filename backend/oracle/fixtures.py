"""Oracle Phase 1 — Schedule fixture data.

Provides pre-defined game records in the ScheduleProvider contract shape
for Phase 1 integration testing.  Phase 2 replaces calls to
load_phase1_fixtures() with live MLB Stats API data; the record shape is
intentionally identical so no call-site changes are required.

ScheduleProvider contract shape (WP-4 specification):
    {
        "external_game_id": str,   # numeric MLB Stats API gamePk, e.g. "746484"
        "home_team":        str,   # 2–3 uppercase team abbreviation
        "away_team":        str,   # 2–3 uppercase team abbreviation
        "first_pitch_time": str,   # UTC ISO-8601, e.g. "2026-07-25T17:10:00Z"
        "venue":            str,   # stadium name
    }

DCR-W4-004: external_game_id is stored and returned as a numeric string.
The conversion to int for generate_game_run_id() is the WP-4 caller's
responsibility; use get_game_pk() at the WP-4 boundary.
"""

from __future__ import annotations

_REQUIRED_KEYS: frozenset[str] = frozenset({
    "external_game_id",
    "home_team",
    "away_team",
    "first_pitch_time",
    "venue",
})

_PHASE_1_FIXTURES: list[dict[str, str]] = [
    {
        "external_game_id": "746484",
        "home_team": "NYY",
        "away_team": "BOS",
        "first_pitch_time": "2026-07-25T17:10:00Z",
        "venue": "Yankee Stadium",
    },
    {
        "external_game_id": "746485",
        "home_team": "LAD",
        "away_team": "SFG",
        "first_pitch_time": "2026-07-25T22:10:00Z",
        "venue": "Dodger Stadium",
    },
]


class FixtureValidationError(Exception):
    """Raised when a fixture record is missing required fields or has invalid values."""


def validate_fixture_record(record: object) -> None:
    """Raise FixtureValidationError if record does not satisfy the fixture contract.

    Checks:
    - record is a dict
    - all required keys are present
    - external_game_id is a str
    - external_game_id contains only digit characters (numeric string)

    Args:
        record: Value to validate.

    Raises:
        FixtureValidationError: On any contract violation.
    """
    if not isinstance(record, dict):
        raise FixtureValidationError(
            f"Fixture record must be a dict, got {type(record).__name__!r}"
        )
    missing = _REQUIRED_KEYS - record.keys()
    if missing:
        raise FixtureValidationError(
            f"Fixture record missing required keys: {sorted(missing)}"
        )
    eid = record["external_game_id"]
    if not isinstance(eid, str):
        raise FixtureValidationError(
            f"external_game_id must be a str, got {type(eid).__name__!r}"
        )
    if not eid.isdigit():
        raise FixtureValidationError(
            f"external_game_id must be a numeric string, got {eid!r}"
        )


def load_phase1_fixtures() -> list[dict[str, str]]:
    """Return the Phase 1 pre-defined fixture game records.

    Returns a new list on each call; mutations do not affect the internal
    module constant.  Each record matches the ScheduleProvider contract shape.

    Returns:
        A list of at least two game record dicts.
    """
    return [dict(record) for record in _PHASE_1_FIXTURES]


def get_game_pk(record: dict) -> int:  # type: ignore[type-arg]
    """Extract external_game_id and convert it to int for the WP-3 Identifier Manager.

    This function is the WP-4 type-conversion boundary defined in DCR-W4-004.
    The fixture contract holds external_game_id as a numeric string; the WP-3
    function generate_game_run_id() requires game_pk as an int.  This function
    validates the record first so callers receive a clear FixtureValidationError
    rather than a bare ValueError on malformed input.

    Args:
        record: A fixture record.  Must satisfy validate_fixture_record().

    Returns:
        external_game_id parsed as a positive integer.

    Raises:
        FixtureValidationError: If the record fails validation.
    """
    validate_fixture_record(record)
    return int(record["external_game_id"])
