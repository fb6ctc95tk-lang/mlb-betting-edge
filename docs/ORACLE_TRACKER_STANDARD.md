# Oracle Tracker Standard

**Edge Oracle — MLB Betting Edge Project**
**Authority Level: 4 — Derives Authority from Oracle Constitution, Oracle Evaluation Standard, and Oracle Audit Standard**
**Status: Ratified**

---

## Preamble

The Oracle Tracker is the primary evidence base for every Oracle evaluation, audit, and governance proposal. Its records must be complete, accurate, and preserved exactly as they were created. Nothing in Oracle practice is more consequential than the integrity of the tracker record.

This document establishes the official standard for the logical content of Oracle tracker records. It defines what data must exist in every record, when that data must be captured, and what quality standards the record must meet.

This standard governs logical content only. It does not prescribe a specific implementation technology — whether the tracker is maintained as a spreadsheet, a CSV file, a database, or another format is an implementation decision governed separately. Any implementation that satisfies the logical requirements defined here is compliant with this standard.

This document is coordinate with the Oracle Paper Bet Tracking Rules (`ORACLE_PAPER_BET_TRACKING_RULES.md`). The Tracking Rules govern procedural conduct — how the Oracle behaves when making and recording recommendations. This standard governs data content — what information the record must contain. Both documents are at Authority Level 4. Neither supersedes the other. Where they address the same matter, they must be read together.

---

## Article I — Purpose

### Section 1.1 — Why This Standard Exists

The Oracle's analytical value is only as real as the documentation that supports it. A recommendation that cannot be verified by reference to a complete, timestamped, pre-game record is not an auditable recommendation. An evaluation that depends on recollection rather than documentation is not a valid evaluation.

This standard exists to ensure that:

1. Every recommendation the Oracle makes is documented completely enough to support independent evaluation.
2. Every evaluation the Oracle performs is permanently recorded in the form that existed before the outcome was known.
3. Every record that enters the audit process contains sufficient evidence for the audit findings to be meaningful.
4. The tracker record is internally consistent with the Evaluation Standard's lifecycle requirements and the Audit Standard's evidence requirements.

### Section 1.2 — What This Standard Does Not Govern

This standard does not:

1. Define how to evaluate specific markets or sports. That is the domain of Market Playbooks.
2. Govern procedural rules for play selection, stake sizing, or pass discipline. That is the domain of the Tracking Rules.
3. Specify the physical format, file type, or software used to maintain the tracker.
4. Define audit procedures. That is the domain of the Audit Standard.
5. Authorize application development, database changes, or repository implementation by itself.

---

## Article II — Tracker Principles

The following principles govern all Oracle tracker conduct. They are derived from the Oracle Constitution and must be applied to every record, regardless of market, result, or evaluation outcome.

### Section 2.1 — Completeness Before Outcome

Every required pregame field must be populated before first pitch. A record is not complete — and cannot be legitimately evaluated — unless its pregame fields are documented before the outcome is known.

### Section 2.2 — Permanence

Once a record field is populated and the relevant lifecycle stage has passed, that field is permanent. Pregame fields are permanent from first pitch. Outcome fields are permanent once confirmed. A permanent field may not be silently edited. See Article V for the correction procedure.

### Section 2.3 — Technology Independence

The logical fields defined in this standard must be preserved in any tracker implementation. If an implementation cannot capture a required field, it does not satisfy this standard. The choice of technology does not relax content requirements. A change in implementation technology shall not require amendment of this standard unless the logical information requirements defined herein are themselves changed.

### Section 2.4 — Additive Postgame Documentation

Postgame fields are additions to the pregame record. They do not replace, revise, or reframe pregame documentation. The pregame record represents what the Oracle believed before the outcome. The postgame record represents what the Oracle observed afterward. These are distinct layers and must remain distinct.

### Section 2.5 — Record Self-Sufficiency

Every record should be complete enough that a reviewer with no prior knowledge of the recommendation — and no access to the Oracle's informal reasoning — can reconstruct the full basis for the recommendation and the full basis for the evaluation from the record alone. A reviewer should not need to rely upon memory, external conversations, undocumented assumptions, or informal context in order to understand or evaluate the record.

