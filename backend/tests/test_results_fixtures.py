"""Focused tests for the fixture-only ResultsProvider contract (PM-1115 / PM-1117).

Execution is isolated from DB/network/provider access BEFORE importing the module under test:
socket creation is blocked during the import to prove the module needs no network, then the
original socket is restored so the shared test process is not disturbed. The module is pure
stdlib (re, datetime) and imports no DB/provider client.
"""

from __future__ import annotations

import socket as _socket

import pytest

# --- Pre-import isolation: forbid network (and, by extension, DB/provider) during import. ---
_orig_socket = _socket.socket


def _blocked_socket(*_args, **_kwargs):  # pragma: no cover - must never be called
    raise RuntimeError("network/DB/provider access is forbidden in fixture-contract tests")


_socket.socket = _blocked_socket  # type: ignore[assignment]
try:
    from backend.oracle.results_fixtures import (
        FIXTURE_SOURCE,
        RESULT_STATUSES,
        TEST_DATA_ORIGIN,
        ResultFixtureValidationError,
        _reject_duplicate_ids,
        load_phase1_result_fixtures,
        validate_result_fixture_record,
    )
finally:
    _socket.socket = _orig_socket  # type: ignore[assignment]


def _valid_final_record() -> dict:
    return {
        "external_game_id": "746484",
        "game_status": "final",
        "home_score": 5,
        "away_score": 3,
        "result_observed_at": "2026-07-25T20:45:00Z",
        "source": FIXTURE_SOURCE,
        "data_origin": TEST_DATA_ORIGIN,
    }


# --- Loader: shape, labelling, normalization -------------------------------------------------

def test_load_returns_at_least_two_valid_records():
    records = load_phase1_result_fixtures()
    assert len(records) >= 2
    for r in records:
        validate_result_fixture_record(r)


def test_every_record_is_test_labelled():
    for r in load_phase1_result_fixtures():
        assert r["data_origin"] == TEST_DATA_ORIGIN == "TEST_FIXTURE"
        assert r["source"] == FIXTURE_SOURCE == "results_fixture"


def test_status_tokens_are_normalized_and_in_set():
    for r in load_phase1_result_fixtures():
        status = r["game_status"]
        assert status == status.strip().lower()
        assert status in RESULT_STATUSES


def test_final_has_int_scores_nonfinal_has_none():
    by_id = {r["external_game_id"]: r for r in load_phase1_result_fixtures()}
    assert type(by_id["746484"]["home_score"]) is int
    assert by_id["746484"]["home_score"] >= 0
    assert by_id["746485"]["home_score"] is None
    assert by_id["746485"]["away_score"] is None


# --- Independent copies ----------------------------------------------------------------------

def test_returned_records_are_independent_copies():
    first = load_phase1_result_fixtures()
    first[0]["home_score"] = 999
    first.append({"tampered": True})
    fresh = load_phase1_result_fixtures()
    assert fresh[0]["home_score"] != 999
    assert all("tampered" not in r for r in fresh)


# --- Validation: structural rejections -------------------------------------------------------

def test_reject_non_dict():
    with pytest.raises(ResultFixtureValidationError):
        validate_result_fixture_record(["not", "a", "dict"])


def test_reject_missing_key():
    r = _valid_final_record()
    del r["source"]
    with pytest.raises(ResultFixtureValidationError):
        validate_result_fixture_record(r)


def test_reject_extra_key():
    r = _valid_final_record()
    r["unexpected"] = 1
    with pytest.raises(ResultFixtureValidationError):
        validate_result_fixture_record(r)


def test_reject_non_numeric_and_empty_external_game_id():
    for bad in ("74x", "", "  ", "746484.0"):
        r = _valid_final_record()
        r["external_game_id"] = bad
        with pytest.raises(ResultFixtureValidationError):
            validate_result_fixture_record(r)


# --- Validation: status normalization --------------------------------------------------------

def test_status_normalization_accepts_padded_uppercase():
    r = _valid_final_record()
    r["game_status"] = "  FINAL  "
    validate_result_fixture_record(r)  # normalizes to "final"


def test_reject_out_of_set_status():
    r = _valid_final_record()
    r["game_status"] = "in_progress"
    r["home_score"] = None
    r["away_score"] = None
    with pytest.raises(ResultFixtureValidationError):
        validate_result_fixture_record(r)


# --- Validation: scores ----------------------------------------------------------------------

def test_reject_boolean_scores():
    r = _valid_final_record()
    r["home_score"] = True  # bool must be rejected despite being an int subclass
    with pytest.raises(ResultFixtureValidationError):
        validate_result_fixture_record(r)


def test_reject_float_string_and_negative_scores():
    for bad in (3.0, "3", -1):
        r = _valid_final_record()
        r["home_score"] = bad
        with pytest.raises(ResultFixtureValidationError):
            validate_result_fixture_record(r)


def test_reject_scores_present_when_not_final():
    r = _valid_final_record()
    r["game_status"] = "postponed"
    with pytest.raises(ResultFixtureValidationError):
        validate_result_fixture_record(r)


def test_reject_none_scores_when_final():
    r = _valid_final_record()
    r["home_score"] = None
    with pytest.raises(ResultFixtureValidationError):
        validate_result_fixture_record(r)


# --- Validation: canonical UTC timestamp -----------------------------------------------------

def test_accept_canonical_utc():
    validate_result_fixture_record(_valid_final_record())


def test_reject_noncanonical_timestamps():
    for bad in (
        "2026-07-25T20:45:00",       # missing Z
        "2026-07-25T20:45:00+00:00", # numeric offset
        "2026-07-25 20:45:00Z",      # space separator
        "2026-07-25T20:45:00.000Z",  # fractional seconds
        "2026-13-40T20:45:00Z",      # impossible date
        "2026-07-25t20:45:00z",      # lowercase
    ):
        r = _valid_final_record()
        r["result_observed_at"] = bad
        with pytest.raises(ResultFixtureValidationError):
            validate_result_fixture_record(r)


# --- Validation: sentinels -------------------------------------------------------------------

def test_reject_wrong_sentinels():
    r = _valid_final_record()
    r["source"] = "live"
    with pytest.raises(ResultFixtureValidationError):
        validate_result_fixture_record(r)
    r = _valid_final_record()
    r["data_origin"] = "LIVE"
    with pytest.raises(ResultFixtureValidationError):
        validate_result_fixture_record(r)


# --- Set-level: duplicate id rejection -------------------------------------------------------

def test_reject_duplicate_ids():
    dup = [_valid_final_record(), _valid_final_record()]
    with pytest.raises(ResultFixtureValidationError):
        _reject_duplicate_ids(dup)


def test_canonical_dataset_has_unique_ids():
    records = load_phase1_result_fixtures()
    ids = [r["external_game_id"] for r in records]
    assert len(ids) == len(set(ids))
