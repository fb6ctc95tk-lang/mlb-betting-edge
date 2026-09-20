"""Deterministic daily ranking for Moneyline Evaluator v0 (PM-1287 §D / PM-1289 §4).

Pure and deterministic. Ranks ASSESSED assessments that carry a directional
selection; INSUFFICIENT_EVIDENCE and NO_SELECTION are excluded from the selection
list (they remain valid game-analysis outputs). Identity is the full SUI
(source_namespace, sport_id, game_pk); distinct namespaces are never merged.

Ranking tuple (first difference decides):
  1. assessment_confidence  DESC  (High=3, Moderate=2, Low=1)
  2. directional_margin      DESC
  3. coverage               DESC
  4. game_pk                ASC   (numeric)
  5. sui_string             ASC   (lexicographic; only breaks cross-namespace game_pk ties)

No official three-play cap; empty input returns an empty list.
"""

from __future__ import annotations

import dataclasses

from backend.oracle.moneyline_evaluator import (
    ASSESSED,
    Q_PRESENT,
    MoneylineAssessment,
    _BAND_RANK,
)

MODEL_VERSION = "daily-rank-v0"


def _canonical(a: MoneylineAssessment) -> dict:
    """Complete decision-relevant canonical form of an assessment (PM-1301).

    Two same-SUI assessments are identical duplicates ONLY when their ENTIRE
    output content matches — not merely the sorting-tuple fields. The prior
    signature compared only analytical state/selection/confidence/reason/score/
    margin/coverage, so same-SUI assessments differing in quote context/
    resolution, readiness, missing inputs, reasoning/counterarguments, timing,
    teams, or method/output provenance were silently collapsed first-input-wins
    (e.g. PRESENT vs ABSENT quote), making price_bearing input-order-dependent.

    This uses the FULL output schema via dataclasses.asdict, which recurses into
    the nested QuoteResolution, the readiness/reasoning/quote-provenance/timing/
    identity fields, and official_status/method_version. Comparison is by value
    equality (``==``) on the canonical dicts, which is insensitive to mapping
    key-insertion order and treats equal-instant tz-aware datetimes as equal —
    honoring the equivalences the contract already treats as identical, without
    collapsing materially different content.
    """
    return dataclasses.asdict(a)


def _equivalent(a: MoneylineAssessment, b: MoneylineAssessment) -> bool:
    return _canonical(a) == _canonical(b)


def _dedupe_by_sui(assessments):
    """Return (kept, conflicts). Fully identical same-SUI assessments collapse to
    one; any materially different same-SUI content fails closed as a
    conflicting_duplicate (excluded from all output). Deterministic and
    permutation-invariant: a group collapses iff every member is fully equivalent
    (a single equivalence class), independent of input order; a later duplicate
    cannot restore a SUI already identified as conflicting.
    """
    by_sui: dict[tuple, list] = {}
    order: list[tuple] = []
    for a in assessments:
        key = a.sui()
        if key not in by_sui:
            by_sui[key] = []
            order.append(key)
        by_sui[key].append(a)
    kept, conflicts = [], []
    for key in order:
        group = by_sui[key]
        first = group[0]
        if all(_equivalent(first, other) for other in group[1:]):
            kept.append(first)  # every member is fully identical -> collapse to one
        else:
            ns, sport, pk = key
            conflicts.append({"sui": {"source_namespace": ns, "sport_id": sport, "game_pk": pk},
                              "sui_string": f"{ns}:{sport}:{pk}",
                              "reason": "conflicting_duplicate", "n_entries": len(group)})
    return kept, conflicts


def _sort_key(a: MoneylineAssessment):
    # Negatives give DESC for confidence/margin/coverage; game_pk numeric ASC then sui_string ASC.
    return (
        -_BAND_RANK[a.assessment_confidence],
        -a.directional_margin,
        -a.coverage,
        int(a.game_pk),
        a.sui_string,
    )


def dedupe_report(assessments) -> dict:
    kept, conflicts = _dedupe_by_sui(list(assessments))
    return {"kept": len(kept), "conflicts": conflicts}


def rank(assessments) -> list:
    """Ranked selection list: deduped by SUI (conflicts excluded), eligible only, ordered."""
    kept, _conflicts = _dedupe_by_sui(list(assessments))
    eligible = [a for a in kept if a.analysis_state == ASSESSED and a.directional_selection is not None]
    return sorted(eligible, key=_sort_key)


def price_bearing(assessments) -> list:
    """Subset of the ranked selection list whose bound quote status is PRESENT."""
    return [a for a in rank(assessments)
            if a.quote_context is not None and a.quote_context.status == Q_PRESENT]