---

## Article III — Required Fields

This standard defines the logical meaning of each field. Implementation-specific names, spreadsheet headers, database columns, or application labels may differ from the names used here. Any implementation is compliant with this standard provided every implementation-specific field maps unambiguously to the logical field definitions established below.

Fields are organized by the Evaluation Lifecycle stage in which they are first populated. Each field definition specifies its purpose, whether it is required or optional, when it must be populated, and the acceptable values where a defined set applies.

**Timing Abbreviations Used Below:**

- *At creation* — when the tracker entry is first created, before pregame evaluation begins
- *Before first pitch* — any time between creation and the moment the game begins; must be complete and locked at first pitch
- *After game ends* — populated once the game's outcome is determined
- *During postgame review* — populated during the structured postgame evaluation process

---

### Field Group 1 — Identification and Scheduling

These fields identify the record and the game. They must be populated at the moment the tracker entry is created.

---

**Play ID**
- *Purpose:* Unique, permanent identifier for the record. Links all evaluation, audit, and review references to a single canonical entry.
- *Required/Optional:* Required for all active recommendations. Not assigned to games evaluated and passed without ever being entered.
- *When to populate:* At creation, before any other field is populated.
- *Acceptable values:* Format `EO-YYYY-###` where `YYYY` is the calendar year and `###` is a zero-padded sequential number starting at 001. IDs must be unique and sequential. IDs are never reused or reassigned.

---

**Date**
- *Purpose:* The calendar date of the game being recommended.
- *Required/Optional:* Required.
- *When to populate:* At creation.
- *Acceptable values:* ISO 8601 date format `YYYY-MM-DD`.

---

**Game**
- *Purpose:* Identifies the specific matchup to which the recommendation applies.
- *Required/Optional:* Required.
- *When to populate:* At creation.
- *Acceptable values:* A human-readable identifier sufficient to uniquely identify the matchup within the date (e.g., `NYY @ BOS`). Visiting team listed first.

---

**Game Start Time**
- *Purpose:* The scheduled first pitch time. Establishes the hard deadline for all pregame fields and conditions.
- *Required/Optional:* Required.
- *When to populate:* At creation if known; updated before first pitch if the schedule changes before evaluation is complete.
- *Acceptable values:* Time in a consistent format including timezone designation (e.g., `7:05 PM ET`). If the game is postponed after entry creation, the field is updated and a Review Note records the postponement.

---

**Market**
- *Purpose:* The type of bet being recommended. Establishes the analytical frame for evaluation categories and determines which Market Playbook governs.
- *Required/Optional:* Required.
- *When to populate:* At creation.
- *Acceptable values:* A specific market designation (e.g., `Moneyline`, `Run Line`, `Game Total`, `First 5 Innings Total`, `Team Total`). Generic labels that do not identify the market precisely are not acceptable.

---

### Field Group 2 — Recommendation Fields

These fields document the substance of the Oracle's recommendation. They must be populated at creation and may not be altered after first pitch.

---

**Selection**
- *Purpose:* The specific outcome the Oracle is recommending. Establishes precisely what the recommendation is so the Result field can be populated against it unambiguously.
- *Required/Optional:* Required for active recommendations. Not applicable to Pass entries.
- *When to populate:* At creation.
- *Acceptable values:* The specific side, direction, or value chosen within the designated market (e.g., `Yankees -1.5`, `Over 8.5`, `Red Sox ML`).

---

**Odds at Entry**
- *Purpose:* The American odds at which the recommendation is made. Used for Mock Profit/Loss calculation and for Closing Line Value comparison.
- *Required/Optional:* Required for active recommendations.
- *When to populate:* At creation, reflecting the price available when the recommendation is documented.
- *Acceptable values:* American odds format with sign (e.g., `+130`, `-115`).

---

**Line Source**
- *Purpose:* The sportsbook or data source from which the odds and line were obtained. Establishes the information provenance of the entry price.
- *Required/Optional:* Required.
- *When to populate:* At creation.
- *Acceptable values:* The name of the sportsbook, odds aggregator, or data feed used.

