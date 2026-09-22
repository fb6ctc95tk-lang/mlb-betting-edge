"""backend.oracle.bullpen_rest — ratified M1 bullpen-rest F3 calculator.

Pure, deterministic, stdlib-only. Converts EXPLICITLY SUPPLIED 2024 MLB
regular-season relief-workload evidence into the optional F3 inputs
(``home_bp_rest``, ``away_bp_rest``, ``f3_observed_at``) consumed by the accepted
Moneyline Evaluator v0. Implements the M1 policy Rich ratified in PM-1324
(proposal PM-1323).

Ratified M1 (provisional / uncalibrated):
  * meaning: team recent-relief-outs REST proxy only — NOT reliever availability,
    injuries, bullpen quality/depth/leverage, physiological fatigue, probability,
    or betting edge;
  * domain: 2024 MLB regular season (sport_id == 1);
  * window: the three preceding America/Toronto calendar dates (A-1, A-2, A-3);
    NOT a rolling 72h and NOT "the last three games";
  * workload: integer relief OUTS; relief role iff ``games_started == 0``
    (openers recorded as starters are excluded; bulk relievers and position-player
    relief are counted by that same rule);
  * CAP = 45 outs (= 15.0 innings), a provisional engineering baseline;
  * R_team = clamp(1 - W_team / 45, 0, 1), quantized ONCE to 4dp ROUND_HALF_UP;
  * both teams must have complete required evidence before observed F3 is supplied;
  * a positively established EMPTY window yields W=0, R=1; every partial / missing /
    malformed / conflicting / temporally-unresolved required evidence leaves F3
    MISSING (both None) — missing is never zero.

Boundaries: consumes supplied records + evidence metadata only (fetches nothing;
no clock/network/DB/filesystem/env); does not import or run the evaluator, ranking,
stages, adapters, or scheduler; caller-supplied evidence is NOT treated as
independently authenticated. The accepted F3 interface and PM-1289 missingness
behavior are unchanged and are not reimplemented here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, localcontext

# --- Ratified constants -------------------------------------------------------
CAP_OUTS = 45                      # provisional, uncalibrated engineering baseline
CAP_INNINGS = Decimal("15.0")      # 45 outs / 3
K_DAYS = 3                         # three preceding Toronto calendar dates
SPORT_ID_MLB = 1
# Ratified M1 domain (PM-1324): 2024 MLB-StatsAPI regular season only.
RATIFIED_SOURCE_NAMESPACE = "mlb-statsapi"
RATIFIED_GAME_TYPE = "R"           # regular season
RATIFIED_SEASON = 2024
REST_LO, REST_HI = Decimal("0"), Decimal("1")
_Q = Decimal("0.0001")             # 4-dp quantum, matches the evaluator's grid

# --- Deterministic missingness reason codes -----------------------------------
R_INVENTORY_UNRESOLVED = "inventory_unresolved"
R_TEMPORAL_UNRESOLVED = "temporal_attribution_unresolved"
R_NO_USABLE_WORKLOAD = "expected_game_no_usable_workload"
R_MALFORMED_EVIDENCE = "malformed_evidence"
R_CONFLICTING_EVIDENCE = "conflicting_evidence"
R_MISSING_COMPLETION = "missing_completion_evidence"
R_COMPLETION_NOT_BEFORE_ASOF = "completion_not_before_as_of"
R_OUT_OF_DOMAIN = "out_of_domain"

ASSUMPTION_LABEL = (
    "historical_boxscore_availability_ASSUMED (qualified-2024 research; "
    "completion-time proxy; NOT authenticated publication)"
)


class BullpenRestError(ValueError):
    """Raised when a *structural* input contract is violated (e.g. naive as_of)."""


# --- Timezone: America/Toronto (US/Canada Eastern DST) ------------------------
#
# zoneinfo is preferred when an IANA database is present; otherwise a stdlib
# fallback computes US Eastern DST transitions (2nd Sunday of March 02:00 local ->
# 1st Sunday of November 02:00 local) for the datetime's own year. For 2024 this
# reproduces the exact accepted transitions (EDT 2024-03-10 07:00Z .. 2024-11-03
# 06:00Z). The timezone layer determines only the local *date*; the ratified
# DOMAIN restriction to season 2024 is enforced separately in the public
# validation path (compute_bullpen_rest), independently of the timezone backend.
# No universal timezone support is claimed.

try:  # pragma: no cover - environment dependent
    from zoneinfo import ZoneInfo

    _TORONTO_ZONE = ZoneInfo("America/Toronto")
    TZ_MECHANISM = "zoneinfo:America/Toronto"
except Exception:  # ZoneInfoNotFoundError or import error -> stdlib fallback
    _TORONTO_ZONE = None
    TZ_MECHANISM = "stdlib-fallback:America/Toronto(US-DST-rule)"


def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    first_sun = 1 + (6 - first.weekday()) % 7      # weekday(): Mon=0 .. Sun=6
    return date(year, month, first_sun + (n - 1) * 7)


def _eastern_offset_hours(utc: datetime) -> int:
    """US Eastern UTC offset (-4 EDT / -5 EST) for a UTC instant, any year."""
    y = utc.year
    edt_start = datetime(y, 3, _nth_sunday(y, 3, 2).day, 7, 0, tzinfo=timezone.utc)   # 2:00 EST -> 07:00Z
    edt_end = datetime(y, 11, _nth_sunday(y, 11, 1).day, 6, 0, tzinfo=timezone.utc)   # 2:00 EDT -> 06:00Z
    return -4 if (edt_start <= utc < edt_end) else -5


def _toronto_date(dt_aware: datetime) -> date:
    """Toronto local calendar date of a timezone-aware datetime (any year)."""
    if not (isinstance(dt_aware, datetime) and dt_aware.tzinfo is not None
            and dt_aware.tzinfo.utcoffset(dt_aware) is not None):
        raise BullpenRestError("as_of/completion time must be timezone-aware")
    if _TORONTO_ZONE is not None:  # pragma: no cover - environment dependent
        return dt_aware.astimezone(_TORONTO_ZONE).date()
    utc = dt_aware.astimezone(timezone.utc)
    return (utc + timedelta(hours=_eastern_offset_hours(utc))).date()


def _window_dates(as_of: datetime) -> tuple[str, str, str]:
    """The three preceding Toronto calendar dates {A-1, A-2, A-3} as ISO strings."""
    a = _toronto_date(as_of)
    return tuple((a - timedelta(days=i)).isoformat() for i in range(1, K_DAYS + 1))


# --- Numeric helpers ----------------------------------------------------------

def _is_int(x) -> bool:
    """True only for a genuine int; a bool is rejected (bool is an int subclass)."""
    return isinstance(x, int) and not isinstance(x, bool)


def rest_from_outs(w: int) -> Decimal:
    """R = clamp(1 - W/45, 0, 1), quantized to 4dp HALF_UP.

    Independent of ambient decimal context: the division runs in a local context
    with fixed precision, then a single explicit HALF_UP quantization is applied.
    """
    if not _is_int(w) or w < 0:
        raise BullpenRestError(f"workload outs must be a non-negative int, got {w!r}")
    with localcontext() as ctx:
        ctx.prec = 34
        r = (Decimal(CAP_OUTS) - Decimal(w)) / Decimal(CAP_OUTS)
        r = max(REST_LO, min(REST_HI, r))
        return r.quantize(_Q, rounding=ROUND_HALF_UP)


# --- Supplied-evidence types --------------------------------------------------

@dataclass(frozen=True)
class DomainAssertion:
    """The ratified-domain assertion carried by the request (and, optionally, by
    required records for contradiction detection). This is a *structural* assertion
    of supplied fields — NOT external authentication of the game's identity.
    """
    source_namespace: str
    sport_id: object
    game_type: str
    season: object

    def is_ratified(self) -> bool:
        # genuine ints only (a bool must not pass as a sport/season identifier)
        return (self.source_namespace == RATIFIED_SOURCE_NAMESPACE
                and _is_int(self.sport_id) and self.sport_id == SPORT_ID_MLB
                and self.game_type == RATIFIED_GAME_TYPE
                and _is_int(self.season) and self.season == RATIFIED_SEASON)

    def key(self) -> tuple:
        return (self.source_namespace, self.sport_id, self.game_type, self.season)


@dataclass(frozen=True)
class PitchingLine:
    """One pitcher's line in a game (as supplied). ``games_started``/``outs`` are
    validated as genuine ints; role is relief iff ``games_started == 0``."""
    player_id: str
    games_started: object
    outs: object


@dataclass(frozen=True)
class WorkloadObservation:
    """A supplied per-game, per-team workload record from one source.

    ``source`` is the workload provenance; ``retrieval_provenance`` is the actual
    (modern) retrieval provenance kept SEPARATE from event/availability semantics.
    Multiple observations for the same (game_pk, team_id) are reconciled: identical
    contract projection -> counted once; material disagreement -> fail closed.
    """
    game_pk: str
    team_id: str
    pitching_lines: tuple
    source: str
    retrieval_provenance: str | None = None


@dataclass(frozen=True)
class ExpectedGame:
    """A game the caller's ESTABLISHED inventory says the team played, with its
    caller-attributed Toronto ``local_date`` and completion evidence. ``local_date``
    and ``attribution_resolved`` are caller-provided facts, not module-authenticated.
    """
    game_pk: str
    local_date: str                     # caller-attributed Toronto calendar date
    completion_utc: datetime | None = None
    attribution_resolved: bool = True   # False for unresolved suspended/resumed
    domain: "DomainAssertion | None" = None   # if set, must match the request domain


@dataclass(frozen=True)
class TeamWindowEvidence:
    team_id: str
    inventory_established: bool
    expected_games: tuple = ()          # of ExpectedGame (any dates; module windows)
    observations: tuple = ()            # of WorkloadObservation


@dataclass(frozen=True)
class BullpenRestRequest:
    as_of: datetime                     # timezone-aware
    target_game_pk: str
    home: TeamWindowEvidence
    away: TeamWindowEvidence
    domain: DomainAssertion             # REQUIRED ratified-domain assertion (no default)
    historical_availability_assumed: bool = True


# --- Results ------------------------------------------------------------------

@dataclass(frozen=True)
class TeamRest:
    team_id: str
    supplied: bool
    rest: Decimal | None
    rest_value: float | None            # evaluator-compatible numeric representation
    workload_outs: int | None
    included_game_pks: tuple
    used_sources: tuple                 # (game_pk, source) provenance actually used
    missing_reasons: tuple


@dataclass(frozen=True)
class F3Result:
    home_bp_rest: float | None
    away_bp_rest: float | None
    f3_observed_at: datetime | None
    f3_present: bool
    home: TeamRest
    away: TeamRest
    window_dates: tuple
    as_of: datetime
    tz_mechanism: str
    assumption: str
    notes: tuple = ()

    def to_evaluator_inputs(self) -> dict:
        """The exact kwargs to hand the accepted evaluator's MoneylineInputs.

        When F3 is missing, BOTH sides are None (the accepted missing-F3
        representation) and f3_observed_at is None; the evaluator then applies its
        unchanged PM-1289 conservative interval. This module never runs the evaluator.
        """
        return {
            "home_bp_rest": self.home_bp_rest,
            "away_bp_rest": self.away_bp_rest,
            "f3_observed_at": self.f3_observed_at,
        }


# --- Core -------------------------------------------------------------------

def _line_role_and_outs(line: PitchingLine):
    """Return (is_relief, outs, ok). ok=False if role/outs are malformed for use.

    Role must be a genuine int; relief iff 0. For a relief line, outs must be a
    genuine non-negative int (zero is a valid observed value). A starter's outs are
    not required. Role is never inferred from list order.
    """
    gs = line.games_started
    if not _is_int(gs):
        return (None, None, False)          # malformed role
    if gs == 0:                             # relief appearance
        o = line.outs
        if not _is_int(o) or o < 0:
            return (True, None, False)      # malformed / missing / negative outs
        return (True, o, True)
    return (False, None, True)              # starter (incl. opener): excluded, ok


def _observation_projection(obs: WorkloadObservation):
    """Canonical fingerprint + relief-outs total for one observation.

    Returns (fingerprint, relief_outs, ok). The contract is ONE aggregate pitching
    line per player: a REPEATED player_id within a single observation is malformed
    (ok=False). This closes PM-1327 defect 1 — without it a duplicated identical row
    summed to twice the workload yet collapsed to the same set-fingerprint as a single
    row, so input order silently changed the result. The fingerprint is the
    order-independent *sorted tuple* of (player_id, games_started, outs) over all
    lines, aligned 1:1 with the content used to compute workload (unique players):
    identical recorded roles/outs are compatible regardless of source/provenance, and
    any role/outs disagreement is a material conflict.
    """
    fp = []
    relief_outs = 0
    seen_players = set()
    for line in obs.pitching_lines:
        if line.player_id in seen_players:
            return (None, None, False)          # repeated player id -> malformed
        seen_players.add(line.player_id)
        is_relief, outs, ok = _line_role_and_outs(line)
        if not ok:
            return (None, None, False)
        fp.append((line.player_id, line.games_started, line.outs))
        if is_relief:
            relief_outs += outs
    fp.sort(key=lambda t: (str(t[0]), str(t[1]), str(t[2])))
    return (tuple(fp), relief_outs, True)


def _game_relief_outs(game_pk: str, team_id: str, observations):
    """Reconcile all observations for one (game_pk, team_id).

    Returns (relief_outs, source, status). status is one of 'ok', 'malformed',
    'conflict', 'absent'. Order-independent and idempotent to duplicates: a later
    identical copy changes nothing; a later conflicting copy cannot restore a group.
    """
    matches = [o for o in observations if o.game_pk == game_pk and o.team_id == team_id]
    if not matches:
        return (None, None, "absent")
    fingerprints = {}
    for o in matches:
        fp, relief_outs, ok = _observation_projection(o)
        if not ok:
            return (None, None, "malformed")     # malformed evidence fails closed
        fingerprints.setdefault(fp, (relief_outs, o.source))
    if len(fingerprints) > 1:
        return (None, None, "conflict")          # material disagreement fails closed
    (relief_outs, source), = fingerprints.values()
    return (relief_outs, source, "ok")


def _compute_team(team: TeamWindowEvidence, window: tuple, as_of: datetime,
                  target_game_pk: str, domain: DomainAssertion) -> tuple:
    """Return (TeamRest, latest_completion_utc_or_None)."""
    reasons: list[str] = []
    window_set = set(window)

    # In-window expected games (caller-attributed dates); exclude target & same-day A.
    in_window = [g for g in team.expected_games
                 if g.local_date in window_set and g.game_pk != target_game_pk]

    if not team.inventory_established:
        reasons.append(R_INVENTORY_UNRESOLVED)
        return (TeamRest(team.team_id, False, None, None, None, (), (), tuple(reasons)), None)

    total_outs = 0
    included: list[str] = []
    used_sources: list[tuple] = []
    latest_completion = None

    # deterministic order for reproducibility (sum is order-independent regardless)
    for g in sorted(in_window, key=lambda x: (x.local_date, str(x.game_pk))):
        # a required record carrying contradictory domain info fails closed; it is
        # NOT dropped so the inventory cannot be declared complete/empty around it.
        if g.domain is not None and g.domain.key() != domain.key():
            reasons.append(f"{R_OUT_OF_DOMAIN}:{g.game_pk}")
            continue
        if not g.attribution_resolved:
            reasons.append(f"{R_TEMPORAL_UNRESOLVED}:{g.game_pk}")
            continue
        if g.completion_utc is None:
            reasons.append(f"{R_MISSING_COMPLETION}:{g.game_pk}")
            continue
        if not (isinstance(g.completion_utc, datetime) and g.completion_utc.tzinfo is not None
                and g.completion_utc.tzinfo.utcoffset(g.completion_utc) is not None):
            raise BullpenRestError(f"completion_utc for {g.game_pk} must be timezone-aware")
        if g.completion_utc > as_of:
            reasons.append(f"{R_COMPLETION_NOT_BEFORE_ASOF}:{g.game_pk}")
            continue
        relief_outs, source, status = _game_relief_outs(g.game_pk, team.team_id, team.observations)
        if status == "ok":
            total_outs += relief_outs
            included.append(g.game_pk)
            used_sources.append((g.game_pk, source))
            uc = g.completion_utc.astimezone(timezone.utc)
            latest_completion = uc if latest_completion is None else max(latest_completion, uc)
        elif status == "absent":
            reasons.append(f"{R_NO_USABLE_WORKLOAD}:{g.game_pk}")
        elif status == "malformed":
            reasons.append(f"{R_MALFORMED_EVIDENCE}:{g.game_pk}")
        elif status == "conflict":
            reasons.append(f"{R_CONFLICTING_EVIDENCE}:{g.game_pk}")

    if reasons:
        return (TeamRest(team.team_id, False, None, None, None, (), (), tuple(sorted(reasons))), None)

    # complete: either a nonempty fully-covered window or a positively established empty one
    r = rest_from_outs(total_outs)
    return (
        TeamRest(team.team_id, True, r, float(r), total_outs,
                 tuple(included), tuple(used_sources), ()),
        latest_completion,
    )


def compute_bullpen_rest(request: BullpenRestRequest) -> F3Result:
    """Compute the ratified M1 F3 pair from supplied evidence. Pure/deterministic.

    Supplies observed F3 only when BOTH teams are complete; otherwise both sides are
    None with deterministic per-team missingness reasons (the accepted missing-F3
    representation). Reads no clock, network, DB, filesystem, or environment.
    """
    if not (isinstance(request.as_of, datetime) and request.as_of.tzinfo is not None
            and request.as_of.tzinfo.utcoffset(request.as_of) is not None):
        raise BullpenRestError("as_of is required and must be timezone-aware")

    notes: list[str] = []
    a_date = _toronto_date(request.as_of)          # Toronto calendar date (any tz backend)
    window = _window_dates(request.as_of)

    # Ratified-domain enforcement in the public path, independent of the timezone
    # backend: structural namespace/sport/game_type/season assertion + the TARGET's
    # Toronto-calendar year matching the asserted season. Fails closed (no observed F3).
    domain = request.domain
    domain_ok = isinstance(domain, DomainAssertion) and domain.is_ratified()
    target_year_ok = domain_ok and (a_date.year == domain.season)
    if not (domain_ok and target_year_ok):
        reasons = (R_OUT_OF_DOMAIN,)
        home = TeamRest(request.home.team_id, False, None, None, None, (), (), reasons)
        away = TeamRest(request.away.team_id, False, None, None, None, (), (), reasons)
        note = "out_of_domain_assertion" if not domain_ok else "out_of_domain_target_year"
        return F3Result(None, None, None, False, home, away, window, request.as_of,
                        TZ_MECHANISM, ASSUMPTION_LABEL, (note,))

    home, hc = _compute_team(request.home, window, request.as_of, request.target_game_pk, domain)
    away, ac = _compute_team(request.away, window, request.as_of, request.target_game_pk, domain)

    if home.supplied and away.supplied:
        completions = [c for c in (hc, ac) if c is not None]
        f3_observed_at = max(completions) if completions else None  # None for fully-empty window
        if request.historical_availability_assumed:
            notes.append(ASSUMPTION_LABEL)
        if f3_observed_at is None:
            notes.append("empty_window_no_completion_timestamp")
        return F3Result(home.rest_value, away.rest_value, f3_observed_at, True,
                        home, away, window, request.as_of, TZ_MECHANISM,
                        ASSUMPTION_LABEL, tuple(notes))

    # missing F3 -> both None (accepted missing representation), reasons retained
    return F3Result(None, None, None, False, home, away, window, request.as_of,
                    TZ_MECHANISM, ASSUMPTION_LABEL, ("f3_missing_incomplete_evidence",))
