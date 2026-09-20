"""Moneyline Evaluator v0 — pure, deterministic, supplied-input (PM-1287 / PM-1289).

Implements the corrected Moneyline Evaluator v0 contract exactly:
  * required F1 starting-pitcher run prevention and F2 team offense;
  * optional F3 bullpen rest with PM-1289's conservative interval treatment;
  * qualitative Low / Moderate / High assessment confidence with downward-only caps;
  * NO_SELECTION with balanced_observed_evidence vs optional_evidence_uncertainty;
  * INSUFFICIENT_EVIDENCE on required-factor / presence-gate failure;
  * neutral quoted-price context (no implied probability / EV / value judgment);
  * explicit tz-aware as_of with future-evidence exclusion; no wall-clock read;
  * official_status = NOT_EVALUATED.

stdlib only. No DB, no network, no clock. Parameters are the PM-1299-ratified
PROVISIONAL v0 baseline (starting method, not calibrated/validated).

Exact decimal arithmetic (Decimal, half-up to 4 dp) is used at the contract's
rounding points so the 0.10 / 0.25 / 0.45 boundaries do not drift on float noise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

MODEL_VERSION = "ml-eval-v0"

# --- Ratified provisional v0 parameters (PM-1299; unchanged from PM-1287/1289) ---
W1, W2, W3 = Decimal("0.50"), Decimal("0.35"), Decimal("0.15")
K1, K2 = Decimal("2.00"), Decimal("1.50")
T_SELECT = Decimal("0.10")
BAND_LOW_LO = Decimal("0.10")   # Low  [0.10, 0.25)
BAND_MOD_LO = Decimal("0.25")   # Mod  [0.25, 0.45)
BAND_HIGH_LO = Decimal("0.45")  # High [0.45, 1.00]
MIN_IP = Decimal("20.0")
MIN_GAMES = 20
ERA_LO, ERA_HI = Decimal("0"), Decimal("20")
RPG_LO, RPG_HI = Decimal("0"), Decimal("15")
REST_LO, REST_HI = Decimal("0"), Decimal("1")
QUOTE_MAX_AGE = timedelta(hours=24)  # inclusive 0..24h eligible (PM-1289 §5)
_Q = Decimal("0.0001")
_IP_TOL = Decimal("0.01")           # tolerance for true-innings fractional parts
_TRUE_IP_FRACS = (Decimal("0"), Decimal("0.3333"), Decimal("0.6667"))

# --- Vocabulary ---------------------------------------------------------------
OBSERVED_FULL = "OBSERVED_FULL"
PARTIAL = "PARTIAL"
UNAVAILABLE = "UNAVAILABLE"

ASSESSED = "ASSESSED"
NO_SELECTION = "NO_SELECTION"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

REASON_BALANCED_OBSERVED = "balanced_observed_evidence"
REASON_OPTIONAL_UNCERTAINTY = "optional_evidence_uncertainty"
MISSINGNESS_F3_RESERVED = "f3_missing_conservative_reserved"

LOW, MODERATE, HIGH = "Low", "Moderate", "High"
_BAND_RANK = {None: 0, LOW: 1, MODERATE: 2, HIGH: 3}
_RANK_BAND = {1: LOW, 2: MODERATE, 3: HIGH}

OFFICIAL_STATUS = "NOT_EVALUATED — not an official paper bet"
MARKET_ML = "ML"

# Quote statuses (PM-1287 §E + PM-1289 §5 adds FUTURE)
Q_PRESENT = "PRESENT"
Q_ABSENT = "ABSENT"
Q_MALFORMED = "MALFORMED"
Q_STALE = "STALE"
Q_CONTRADICTORY = "CONTRADICTORY"
Q_FUTURE = "FUTURE"

HOME, AWAY = "home", "away"


class MoneylineEvaluatorError(ValueError):
    """Raised when a required *input contract* is violated (e.g. naive as_of)."""


# --- Decimal helpers ----------------------------------------------------------

def _dec(x) -> Decimal:
    # str() first so float inputs (e.g. 4.90) become clean decimals, not 4.9000000000000004.
    return x if isinstance(x, Decimal) else Decimal(str(x))


def q4(x) -> Decimal:
    """Half-up (ties away from zero) round to four decimals."""
    return _dec(x).quantize(_Q, rounding=ROUND_HALF_UP)


def _clamp(x: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    return max(lo, min(hi, x))


def _is_tz_aware(dt) -> bool:
    return isinstance(dt, datetime) and dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None


def _is_number(x) -> bool:
    # bool is an int subclass; reject it as a numeric factor input.
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


# --- Dataclasses --------------------------------------------------------------

@dataclass(frozen=True)
class MoneylineInputs:
    source_namespace: str
    sport_id: int
    game_pk: str
    home_team: str
    away_team: str
    # F1 (required)
    home_sp_era: float | None = None
    away_sp_era: float | None = None
    home_sp_ip: float | None = None
    away_sp_ip: float | None = None
    # F2 (required)
    home_off_rpg: float | None = None
    away_off_rpg: float | None = None
    home_off_games: int | None = None
    away_off_games: int | None = None
    # F3 (optional)
    home_bp_rest: float | None = None
    away_bp_rest: float | None = None
    # presence gate + readiness (defaults match the contract's "unless noted" baseline)
    home_probable_present: bool = True
    away_probable_present: bool = True
    home_lineup_status: str = OBSERVED_FULL
    away_lineup_status: str = OBSERVED_FULL
    # optional per-factor evidence observation times (tz-aware) for future-exclusion
    f1_observed_at: datetime | None = None
    f2_observed_at: datetime | None = None
    f3_observed_at: datetime | None = None
    # identity / timing carried through
    game_run_id: str | None = None
    scheduled_start_at: datetime | None = None

    def sui(self) -> tuple[str, int, str]:
        return (self.source_namespace, self.sport_id, str(self.game_pk))

    def sui_string(self) -> str:
        # Canonical form identical to underlying_identity.sui_string (kept local to
        # keep this module self-contained per the four-file scope).
        return f"{self.source_namespace}:{self.sport_id}:{self.game_pk}"


@dataclass(frozen=True)
class QuoteContext:
    game_pk: str
    side: str
    american_odds: int
    observed_at: datetime
    sportsbook: str | None = None
    jurisdiction: str | None = None
    provenance: str | None = None
    market: str = MARKET_ML


@dataclass(frozen=True)
class QuoteResolution:
    status: str
    side: str | None = None
    american_odds: int | None = None
    sportsbook: str | None = None
    jurisdiction: str | None = None
    observed_at: datetime | None = None
    provenance: str | None = None
    market: str = MARKET_ML
    # Quotes for a non-selected side, carried as neutral context only (never a recommendation).
    carried_context: tuple = ()


@dataclass(frozen=True)
class FactorReport:
    factor_id: str
    present: bool
    valid: bool
    score: float | None = None
    weight: float | None = None
    contribution: float | None = None
    detail: str | None = None


@dataclass(frozen=True)
class MoneylineAssessment:
    game_pk: str
    source_namespace: str
    sport_id: int
    sui_string: str
    game_run_id: str | None
    home_team: str
    away_team: str
    scheduled_start_at: datetime | None
    as_of_time: datetime
    analysis_state: str
    directional_selection: str | None
    assessment_confidence: str | None
    no_selection_reason: str | None
    aggregate_score: float | None
    directional_margin: float | None
    coverage: float | None
    readiness: dict
    supporting_factors: tuple
    counterarguments: tuple
    missing_or_invalid_inputs: tuple
    missingness_treatment: str | None
    confidence_explanation: str
    quote_context: QuoteResolution
    method_version: str = MODEL_VERSION
    official_status: str = OFFICIAL_STATUS

    def sui(self) -> tuple[str, int, str]:
        return (self.source_namespace, self.sport_id, str(self.game_pk))


# --- Factor validation & scoring ---------------------------------------------

def _ip_is_true_innings(ip) -> bool:
    """True only for a numeric true-innings value; a .1/.2 display token fails closed."""
    if not _is_number(ip):
        return False
    d = _dec(ip)
    if d < 0:
        return False
    frac = d - int(d)
    return any(abs(frac - ok) <= _IP_TOL for ok in _TRUE_IP_FRACS)


def _era_valid(era, ip) -> bool:
    if not (_is_number(era) and _is_number(ip)):
        return False
    if not (ERA_LO <= _dec(era) <= ERA_HI):
        return False
    if not _ip_is_true_innings(ip):
        return False
    return _dec(ip) >= MIN_IP


def _off_valid(rpg, games) -> bool:
    if not _is_number(rpg):
        return False
    if isinstance(games, bool) or not isinstance(games, int):
        return False
    if not (RPG_LO <= _dec(rpg) <= RPG_HI):
        return False
    return games >= MIN_GAMES


def _rest_valid(home_rest, away_rest) -> bool:
    if not (_is_number(home_rest) and _is_number(away_rest)):
        return False
    return (REST_LO <= _dec(home_rest) <= REST_HI) and (REST_LO <= _dec(away_rest) <= REST_HI)


def _future_or_naive(observed_at, as_of) -> str | None:
    """Return 'naive'/'future' if the evidence timestamp disqualifies its factor, else None."""
    if observed_at is None:
        return None
    if not _is_tz_aware(observed_at):
        return "naive"
    if observed_at > as_of:
        return "future"
    return None


def _s1(inp: MoneylineInputs) -> Decimal:
    raw = (_dec(inp.away_sp_era) - _dec(inp.home_sp_era)) / K1  # lower ERA favors that side
    return q4(_clamp(raw, Decimal("-1"), Decimal("1")))


def _s2(inp: MoneylineInputs) -> Decimal:
    raw = (_dec(inp.home_off_rpg) - _dec(inp.away_off_rpg)) / K2  # higher rpg favors that side
    return q4(_clamp(raw, Decimal("-1"), Decimal("1")))


def _s3(inp: MoneylineInputs) -> Decimal:
    raw = _dec(inp.home_bp_rest) - _dec(inp.away_bp_rest)
    return q4(_clamp(raw, Decimal("-1"), Decimal("1")))


# --- Confidence ---------------------------------------------------------------

def _base_band(margin: Decimal) -> str:
    if BAND_HIGH_LO <= margin:
        return HIGH
    if BAND_MOD_LO <= margin < BAND_HIGH_LO:
        return MODERATE
    return LOW  # margin in [0.10, 0.25); callers only ask when a selection exists


def _apply_caps(base: str, coverage: Decimal, lineup_ok: bool, at_min_sample: bool) -> tuple[str, list[str]]:
    cap_rank = 3  # High
    caps = []
    if coverage < Decimal("1.00"):
        cap_rank = min(cap_rank, 2)
        caps.append("coverage<1.00")
    if not lineup_ok:
        cap_rank = min(cap_rank, 2)
        caps.append("lineup_not_OBSERVED_FULL")
    if at_min_sample:
        cap_rank = min(cap_rank, 2)
        caps.append("at_minimum_sample")
    displayed_rank = min(_BAND_RANK[base], cap_rank)
    return _RANK_BAND[displayed_rank], caps


# --- Quote resolution ---------------------------------------------------------

def _quote_valid(q: QuoteContext) -> bool:
    if not (type(q.american_odds) is int and abs(q.american_odds) >= 100):  # bool rejected by type check
        return False
    if not _is_tz_aware(q.observed_at):
        return False
    if q.market != MARKET_ML:
        return False
    if q.side not in (HOME, AWAY):
        return False
    return True


def _resolve_quotes(quotes, selected_side, game_pk, as_of) -> QuoteResolution:
    if not quotes:
        return QuoteResolution(status=Q_ABSENT)
    matching = [q for q in quotes if str(q.game_pk) == str(game_pk) and q.market == MARKET_ML]
    if not matching:
        return QuoteResolution(status=Q_ABSENT)
    carried = tuple(
        {"side": q.side, "american_odds": q.american_odds, "sportsbook": q.sportsbook,
         "jurisdiction": q.jurisdiction, "observed_at": q.observed_at, "provenance": q.provenance}
        for q in matching if q.side != selected_side
    )
    if selected_side is None:
        # No directional selection => nothing bindable to a recommendation.
        return QuoteResolution(status=Q_ABSENT, carried_context=carried)
    side_quotes = [q for q in matching if q.side == selected_side]
    if not side_quotes:
        return QuoteResolution(status=Q_ABSENT, carried_context=carried)
    # Distinct quotes for the same game+side+market => contradictory, attach none.
    distinct = {(q.american_odds, q.observed_at, q.sportsbook, q.jurisdiction) for q in side_quotes}
    if len(distinct) > 1:
        return QuoteResolution(status=Q_CONTRADICTORY, side=selected_side, carried_context=carried)
    q = side_quotes[0]
    if not _quote_valid(q):
        return QuoteResolution(status=Q_MALFORMED, side=selected_side, carried_context=carried)
    if q.observed_at > as_of:
        status = Q_FUTURE
    elif (as_of - q.observed_at) > QUOTE_MAX_AGE:
        status = Q_STALE
    else:
        status = Q_PRESENT
    return QuoteResolution(
        status=status, side=selected_side, american_odds=q.american_odds, sportsbook=q.sportsbook,
        jurisdiction=q.jurisdiction, observed_at=q.observed_at, provenance=q.provenance,
        market=MARKET_ML, carried_context=carried,
    )


# --- Evaluate -----------------------------------------------------------------

def evaluate(inputs: MoneylineInputs, as_of_time: datetime, quote_context=None) -> MoneylineAssessment:
    """Evaluate one game from supplied inputs. Pure/deterministic; reads no clock."""
    if not _is_tz_aware(as_of_time):
        raise MoneylineEvaluatorError("as_of_time is required and must be timezone-aware")

    quotes = None
    if quote_context is not None:
        quotes = list(quote_context) if isinstance(quote_context, (list, tuple)) else [quote_context]

    missing: list[str] = []

    # Future/naive evidence exclusion BEFORE validity checks (contract §F).
    f1_ex = _future_or_naive(inputs.f1_observed_at, as_of_time)
    f2_ex = _future_or_naive(inputs.f2_observed_at, as_of_time)
    f3_ex = _future_or_naive(inputs.f3_observed_at, as_of_time)
    if f1_ex:
        missing.append(f"F1_excluded_{f1_ex}_evidence")
    if f2_ex:
        missing.append(f"F2_excluded_{f2_ex}_evidence")

    f1_ok = (f1_ex is None) and _era_valid(inputs.home_sp_era, inputs.home_sp_ip) \
        and _era_valid(inputs.away_sp_era, inputs.away_sp_ip)
    f2_ok = (f2_ex is None) and _off_valid(inputs.home_off_rpg, inputs.home_off_games) \
        and _off_valid(inputs.away_off_rpg, inputs.away_off_games)

    presence_ok = bool(inputs.home_probable_present and inputs.away_probable_present)
    if not inputs.home_probable_present:
        missing.append("home_probable_starter")
    if not inputs.away_probable_present:
        missing.append("away_probable_starter")
    if not f1_ok and f1_ex is None:
        missing.append("F1_starting_pitcher_run_prevention")
    if not f2_ok and f2_ex is None:
        missing.append("F2_team_offense")

    lineup_ok = (inputs.home_lineup_status == OBSERVED_FULL and inputs.away_lineup_status == OBSERVED_FULL)
    readiness = {
        "F1_present_valid": f1_ok,
        "F2_present_valid": f2_ok,
        "F3_present_valid": None,  # set below
        "home_probable_present": inputs.home_probable_present,
        "away_probable_present": inputs.away_probable_present,
        "home_lineup_status": inputs.home_lineup_status,
        "away_lineup_status": inputs.away_lineup_status,
        "lineup_ok": lineup_ok,
    }

    # Required-factor / presence-gate precedence => INSUFFICIENT_EVIDENCE.
    if not (presence_ok and f1_ok and f2_ok):
        readiness["F3_present_valid"] = False
        return MoneylineAssessment(
            game_pk=str(inputs.game_pk), source_namespace=inputs.source_namespace,
            sport_id=inputs.sport_id, sui_string=inputs.sui_string(), game_run_id=inputs.game_run_id,
            home_team=inputs.home_team, away_team=inputs.away_team,
            scheduled_start_at=inputs.scheduled_start_at, as_of_time=as_of_time,
            analysis_state=INSUFFICIENT_EVIDENCE, directional_selection=None,
            assessment_confidence=None, no_selection_reason=None,
            aggregate_score=None, directional_margin=None, coverage=None,
            readiness=readiness, supporting_factors=(),
            counterarguments=("insufficient_required_evidence",),
            missing_or_invalid_inputs=tuple(missing),
            missingness_treatment=None,
            confidence_explanation="Insufficient required evidence: " + ", ".join(missing) + ".",
            quote_context=_resolve_quotes(quotes, None, inputs.game_pk, as_of_time),
        )

    s1 = _s1(inputs)
    s2 = _s2(inputs)
    b = W1 * s1 + W2 * s2  # exact decimal (not yet rounded)

    f3_present = (f3_ex is None) and _rest_valid(inputs.home_bp_rest, inputs.away_bp_rest)
    readiness["F3_present_valid"] = f3_present
    at_min_sample = (
        _dec(inputs.home_sp_ip) == MIN_IP or _dec(inputs.away_sp_ip) == MIN_IP
        or inputs.home_off_games == MIN_GAMES or inputs.away_off_games == MIN_GAMES
    )

    missingness_treatment = None
    if f3_present:
        s3 = _s3(inputs)
        a = q4(b + W3 * s3)
        signed = a
        margin = abs(a)
        coverage = Decimal("1.00")
    else:
        if inputs.home_bp_rest is not None or inputs.away_bp_rest is not None or f3_ex is not None:
            # F3 was supplied but invalid / future / naive -> treated absent (named).
            missing.append("F3_bullpen_rest" + (f"_{f3_ex}" if f3_ex else "_invalid"))
        else:
            missing.append("F3_bullpen_rest_absent")
        s3 = None
        lo = q4(b - W3)
        up = q4(b + W3)
        if lo > 0:
            d = lo
        elif up < 0:
            d = up
        else:
            d = Decimal("0.0000")
        signed = d
        margin = abs(d)
        coverage = Decimal("0.85")
        missingness_treatment = MISSINGNESS_F3_RESERVED

    supporting: list[dict] = []
    counter: list[dict] = []
    contrib = {"F1": (W1, s1), "F2": (W2, s2)}
    if f3_present:
        contrib["F3"] = (W3, s3)

    # --- Selection & confidence ---
    if margin < T_SELECT:
        selection = None
        band = None
        if f3_present:
            reason = REASON_BALANCED_OBSERVED
        else:
            reason = REASON_OPTIONAL_UNCERTAINTY
        state = NO_SELECTION
        for fid, (w, s) in contrib.items():
            counter.append({"factor": fid, "score": float(s), "weight": float(w)})
        if not f3_present:
            counter.append({"factor": "F3", "note": "missing_conservative_reserved"})
        expl = ("Complete required evidence but no directional lean at the "
                f"{float(T_SELECT):.2f} threshold (margin {float(margin):.4f}); reason={reason}.")
    else:
        selection = HOME if signed > 0 else AWAY
        band_base = _base_band(margin)
        band, caps = _apply_caps(band_base, coverage, lineup_ok, at_min_sample)
        state = ASSESSED
        reason = None
        sel_sign = 1 if selection == HOME else -1
        for fid, (w, s) in contrib.items():
            c = float(w * s)
            rec = {"factor": fid, "score": float(s), "weight": float(w), "contribution": c}
            if (s > 0 and sel_sign > 0) or (s < 0 and sel_sign < 0):
                supporting.append(rec)
            elif s == 0:
                counter.append({**rec, "note": "neutral"})
            else:
                counter.append(rec)
        if not f3_present:
            counter.append({"factor": "F3", "note": "missing_conservative_reserved_counts_against_lean"})
        cap_txt = (" capped to " + band + " (" + ", ".join(caps) + ")") if caps and band != band_base else ""
        expl = (f"Directional lean to {selection}; base band {band_base} on margin "
                f"{float(margin):.4f}{cap_txt}. Coverage {float(coverage):.2f}. "
                "Qualitative assessment strength only — not a win probability or price-qualified confidence.")

    return MoneylineAssessment(
        game_pk=str(inputs.game_pk), source_namespace=inputs.source_namespace,
        sport_id=inputs.sport_id, sui_string=inputs.sui_string(), game_run_id=inputs.game_run_id,
        home_team=inputs.home_team, away_team=inputs.away_team,
        scheduled_start_at=inputs.scheduled_start_at, as_of_time=as_of_time,
        analysis_state=state, directional_selection=selection, assessment_confidence=band,
        no_selection_reason=reason, aggregate_score=float(signed),
        directional_margin=float(margin), coverage=float(coverage), readiness=readiness,
        supporting_factors=tuple(supporting), counterarguments=tuple(counter),
        missing_or_invalid_inputs=tuple(missing), missingness_treatment=missingness_treatment,
        confidence_explanation=expl,
        quote_context=_resolve_quotes(quotes, selection, inputs.game_pk, as_of_time),
    )