---

**Data Timestamp**
- *Purpose:* Records when the Oracle retrieved or evaluated the data used to make the recommendation. Establishes the information cutoff for the entry.
- *Required/Optional:* Required.
- *When to populate:* At creation.
- *Acceptable values:* Date and time in a consistent format (e.g., `2026-07-19 09:45 ET`).

---

**Oracle Verdict**
- *Purpose:* The Oracle's top-level classification of the recommendation. Distinguishes active plays from conditional plays from deliberate passes.
- *Required/Optional:* Required for every tracker entry, including passes that are formally recorded.
- *When to populate:* At creation.
- *Acceptable values:*

  | Value | Meaning |
  |---|---|
  | `Play` | The Oracle is recommending an active paper bet with no pending conditions. |
  | `Conditional Play` | The Oracle is recommending a paper bet that becomes active only if specified pregame conditions are confirmed before first pitch. |
  | `Pass` | The Oracle reviewed the opportunity and deliberately declined to recommend. The reason for the pass must be documented in the Thesis/Reason field. |
  | `No Evaluate` | The game was on the slate but the Oracle did not evaluate it. Used only for games the Oracle deliberately excluded from consideration. May require a brief note per Tracking Rules Rule 1. |

---

**Risk Tier**
- *Purpose:* The Oracle's assessment of the risk profile of the recommendation at the time of entry. Informs audit review and process evaluation.
- *Required/Optional:* Required for Play and Conditional Play verdicts.
- *When to populate:* At creation.
- *Acceptable values:* `Low`, `Medium`, `High`.

---

**Paper Stake**
- *Purpose:* The number of units staked on the paper bet. Used for Mock Profit/Loss calculation. Fixed by Tracking Rule 3 (flat 1-unit stakes during evaluation phase).
- *Required/Optional:* Required for Play and Conditional Play verdicts. Not applicable to Pass and No Evaluate entries.
- *When to populate:* At creation.
- *Acceptable values:* `1` unit during the current evaluation phase. Any deviation requires documented governance authorization.

---

**Thesis / Reason**
- *Purpose:* The Oracle's primary analytical rationale for the recommendation or the pass. This is the most important pregame documentation field. It must be specific enough to support process evaluation across all five Evaluation Standard categories.
- *Required/Optional:* Required.
- *When to populate:* At creation. May be expanded before first pitch as additional evidence is reviewed. May not be altered after first pitch.
- *Acceptable values:* Free text. Minimum specificity requirement: a reader must be able to identify the Oracle's directional thesis, the evidence supporting it, and the analytical distinction that justifies this recommendation rather than a pass.

---

**Weakest Point**
- *Purpose:* The Oracle's honest identification of the most significant vulnerability in its own recommendation. Documents that the Oracle has considered the strongest counter-case before committing to a recommendation.
- *Required/Optional:* Required for Play and Conditional Play verdicts.
- *When to populate:* At creation or before first pitch.
- *Acceptable values:* Free text. Must identify a specific, genuine vulnerability — not a generic disclaimer.

---

### Field Group 3 — Pregame Condition and Context Fields

These fields document conditional requirements and game context relevant to the recommendation. They must be populated before first pitch and are locked at first pitch.

---

**Lineup Status**
- *Purpose:* Records the confirmation status of relevant lineup information at the time of the recommendation.
- *Required/Optional:* Required for Play and Conditional Play verdicts where lineup information is material to the thesis. Optional where lineup is not analytically relevant.
- *When to populate:* At creation; may be updated before first pitch as lineup information becomes available.
- *Acceptable values:* `Confirmed`, `Projected`, `Unknown`.

---

**Starting Pitcher Status**
- *Purpose:* Records the confirmation status of the starting pitchers at the time of the recommendation.
- *Required/Optional:* Required for Play and Conditional Play verdicts in markets where starting pitcher performance is material to the thesis. Optional where starting pitchers are not analytically relevant.
- *When to populate:* At creation; may be updated before first pitch as confirmed starter information becomes available.
- *Acceptable values:* `Confirmed`, `Projected`, `Unknown`.

