"""Oracle Phase 1 — Slate-level and game-level state machine validators.

Both machines are pure, stateless functions over explicit transition
allowlists.  Each function validates a (from_state, to_state) pair and
returns to_state on success, or raises InvalidStateTransitionError.

Neither machine stores state, writes to the database, or emits events.
The caller owns state persistence and event ownership (DCR-W4-005).

Slate machine — 10 states (§10.3, DCR-W4-002):
    initializing | schedule_loaded | analysis_in_progress |
    activation_window_open | pregame_locked | settled | partial_void |
    analysis_failed | activation_failed | settlement_pending_retry

    DCR-W4-002 additions:
        pregame_locked → settlement_pending_retry
        partial_void   → settlement_pending_retry

    Terminal: settled | analysis_failed | activation_failed

Game machine — 9 states (§10.4, DCR-W4-003):
    scheduled | preliminary_analysis | lineup_monitoring | final_analysis |
    activation_eligible | pregame_locked | settled | voided | postponed

    analysis_failed is NOT a game state (deliberate asymmetry per §10.4).

    Terminal: settled | voided | postponed
"""

from __future__ import annotations


class InvalidStateTransitionError(Exception):
    """Raised when a proposed state transition is not in the allowlist."""


# ---------------------------------------------------------------------------
# Slate-level state machine (10 states)
# ---------------------------------------------------------------------------

_SLATE_STATES: frozenset[str] = frozenset({
    "initializing",
    "schedule_loaded",
    "analysis_in_progress",
    "activation_window_open",
    "pregame_locked",
    "settled",
    "partial_void",
    "analysis_failed",
    "activation_failed",
    "settlement_pending_retry",
})

_SLATE_TERMINAL_STATES: frozenset[str] = frozenset({
    "settled",
    "analysis_failed",
    "activation_failed",
})

_SLATE_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("initializing",           "schedule_loaded"),
    ("initializing",           "analysis_failed"),
    ("schedule_loaded",        "analysis_in_progress"),
    ("analysis_in_progress",   "activation_window_open"),
    ("analysis_in_progress",   "analysis_failed"),
    ("activation_window_open", "pregame_locked"),
    ("activation_window_open", "activation_failed"),
    ("pregame_locked",         "settled"),
    ("pregame_locked",         "partial_void"),
    ("pregame_locked",         "settlement_pending_retry"),  # DCR-W4-002
    ("partial_void",           "settled"),
    ("partial_void",           "settlement_pending_retry"),  # DCR-W4-002
    ("settlement_pending_retry", "settled"),
})


def transition_slate_state(from_state: str, to_state: str) -> str:
    """Validate and return the result of a slate-level state transition.

    Args:
        from_state: The current slate state.
        to_state:   The proposed next slate state.

    Returns:
        to_state when the transition is in the allowlist.

    Raises:
        InvalidStateTransitionError: If from_state or to_state is unknown,
            if from_state is terminal, or if (from_state, to_state) is not
            in the allowlist.
    """
    if from_state not in _SLATE_STATES:
        raise InvalidStateTransitionError(
            f"Unknown slate state: {from_state!r}"
        )
    if to_state not in _SLATE_STATES:
        raise InvalidStateTransitionError(
            f"Unknown slate target state: {to_state!r}"
        )
    if from_state in _SLATE_TERMINAL_STATES:
        raise InvalidStateTransitionError(
            f"Slate state {from_state!r} is terminal; no outbound transitions permitted"
        )
    if (from_state, to_state) not in _SLATE_TRANSITIONS:
        raise InvalidStateTransitionError(
            f"Slate transition {from_state!r} → {to_state!r} is not in the allowlist"
        )
    return to_state


# ---------------------------------------------------------------------------
# Game-level state machine (9 states)
# ---------------------------------------------------------------------------

_GAME_STATES: frozenset[str] = frozenset({
    "scheduled",
    "preliminary_analysis",
    "lineup_monitoring",
    "final_analysis",
    "activation_eligible",
    "pregame_locked",
    "settled",
    "voided",
    "postponed",
})

_GAME_TERMINAL_STATES: frozenset[str] = frozenset({
    "settled",
    "voided",
    "postponed",
})

_GAME_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("scheduled",             "preliminary_analysis"),
    ("preliminary_analysis",  "lineup_monitoring"),
    ("lineup_monitoring",     "final_analysis"),
    ("final_analysis",        "activation_eligible"),
    ("activation_eligible",   "pregame_locked"),
    ("pregame_locked",        "settled"),
    ("pregame_locked",        "voided"),
    ("pregame_locked",        "postponed"),
})


def transition_game_state(from_state: str, to_state: str) -> str:
    """Validate and return the result of a game-level state transition.

    Args:
        from_state: The current game state.
        to_state:   The proposed next game state.

    Returns:
        to_state when the transition is in the allowlist.

    Raises:
        InvalidStateTransitionError: If from_state or to_state is unknown,
            if from_state is terminal, or if (from_state, to_state) is not
            in the allowlist.
    """
    if from_state not in _GAME_STATES:
        raise InvalidStateTransitionError(
            f"Unknown game state: {from_state!r}"
        )
    if to_state not in _GAME_STATES:
        raise InvalidStateTransitionError(
            f"Unknown game target state: {to_state!r}"
        )
    if from_state in _GAME_TERMINAL_STATES:
        raise InvalidStateTransitionError(
            f"Game state {from_state!r} is terminal; no outbound transitions permitted"
        )
    if (from_state, to_state) not in _GAME_TRANSITIONS:
        raise InvalidStateTransitionError(
            f"Game transition {from_state!r} → {to_state!r} is not in the allowlist"
        )
    return to_state
