"""Oracle Inc-1 Stage 3 — Preliminary Data Gather module (N-1).

Provides gather_preliminary_data(), which calls the adapter MI-6 method
with retry logic.  The caller (Orchestrator) owns all DB state changes
and transaction boundaries (DCR-W5-001).
"""

from __future__ import annotations

from backend.oracle.adapter_interface import PreliminaryDataResponse, SportModuleAdapter


def gather_preliminary_data(
    game_id: str,
    adapter: SportModuleAdapter,
    retry_count: int = 3,
) -> PreliminaryDataResponse:
    """Gather preliminary data for one game via the adapter with retry logic.

    Calls adapter.get_preliminary_data(game_id) up to retry_count times.
    Returns immediately on the first successful (available=True) response.
    Returns the last response if all attempts fail.

    Args:
        game_id: The gamePk string (last segment of game_run_id).
        adapter: A SportModuleAdapter implementing MI-6.
        retry_count: Maximum number of attempts (default 3).

    Returns:
        PreliminaryDataResponse — successful on first available=True,
        or the final unavailable response after retry_count exhaustion.
    """
    response: PreliminaryDataResponse | None = None
    for _ in range(retry_count):
        response = adapter.get_preliminary_data(game_id)
        if response.availability.available:
            return response
    return response  # type: ignore[return-value]