---

**Price Condition**
- *Purpose:* Documents any minimum or threshold odds requirement the Oracle has established for the recommendation to be active. Ensures that conditional pricing requirements are explicit and verifiable.
- *Required/Optional:* Required when Oracle Verdict is `Conditional Play` and the condition includes a price threshold. Optional for `Play` verdicts where no price condition applies.
- *When to populate:* At creation.
- *Acceptable values:* A specific odds threshold stated in American format (e.g., `+120 or better`, `-110 or better`). `N/A` for plays with no price condition.

---

**Expected Game Script**
- *Purpose:* Documents the Oracle's expectation of how the game will unfold in ways material to the thesis. Establishes the baseline against which Script Accuracy is evaluated postgame.
- *Required/Optional:* Optional, but strongly encouraged for any recommendation where game flow is a significant factor in the thesis.
- *When to populate:* Before first pitch.
- *Acceptable values:* Free text describing the expected game flow, pace, or scenario the thesis depends upon.

---

**Condition Met Before First Pitch**
- *Purpose:* Records whether all pregame conditions for a Conditional Play were confirmed satisfied before first pitch. The definitive field that determines whether a Conditional Play becomes active.
- *Required/Optional:* Required for all `Conditional Play` verdicts. `N/A` for all other verdict types.
- *When to populate:* Before first pitch, at the point of final condition verification.
- *Acceptable values:* `Yes` (all conditions met — play is active), `No` (one or more conditions not met — play becomes Void), `N/A`.

---

**Market Close Time**
- *Purpose:* Records when the market closed or when the Oracle performed its last meaningful line check before first pitch.
- *Required/Optional:* Optional. Recommended when the closing line is recorded.
- *When to populate:* Before or at first pitch.
- *Acceptable values:* Date and time in a consistent format (e.g., `2026-07-19 19:03 ET`).

---

### Field Group 4 — Pregame Process Evaluation Fields

These fields record the Oracle's formal pregame evaluation. All fields in this group must be completed before first pitch and are locked at first pitch. They may not be altered after first pitch under any circumstances.

---

**Process Score**
- *Purpose:* The Oracle's holistic assessment of overall pregame decision quality across all five evaluation categories. The primary evaluation field for audit and governance purposes.
- *Required/Optional:* Required for all Play and Conditional Play verdicts. Not required for Pass entries.
- *When to populate:* Before first pitch. Must be locked at first pitch.
- *Acceptable values:* `A`, `B`, `C`, `D`, `F` per the Oracle Evaluation Standard Section 6. The score is a holistic judgment, not a mechanical average of category grades.

---

**Category Evaluation — Game Selection**
- *Purpose:* Records the Oracle's assessment of whether this was the right opportunity to engage, per Evaluation Standard Section 4.1.
- *Required/Optional:* Required for all Play and Conditional Play verdicts.
- *When to populate:* Before first pitch. Locked at first pitch.
- *Acceptable values:* Free text assessment. Must be specific enough to explain the Process Score by reference to this category.

---

**Category Evaluation — Market Selection**
- *Purpose:* Records the Oracle's assessment of whether the chosen market is the correct vehicle for the thesis, per Evaluation Standard Section 4.2.
- *Required/Optional:* Required for all Play and Conditional Play verdicts.
- *When to populate:* Before first pitch. Locked at first pitch.
- *Acceptable values:* Free text assessment. Must explain why this market and not an alternative.

---

**Category Evaluation — Handicap Quality**
- *Purpose:* Records the Oracle's assessment of the analytical quality behind the recommendation, per Evaluation Standard Section 4.3.
- *Required/Optional:* Required for all Play and Conditional Play verdicts.
- *When to populate:* Before first pitch. Locked at first pitch.
- *Acceptable values:* Free text assessment. Must identify the specific evidence used and the counterarguments considered.

---

