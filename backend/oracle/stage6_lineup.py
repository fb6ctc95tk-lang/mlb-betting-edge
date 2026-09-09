"""Stage 6 — evidence-safe lineup snapshot logic (Core-side; network-FREE).

Consumes the normalized ``LineupObservation`` produced by the MLB adapter and
provides deterministic snapshot identity and OBSERVED material-change detection.
This module performs NO network, DB, or clock access (PM-1029 Option B): all
MLB network access lives in ``backend.oracle.mlb_adapter``; timestamps and the
active policy identity are supplied by the Orchestrator.

Epistemic discipline: this module never upgrades PROBABLE/OBSERVED data to
authoritative confirmation. ``lineup_change_detected`` means only that an
observed provider snapshot differs materially from the previous canonical
observed snapshot — never an official scratch, confirmed replacement, or
authoritative roster action.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from backend.oracle.mlb_adapter import LineupObservation, PITCHER_PROBABLE

# Top-of-order window (positions 1-3) for the ">=2 position shift" material rule.
_TOP_OF_ORDER_WINDOW = 3
_TOP_OF_ORDER_MIN_SHIFT = 2


@dataclass(frozen=True)
class Stage6Result:
    """Explicit, immutable, caller-visible per-game Stage 6 outcome (PM-1033).

    Makes UNAVAILABLE / PARTIAL / OBSERVED_FULL and the persistence, replay, and
    material-change facts distinguishable by the caller WITHOUT parsing logs,
    querying the database, or reading lifecycle-audit rows. It is a report of
    what Stage 6 did; it changes no provider classification, persistence rule,
    snapshot identity, event semantics, or product meaning.

    Fields:
      game_run_id      — associates the result with the requested game.
      classification   — 'UNAVAILABLE' | 'PARTIAL' | 'OBSERVED_FULL'.
      persisted        — True iff a canonical observation row was written.
      replay           — True iff this was an identical (idempotent) replay.
      change_detected  — True iff an observed material change vs the prior
                         canonical snapshot was detected.
      reason           — bounded status/reason for UNAVAILABLE/PARTIAL (or None).
      snapshot_identity— identity of the canonical snapshot when applicable.
    """

    game_run_id: str
    classification: str
    persisted: bool
    replay: bool
    change_detected: bool
    reason: str | None = None
    snapshot_identity: str | None = None


def canonical_snapshot(obs: LineupObservation) -> dict:
    """Return a deterministic, JSON-serializable canonical view of an observation."""
    return {
        "home_order": list(obs.home_order),
        "away_order": list(obs.away_order),
        "home_pitcher": _canonical_pitcher(obs.home_pitcher),
        "away_pitcher": _canonical_pitcher(obs.away_pitcher),
        "home_lineup_status": obs.home_lineup_status,
        "away_lineup_status": obs.away_lineup_status,
    }


def canonical_from_stored(
    home_order, away_order, home_pitcher, away_pitcher, home_lineup_status, away_lineup_status
) -> dict:
    """Reconstruct a canonical snapshot from stored DB values (for comparison)."""
    return {
        "home_order": list(home_order or []),
        "away_order": list(away_order or []),
        "home_pitcher": _canonical_pitcher(home_pitcher),
        "away_pitcher": _canonical_pitcher(away_pitcher),
        "home_lineup_status": home_lineup_status,
        "away_lineup_status": away_lineup_status,
    }


def compute_snapshot_identity(game_run_id: str, obs: LineupObservation) -> str:
    """Deterministic content-addressed identity over all material observed values
    and their epistemic statuses (PM-1029 §6)."""
    blob = json.dumps(canonical_snapshot(obs), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"S6O-{game_run_id}-{digest}"


def detect_material_change(current: dict, prior: dict | None) -> tuple[bool, dict]:
    """Compare two canonical snapshots; return (change_detected, evidence).

    Material (OBSERVED) change: a personId added to or removed from a side's
    batting order, a top-of-order (positions 1-3) shift of >=2 positions, or a
    probable-pitcher personId change. Evidence records exactly what changed and
    marks pitcher epistemic status as PROBABLE (never confirmed).
    Returns (False, {}) when there is no prior canonical snapshot.
    """
    if prior is None:
        return False, {}
    evidence: dict = {}
    changed = False
    for side in ("home", "away"):
        cur_order = current[f"{side}_order"]
        pri_order = prior[f"{side}_order"]
        added = [x for x in cur_order if x not in pri_order]
        removed = [x for x in pri_order if x not in cur_order]
        top_shift = _top_of_order_shift(cur_order, pri_order)
        if added or removed or top_shift:
            changed = True
            evidence[f"{side}_lineup"] = {
                "added": added,
                "removed": removed,
                "top_of_order_shift_ge_2": top_shift,
            }
        cur_sp = (current[f"{side}_pitcher"] or {}).get("id")
        pri_sp = (prior[f"{side}_pitcher"] or {}).get("id")
        if cur_sp != pri_sp:
            changed = True
            evidence[f"{side}_probable_pitcher"] = {
                "from": pri_sp,
                "to": cur_sp,
                "epistemic_status": PITCHER_PROBABLE,
                "note": "observed probable-pitcher change; not a confirmed replacement",
            }
    return changed, evidence


def _canonical_pitcher(pitcher: object) -> dict | None:
    if not isinstance(pitcher, dict):
        return None
    pid = pitcher.get("id")
    if pid is None:
        return None
    return {"id": pid, "epistemic_status": pitcher.get("epistemic_status", PITCHER_PROBABLE)}


def _top_of_order_shift(cur_order: list, pri_order: list) -> bool:
    """True if a player present in both orders moved >=2 positions while in or
    into the top-of-order window (positions 1-3)."""
    pri_index = {pid: i for i, pid in enumerate(pri_order)}
    for cur_i, pid in enumerate(cur_order):
        if pid in pri_index:
            pri_i = pri_index[pid]
            if abs(cur_i - pri_i) >= _TOP_OF_ORDER_MIN_SHIFT and (
                cur_i < _TOP_OF_ORDER_WINDOW or pri_i < _TOP_OF_ORDER_WINDOW
            ):
                return True
    return False