**Category Evaluation — Value and Price**
- *Purpose:* Records the Oracle's assessment of whether the entry price is acceptable given the thesis, per Evaluation Standard Section 4.4.
- *Required/Optional:* Required for all Play and Conditional Play verdicts.
- *When to populate:* Before first pitch. Locked at first pitch.
- *Acceptable values:* Free text assessment. Must address the relationship between the entry price and the Oracle's analytical view of fair value.

---

**Category Evaluation — Execution and Discipline**
- *Purpose:* Records the Oracle's assessment of whether the recommendation was made and documented in compliance with applicable Constitutional Rules and Tracking Rules, per Evaluation Standard Section 4.5.
- *Required/Optional:* Required for all Play and Conditional Play verdicts.
- *When to populate:* Before first pitch. Locked at first pitch.
- *Acceptable values:* Free text assessment. Must confirm compliance or document any deviation.

---

### Field Group 5 — Outcome Fields

These fields record the factual result of the recommendation. They are populated after the game ends. They are distinct from evaluation fields and do not alter any pregame field or grade.

---

**Status**
- *Purpose:* Records the final disposition of the tracker entry at the time of review.
- *Required/Optional:* Required.
- *When to populate:* After game resolution, or when the entry's final state is determined.
- *Acceptable values:* `Active` (pregame, not yet played), `Final` (game complete, entry closed), `Voided` (conditional play with unmet conditions), `No Play` (game did not occur or play was withdrawn before activation).

---

**Result**
- *Purpose:* The factual outcome of the recommendation against the selected market.
- *Required/Optional:* Required for all entries that were active (Play or Conditional Play with conditions met).
- *When to populate:* After game ends and outcome is confirmed.
- *Acceptable values:* `Win`, `Loss`, `Push`, `Void`, `No Play`. Per Evaluation Standard Section 7.

---

**Closing Line**
- *Purpose:* The market price immediately before game start. Used to calculate Closing Line Value (CLV) per Evaluation Standard Section 5.2.
- *Required/Optional:* Optional. Record when available. If unavailable, the field is marked `Unavailable`.
- *When to populate:* After game ends (or sourced from closing-line data at game time).
- *Acceptable values:* American odds format (e.g., `-108`), or `Unavailable`.

---

**CLV Comparison**
- *Purpose:* Documents whether the Oracle's entry price was more or less favorable than the closing market price.
- *Required/Optional:* Optional. Required only when Closing Line is recorded and available.
- *When to populate:* After Closing Line is recorded.
- *Acceptable values:* `Beat the Close`, `Tied the Close`, `Lost to the Close`, `Unavailable`. Per Evaluation Standard Section 5.2.

---

**Mock Profit/Loss**
- *Purpose:* The calculated paper profit or loss for the entry, in units, per the calculation rules in the Tracking Rules.
- *Required/Optional:* Required for all entries with a Result.
- *When to populate:* After Result is recorded.
- *Acceptable values:* A numeric value in units, calculated per Tracking Rules 8–11. Zero for Void and No Play results.

---

### Field Group 6 — Postgame Review Fields

These fields are populated during the structured postgame review process. They are additive — they document what the Oracle observed after the game without altering the pregame record.

---

**Actual Game Script**
- *Purpose:* A factual description of how the game played out, for comparison against the Expected Game Script.
- *Required/Optional:* Optional. Required when Expected Game Script was populated.
- *When to populate:* During postgame review.
- *Acceptable values:* Free text describing the relevant game flow. Must be factual, not evaluative.

---

**Script Accuracy**
- *Purpose:* A qualitative assessment comparing the actual game to the expected game script, per Evaluation Standard Section 5.3.
- *Required/Optional:* Optional. Required when Expected Game Script was populated.
- *When to populate:* During postgame review, after Actual Game Script is documented.
- *Acceptable values:* `As Expected`, `Partially As Expected`, `Diverged`. Script Accuracy is independent of the Result.

---

**Repeat Decision Assessment**
- *Purpose:* Records whether, under identical pregame conditions, the Oracle would make the same recommendation again. Per Evaluation Standard Section 5.5.
- *Required/Optional:* Optional. Encouraged for all Play and Conditional Play entries.
- *When to populate:* During postgame review.
- *Acceptable values:* `Yes`, `No`, `Conditional`. A Conditional value must specify the condition. Assessment is based on process quality, not the result.

---

**Variance Classification**
- *Purpose:* Classifies the relationship between the Oracle's pregame model, the actual game script, and the result. Per Evaluation Standard Section 8.
- *Required/Optional:* Required for all Play and Conditional Play entries with a Final Result.
- *When to populate:* During postgame review, after Script Accuracy is determined.
- *Acceptable values:* `Expected`, `Positive Variance`, `Negative Variance`, `Model Miss`. Per Evaluation Standard Section 8.

---

**Lessons Learned Classification**
- *Purpose:* The classification of the principal process or analytical observation from the completed recommendation. Per Evaluation Standard Section 9.
- *Required/Optional:* Required for all Play and Conditional Play entries with a Final Result.
- *When to populate:* During postgame review, after Variance Classification is assigned.
- *Acceptable values:* `No Action Required`, `Monitor`, `Investigate`, `Recommend Governance Review`. Per Evaluation Standard Section 9. The classification is advisory. It does not modify any governance document.

---

**Review Notes**
- *Purpose:* Free-text field for postgame observations, lessons, anomalies, or process flags that do not fit neatly into other structured fields.
- *Required/Optional:* Optional. Required when Lessons Learned Classification is `Investigate` or `Recommend Governance Review` — in those cases the note must document the specific gap, pattern, or governance concern.
- *When to populate:* During postgame review.
- *Acceptable values:* Free text.

---

### Field Group 7 — Record Quality Field

---

**Record Completeness**
- *Purpose:* A meta-field documenting the quality and completeness of the tracker record as a whole. Used by the Audit Standard to assess the reliability of the record as audit evidence.
- *Required/Optional:* Required for all records at the time of postgame review completion.
- *When to populate:* At the conclusion of the postgame review process, as the final step before the record is considered closed.
- *Acceptable values:* See Article VII.

---

## Article IV — Timing Rules

### Section 4.1 — The First Pitch Boundary

First pitch is the absolute boundary between pregame and postgame. It is not a soft deadline.

All fields in Field Groups 1, 2, 3, and 4 must be complete at first pitch. Any required field that is not populated at first pitch is absent from the pregame record — not late, not pending. The record is incomplete at that point, and the incompleteness is permanent.

No pregame field may be populated, revised, or supplemented after first pitch under any circumstances, even to correct an error. See Article V for the correction procedure, which does not permit restoration of genuinely missing pregame data.

### Section 4.2 — Order Within the Pregame Window

The pregame window is the period from entry creation to first pitch. Within this window, fields must be populated in an order consistent with the Evaluation Lifecycle:

1. Identification and Scheduling Fields — at creation
2. Recommendation Fields — at creation
3. Pregame Condition and Context Fields — at creation or updated as information becomes available
4. Pregame Process Evaluation Fields — completed as the final step before first pitch

Process Evaluation Fields must reflect the Oracle's analysis at or near the time of entry, not hours before first pitch when material information may not yet be available. The Data Timestamp documents the information cutoff.

### Section 4.3 — Postgame Timing

Postgame fields should be populated within a reasonable time after game completion. A target of the same calendar day or the following morning is consistent with good practice.

Postgame fields must not be populated before the game ends. An outcome entered before the final result is confirmed is not a valid outcome record.

### Section 4.4 — Pass Entries

Formally recorded Pass entries (Oracle Verdict: `Pass`) require the following fields at minimum: Play ID (optional per Tracking Rules), Date, Game, Market, Oracle Verdict, and Thesis/Reason (documenting the reason for the pass). Other fields may be marked `N/A`. No process evaluation is required for Pass entries.

---

## Article V — Record Corrections

### Section 5.1 — The Permanence Rule

Every field in the tracker record that has been populated and whose lifecycle stage has passed is permanent. This rule derives from Constitutional Rule 4 (No Rewriting History) and is not subject to exception except through the procedure below.

Silent editing — changing a field value without documenting the change — is prohibited unconditionally.

### Section 5.2 — What May Be Corrected

Corrections are permitted only for factual transcription errors: cases where the value entered does not reflect what the Oracle actually determined or observed at the time of entry, due to a data entry mistake.

Permitted correction examples:
- A team name entered in the wrong order
- A date entered as the wrong calendar date due to a typo
- An odds value transposed (e.g., `+130` entered as `+310`)
- A Play ID with an incorrect sequence number

Prohibited revision examples:
- Changing a Process Score after first pitch, regardless of reason
- Revising the Thesis to strengthen the analytical case after the result is known
- Updating a Variance Classification because the initial classification was later judged incorrect
- Changing an Outcome field because of a subsequent official scorer ruling without independent documentation

### Section 5.3 — Correction Procedure

When a factual transcription error is identified:

1. The original erroneous value must be preserved and marked as superseded (e.g., struck through, moved to a correction field, or documented in Review Notes according to the implementation's capabilities).
2. The corrected value is entered alongside the original.
3. Review Notes must permanently record all of the following: (a) the original value, (b) the corrected value, (c) the date and time of the correction, (d) the reason the change is a factual correction and not a revision, and (e) the person or system making the correction, as applicable to the implementation.
4. Corrections to pregame fields after first pitch require Constitution Authority notification before the correction is made. The Constitution Authority may review and confirm or reject the correction.

### Section 5.4 — Analytical Revisions Are Not Corrections

A disagreement with an evaluation judgment made before first pitch is not a factual error. If the Oracle believes its pregame Process Score was too high or too low, that belief is itself a lesson and should be documented in Lessons Learned — not corrected in the record. The pregame record reflects what the Oracle believed when it was documented. That belief is what the Oracle is accountable to.

---

## Article VI — Missing Data

### Section 6.0 — Status Marker Definitions

The following status markers are used throughout this standard to indicate the state of a field that is not populated with a substantive value. Each marker has a distinct meaning. They are not interchangeable.

| Marker | Meaning |
|---|---|
| `Unknown` | The information may exist but has not yet been confirmed. Used in field values where the state of a fact is genuinely unresolved at the time of documentation (e.g., a starting pitcher whose status has not been officially announced). `Unknown` is a substantive field value, not a missing-data marker. |
| `Unavailable` | The information does not exist or cannot reasonably be obtained. Used when the data source is inaccessible, the market does not publish the information, or the information has been lost. `Unavailable` is a permanent statement that the information cannot be supplied. |
| `Pending` | The information is expected to become available before the applicable lifecycle deadline. Used only within the pregame window for fields awaiting confirmation. A field marked `Pending` at first pitch for any pregame field is a documentation failure — see Section 6.2. |
| `N/A` | The field does not apply to the current record type. Used when a field is structurally inapplicable (e.g., Paper Stake on a Pass entry, or Condition Met Before First Pitch on a Play verdict with no conditions). `N/A` is not a substitute for `Unavailable` or `Unknown`. |

These definitions apply consistently to every use of these markers throughout this standard.

### Section 6.1 — Required Field Gaps

When a required field cannot be populated — because the information is genuinely unavailable, the game was postponed before evaluation was complete, or another documented circumstance prevented completion — the field must be marked explicitly rather than left blank.

Acceptable missing-data markers:
- `Unavailable` — the information does not exist or cannot reasonably be obtained (see Section 6.0)
- `N/A` — the field does not apply to this entry type (see Section 6.0)
- `Pending` — the field is expected to be populated (used only within the pregame window; must not remain Pending after first pitch for pregame fields — see Section 6.0)

A blank field is not an acceptable substitute for a missing-data marker. An unmarked blank is ambiguous. An explicit marker creates an auditable record of what is missing and why.

### Section 6.2 — Pre-First-Pitch Gaps

A required field that is blank or marked Pending at first pitch is absent from the pregame record. This is a documentation failure. It must be noted in Review Notes and reflected in the Record Completeness classification. The field may not be populated after first pitch.

### Section 6.3 — Post-Game Gaps

Missing data in postgame fields — where the information was genuinely unavailable (e.g., Closing Line unavailable for the market) — must be explicitly marked `Unavailable`. Missing data that reflects incomplete postgame review must be completed. An incomplete postgame review is not a closed record.

---

## Article VII — Data Quality

### Section 7.1 — Record Completeness Classification

Every record must receive a Record Completeness classification as the final step of the postgame review process. This classification documents the documentation quality of the record — not the quality of the analytical process and not the result.

Record Completeness is assessed against the requirements of this standard, not against any performance standard.

---

**Complete**

All required fields are populated with values within their acceptable ranges. All timing rules were respected — pregame fields were populated before first pitch, postgame fields reflect information available at the time of review. No correction procedure was required, or if one was, it was executed correctly. The record is fully usable for evaluation and audit purposes.

---

**Minor Missing Data**

One or more of the following conditions apply:
- One or two optional fields are absent where absence does not materially reduce audit value
- One required field of low governance impact is absent or marked Unavailable for a documented reason
- A correction procedure was applied to a minor transcription error in a non-critical field

The record is substantially usable for evaluation and audit purposes but has a documented gap. The gap must be noted in Review Notes.

---

**Significant Missing Data**

One or more of the following conditions apply:
- One or more required fields of high governance impact are absent (including any Process Evaluation field, any Outcome field, or the Thesis/Reason field)
- Required pregame fields were not completed at first pitch and cannot be reconstructed from contemporaneous sources
- Multiple required fields are absent or marked Unknown
- A correction procedure was applied to a critical field without Constitution Authority notification

The record has limited audit value. It may be included in quantitative audit summaries as a data point but findings derived from it must be noted as resting on an incomplete record. The Audit Standard's evidence hierarchy applies — records with Significant Missing Data are lower-quality evidence.

### Section 7.2 — Implications for Audit

Record Completeness classifications are direct inputs to Audit Confidence assessment under the Audit Standard. An audit scope with a high proportion of Significant Missing Data records will reflect a lower Audit Confidence classification per Audit Standard Article VI, Section 6.3.

The Document Maintainer must flag Significant Missing Data records in every audit report that includes them.

---

## Article VIII — Relationship to Governance

### Section 8.1 — Tracker Records as Primary Audit Evidence

The Oracle tracker record is the primary source of evidence for all Oracle audits. The Audit Standard defines the standards for what constitutes valid evidence. This standard defines what the record must contain in order to satisfy those evidence requirements.

A recommendation that is not documented in the tracker to the standard defined here does not generate valid audit evidence for the fields that are absent.

### Section 8.2 — Tracker Records and the Evaluation Standard

The field definitions in Article III are designed to capture every data point required by the Oracle Evaluation Standard's lifecycle. The Process Evaluation fields (Group 4) satisfy the pregame evaluation requirements of Evaluation Standard Section 4. The Postgame Review fields (Group 6) satisfy the postgame evaluation requirements of Evaluation Standard Section 5. A record that is Complete under this standard contains the full evidence set required for a valid lifecycle evaluation.

### Section 8.3 — Tracker Records and the Constitutional Amendment Procedure

Tracker records are the evidentiary foundation for governance proposals under Constitutional Article VI. A governance proposal that cannot be supported by reference to complete tracker records, analyzed through a conformant audit, does not satisfy the evidence requirements of the Amendment Procedure.

This standard exists to ensure that the tracker is always capable of supporting the Amendment Procedure when the evidence threshold is reached.

### Section 8.4 — Tracker Standard and Tracking Rules Relationship

This standard and the Tracking Rules are coordinate documents at Authority Level 4. Conflicts between them must be escalated to the Constitution Authority for resolution per Constitutional Section 2.2. Neither document supersedes the other.

---

## Article IX — Version History

| Version | Date | Change | Authority |
|---------|------|--------|-----------|
| 1.0 | 2026-07-19 | Initial draft | Document Maintainer |
| 1.0 | 2026-07-19 | Ratified by Constitution Authority | Constitution Authority |

---

*End of Oracle Tracker Standard v1.0 Draft*
