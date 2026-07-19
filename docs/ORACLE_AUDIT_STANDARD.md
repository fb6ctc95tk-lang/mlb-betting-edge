# Oracle Audit Standard

**Edge Oracle — MLB Betting Edge Project**
**Authority Level: 3 — Derives Authority from Oracle Constitution and Oracle Evaluation Standard**
**Status: Ratified**

---

## Preamble

Audit is the mechanism by which the Oracle reviews its own performance, tests the integrity of its process, and generates the evidence on which governance proposals may be based.

This document establishes the official standards by which Edge Oracle audits are conducted, reported, and acted upon. It derives its authority from the Oracle Constitution (Level 1) and is informed by the Oracle Evaluation Standard (Level 2). It may expand upon the principles established in those documents. It may never contradict them.

The Audit Standard governs audit conduct only. It does not define what changes the Oracle should make — that is the domain of the Amendment Procedure in the Oracle Constitution. The Audit Standard ensures that the evidence reaching the Amendment Procedure is honest, structured, and properly sourced.

---

## Article I — Purpose

### Section 1.1 — Why Audits Exist

The Edge Oracle operates under uncertainty. Its evaluation process — however disciplined — may contain systematic biases, structural blind spots, or methodology errors that are invisible from within individual recommendations but become visible only across a meaningful sample of decisions.

Audits exist to:

1. Evaluate whether the Oracle's process is performing as designed.
2. Identify recurring patterns in variance that may indicate systematic evaluation errors rather than expected noise.
3. Generate structured findings that can support or contradict governance proposals.
4. Create an honest, documented record of the Oracle's performance across defined time periods and play samples.
5. Test whether the Oracle's self-evaluation is consistent, accurate, and free from grade inflation.
6. Provide the evidence base required by the Constitutional Amendment Procedure.

### Section 1.2 — What Audits Do Not Do

Audits do not:

1. Determine whether governance proposals are approved. That authority belongs exclusively to the Constitution Authority.
2. Modify Oracle governance documents. Audits generate findings and may produce Proposals; they do not enact changes.
3. Override the Constitution, Evaluation Standard, or any other higher-level document.
4. Evaluate individual recommendations after-the-fact with information not available before the game. All retrospective review is limited to what was documented in the pregame record.
5. Retroactively alter process grades, tracker records, or documented reasoning.

---

## Article II — Audit Philosophy

The following principles govern all Oracle audit conduct. They are derived from the Oracle Constitution and must be applied in every audit, regardless of type, scope, or findings.

### Section 2.1 — Audits Serve the Process, Not the Outcome

An audit that finds the Oracle performed well is only as valuable as one that finds it performed poorly. The purpose of an audit is accurate assessment — not validation, not exoneration, and not confirmation of a preferred narrative.

Audit findings must reflect the evidence as it exists. If the evidence is unfavorable, the findings must say so. If the evidence is favorable, inflating the critique to appear rigorous is equally dishonest.

### Section 2.2 — Evidence Precedes Conclusion

No audit finding may be reached without traceable supporting evidence from the Oracle record. An auditor's intuition, observation, or prior expectation is not an audit finding. Every conclusion must cite the specific records, patterns, or data that support it.

### Section 2.3 — The Pregame Record Is the Only Record

Retrospective review — looking at what happened in a game and asking whether the Oracle should have known better — is not a valid audit activity when it requires knowledge not available at the time the recommendation was made.

Every audit finding about recommendation quality is anchored to what the pregame record shows, not what the outcome implies.

### Section 2.4 — Audits Must Be Survivable

The Oracle governance process is designed for the long term. Audit findings that are accurate but unnecessarily harsh, or that generate governance proposals beyond what the evidence supports, are counterproductive. Audits must produce findings the process can act on — not findings that destabilize a still-developing practice.

### Section 2.5 — Audit Independence

The Oracle Engine (Edge Oracle GPT) generates recommendations and self-evaluations but is not the final auditing authority. The Document Maintainer (Claude) conducts audits under this standard. The Constitution Authority reviews and approves audit findings before any findings are used as the basis for a governance proposal.

---

## Article III — Audit Types

### Section 3.1 — Milestone Audit

A Milestone Audit is triggered when the Oracle has accumulated a defined quantity of tracked recommendations sufficient to support meaningful analysis.

**Trigger condition:** Oracle tracker reaches 30 recorded plays with completed pregame evaluations and recorded outcomes.

**Scope:** All plays from the beginning of the tracked period through the milestone trigger.

**Authorization:** The Document Maintainer initiates when the trigger condition is met. No separate authorization is required to begin the audit; Constitution Authority approval is required before any Milestone Audit findings are used as the basis for a governance proposal.

**Frequency:** Each subsequent Milestone Audit may be triggered at the Constitution Authority's discretion after the first 30-play milestone, or at any additional milestone the Constitution Authority designates.

### Section 3.2 — Triggered Audit

A Triggered Audit is initiated in response to a specific operational or governance event that requires examination outside the normal milestone schedule.

**Valid trigger conditions (per Constitutional Rule 6):**

- A safety concern involving the Oracle's use or outputs
- An integrity concern about the accuracy or honesty of documented records
- A discovered contradiction between two governance documents
- Ambiguity in governance language producing materially different interpretations
- Data corruption in the tracker or supporting records
- An operational failure affecting the Oracle's ability to function as designed

**Authorization:** The Document Maintainer may identify a potential trigger condition and notify the Constitution Authority. The Constitution Authority authorizes the Triggered Audit. The Document Maintainer conducts it.

**Scope:** Defined at the time of authorization. The scope must be specific to the trigger condition and must not expand beyond what the trigger requires without additional Constitution Authority approval.

### Section 3.3 — Advisory Review

An Advisory Review is a lightweight, informal examination of the Oracle record that does not produce a formal Audit Report.

**Purpose:** To monitor developing patterns, check data integrity, or answer a specific operational question before a formal audit is warranted.

**Output:** A brief written summary shared with the Constitution Authority. No governance proposals may derive from an Advisory Review alone.

**Authorization:** No formal authorization required. The Document Maintainer may conduct Advisory Reviews at any time.

Advisory Reviews are operational monitoring activities. They do not become part of the permanent Oracle audit record unless their findings are explicitly incorporated into a formal Audit Report that has been approved by the Constitution Authority under this standard.

---

## Article IV — Audit Inputs

### Section 4.1 — Required Inputs

Every Milestone Audit and Triggered Audit requires the following inputs before audit work may begin:

1. **The Oracle Tracker** — the complete tracker record for the audit scope period, including all plays, all pregame fields, all process grades, and all outcomes.
2. **The Tracking Rules** — the current version of `ORACLE_PAPER_BET_TRACKING_RULES.md` in effect during the audit period.
3. **The Oracle Constitution** — the current ratified version.
4. **The Oracle Evaluation Standard** — the current active version.
5. **Any Market Playbooks** in effect during the audit period, if applicable to the plays under review.

### Section 4.2 — Conditional Inputs

The following inputs are required if they are relevant to the audit scope:

- Prior Audit Reports for any period overlapping the current audit scope
- Change Log entries for any governance document modified during the audit period
- Supporting research materials cited in the pregame record of any play under review (when the audit specifically addresses the quality of that research)

### Section 4.3 — Input Completeness Requirement

An audit may not begin if required inputs are incomplete, absent, or suspected to be corrupted. The Document Maintainer must document any input gaps and notify the Constitution Authority before proceeding.

A Triggered Audit investigating data corruption is exempt from the input completeness requirement only to the extent that the missing or corrupted data is itself the subject of the audit.

---

## Article V — Audit Procedure

Every Milestone Audit and Triggered Audit follows the procedure below. Steps must be completed in sequence.

### Step 1 — Define Scope

Before any analysis begins, the Document Maintainer defines and documents:

- The audit type (Milestone or Triggered)
- The date range and play range under review
- The specific questions the audit will answer
- Any exclusions from scope and the reason for each exclusion

Scope definitions for Triggered Audits must match the trigger authorization. Scope may not expand during the audit without Constitution Authority approval.

### Step 2 — Verify Inputs

Confirm all required inputs under Article IV are present, complete, and internally consistent. Document any anomalies found.

### Step 3 — Compile the Play Sample

Identify all plays within the defined scope. For each play, confirm:

- Pregame evaluation fields are complete
- Process grade is recorded
- Outcome is recorded
- No fields were modified after first pitch (compare timestamps if available)

Flag any plays where record integrity is in question. Flagged plays may be excluded from quantitative analysis but must be noted in the report.

### Step 4 — Quantitative Summary

Compute and document:

- Total plays in scope
- Distribution of Process Scores (count and percentage at each grade)
- Win/loss record by Process Score grade
- Variance between expected and actual results by grade
- Any statistically notable patterns in market selection, game type, or other dimensions the audit is specifically examining

Quantitative analysis is descriptive, not diagnostic. Statistical patterns alone do not establish causation. Before a pattern identified in quantitative analysis can support an interpretive conclusion, that conclusion must be grounded in supporting evidence consistent with the Evidence Standards in Article VII. Patterns identified here are inputs to the interpretive step that follows.

### Step 5 — Interpretive Analysis

Examine the quantitative patterns for explanations. For each notable pattern, consider:

- Is this within the range of expected variance for the sample size?
- Is there a structural explanation (market conditions, data quality, seasonal factors)?
- Is there evidence of a systematic evaluation error?
- Is there evidence of grade inflation or deflation in process scores?
- Does any pattern suggest a governance gap, contradiction, or ambiguity?

Interpretive claims must be supported by evidence. State what the evidence shows, then what it may mean, and separately state the confidence the audit has in that interpretation (per Article VI, Section 6.3).

### Step 6 — Classify Findings

Assign each finding a classification per Article VI.

### Step 7 — Draft Report

Produce a draft Audit Report meeting the requirements of Article VIII.

### Step 8 — Submit for Constitution Authority Review

Submit the draft report to the Constitution Authority for review before finalizing. The Constitution Authority may:

- Approve the report as submitted
- Request revisions to specific findings
- Direct additional investigation before the report is finalized
- Decline to accept a finding that lacks adequate evidence

### Step 9 — Finalize and Commit

After Constitution Authority approval, the Document Maintainer finalizes the report and commits it to the repository as a Level 5 document per the governance hierarchy.

---

## Article VI — Audit Findings

### Section 6.1 — Finding Classification

Every substantive finding in an Audit Report must be assigned one of the following classifications:

| Classification | Meaning |
|---|---|
| **No Action Required** | The evidence shows the Oracle's process is performing as designed in this area. No governance change is warranted. |
| **Monitor** | A pattern exists that does not yet constitute evidence of a systematic problem but warrants observation in the next audit period. |
| **Investigate** | A pattern or anomaly requires deeper examination before a conclusion can be reached. The Document Maintainer must specify what additional evidence would resolve the question. |
| **Recommend Governance Review** | The evidence is sufficient to support a formal governance proposal under the Constitutional Amendment Procedure. The Document Maintainer must specify the exact concern and what the evidence shows. |

A finding classified as "Recommend Governance Review" does not itself propose or require a specific amendment. It identifies a concern and points to evidence. The Constitution Authority determines whether and how to act on it.

### Section 6.2 — Governance Flow: Findings, Recommendations, and Decisions

The following distinctions govern how audit outputs move through the governance process. Each term has a specific meaning and must not be used interchangeably.

**Audit Finding**
A Finding documents what the evidence in the Oracle record demonstrates. A Finding is an evidentiary statement, not a judgment about what should happen next. Every Finding must be traceable to specific records, patterns, or data per Article VII.

**Audit Recommendation**
A Recommendation suggests a possible course of action based on one or more Findings. A Recommendation may arise from a finding classified "Recommend Governance Review" (Section 6.1). A Recommendation is the Document Maintainer's assessment of what the evidence may warrant — it is not a directive and does not carry governance authority.

**Governance Decision**
A Governance Decision is made exclusively by the Constitution Authority through the constitutional governance process defined in Constitutional Article VI. No Finding and no Recommendation — regardless of its classification or confidence level — constitutes a Governance Decision. The Constitution Authority may accept, reject, modify, or defer any Recommendation without affecting the validity of the underlying Finding.

### Section 6.3 — Audit Confidence Classification

Every Audit Report must include an overall Audit Confidence classification and, where appropriate, per-finding confidence levels. Audit Confidence is a holistic assessment — not a mechanical checklist — based on the following factors considered together:

**Factors bearing on Audit Confidence:**

- **Sample adequacy** — whether the number of plays provides meaningful signal relative to the question the audit is answering
- **Record completeness** — whether pregame evaluations, process grades, and outcomes are fully documented for all plays in scope
- **Tracker integrity** — whether any records show signs of post-hoc modification, missing fields, or data anomalies
- **Quality of supporting evidence** — whether conclusions are grounded in clear, specific evidence from the tracker record
- **Consistency of findings** — whether findings are internally consistent or whether conflicting signals exist that are not explained
- **Presence of corroborating evidence** — whether key findings are supported by more than one independent evidence point

Play count is one contributing factor to sample adequacy. It is not the sole determinant of any confidence level.

| Confidence Level | Meaning |
|---|---|
| **High** | The audit record is complete, evidence is clear and consistent, findings are supported by multiple independent evidence points, and the sample is adequate to the question being answered. The audit's conclusions are reliable for governance purposes. |
| **Moderate** | The audit record is substantially complete but contains gaps, ambiguities, or findings that rest on limited evidence points. The sample may be meaningful but not conclusive. The audit's conclusions are useful but should be weighted accordingly. |
| **Low** | The audit record has material gaps, findings cannot be clearly separated from expected variance, or evidence is insufficient to support the conclusions with confidence. The audit's conclusions are observational only and may not support governance proposals. |

A Low-confidence audit may not be used as the basis for a governance proposal without additional corroborating evidence.

---

## Article VII — Evidence Standards

### Section 7.1 — What Constitutes Valid Audit Evidence

The following are valid forms of audit evidence:

1. **Tracker records** — completed fields in the official Oracle tracker, including dates, grades, outcomes, and documentation columns.
2. **Pregame evaluation documentation** — the reasoning and supporting data documented in the tracker or referenced pregame materials, as they existed before first pitch.
3. **Governance documents** — ratified or active versions of any document in the Oracle hierarchy, cited for the specific text that is relevant.
4. **Quantitative patterns** — statistical patterns in the tracker record across a defined play sample, described with appropriate context about sample size.
5. **Operational logs** — system logs, error records, or other operational artifacts relevant to a Triggered Audit investigating operational failure.

### Section 7.2 — What Does Not Constitute Valid Audit Evidence

The following are NOT valid forms of audit evidence:

1. **Game outcomes as proof of evaluation error** — a loss does not prove the recommendation was poorly evaluated. An outcome-based argument for a negative finding must also cite what the pregame record specifically failed to identify.
2. **Post-game information** — information that was not available before first pitch may not be used to evaluate whether the pregame record was adequate.
3. **Anecdotal observation** — a general impression of how the Oracle has been performing, without reference to specific tracker records, is not evidence.
4. **Prior audit findings without independent support** — a finding from a prior audit may be cited as context but must be independently supported in the current audit record. Prior findings do not carry forward automatically.
5. **Constitutional or Evaluation Standard assertions alone** — the fact that a rule or principle exists is not evidence that the Oracle has violated it. A violation must be demonstrated through the tracker record.

### Section 7.3 — Handling Ambiguous Evidence

When evidence is ambiguous — capable of supporting more than one conclusion — the audit must:

1. State both possible interpretations.
2. Describe what additional evidence would distinguish between them.
3. Assign a finding classification of "Investigate" rather than "Recommend Governance Review" until the ambiguity is resolved.

---

## Article VIII — Audit Report Requirements

### Section 8.1 — Required Report Sections

Every Milestone Audit and Triggered Audit must produce a written Audit Report containing the following sections:

1. **Header** — Document title, audit type, date range, audit date, and Document Maintainer identification.
2. **Audit Confidence** — Overall Audit Confidence classification (High/Moderate/Low) with a brief explanation.
3. **Scope Summary** — Play count, date range, markets reviewed, and any exclusions with reasons.
4. **Input Verification** — Confirmation that all required inputs were present and complete, or documentation of any gaps.
5. **Quantitative Summary** — Grade distribution, win/loss record by grade, and any notable statistical patterns.
6. **Interpretive Analysis** — Explanations and interpretations of notable patterns, with evidence citations.
7. **Findings** — Each finding listed with its classification, supporting evidence, and per-finding confidence level per Section 6.3 where applicable.
8. **Governance Implications** — A summary of whether any findings support governance proposals under the Amendment Procedure. If none, this section must explicitly state: "No governance proposals arising from this audit."
9. **Next Audit Recommendation** — What the Document Maintainer recommends for the scope and timing of the next audit.
10. **Constitution Authority Approval** — Space for the Constitution Authority's approval notation before the report is finalized.

### Section 8.2 — Report Naming and Filing

Audit Reports are filed in the `docs/` directory of the repository using the naming convention:

```
ORACLE_AUDIT_REPORT_[TYPE]_[DATE].md
```

Where:
- `[TYPE]` is `MILESTONE` or `TRIGGERED`
- `[DATE]` is the report date in `YYYY-MM-DD` format

### Section 8.3 — Report Permanence

Finalized Audit Reports may not be modified after the Constitution Authority approves them. Errors discovered after finalization must be documented in a separate addendum filed alongside the original report, not by editing the original.

---

## Article IX — Relationship to the Constitution

### Section 9.1 — Subordination

This document is subordinate to the Oracle Constitution. Every audit must operate within the bounds the Constitution establishes. Where this standard is silent on a matter of governance, the Constitution governs.

### Section 9.2 — Audit Cannot Amend the Constitution

Audit findings — regardless of their classification or Audit Confidence level — do not amend the Constitution. They produce evidence and may produce governance proposals. Amendments require the full Amendment Procedure specified in Constitutional Article VI.

### Section 9.3 — Audit Cannot Override Prior Decisions

A finding that a past Oracle decision was evaluatively weak does not retroactively change that decision's status in the tracker. The Oracle record is permanent per Constitutional Rule 4 (No Rewriting History). Audit findings describe what happened; they do not alter it.

### Section 9.4 — Consistency with the Evaluation Standard

Audit interpretations of process quality must be consistent with the grading framework established in the Oracle Evaluation Standard. An audit may not assign different meanings to Process Score grades than those defined in the Evaluation Standard.

### Section 9.5 — Escalation to the Constitution

If an audit produces findings that suggest the Constitution itself requires amendment — not merely that a lower-level document does — those findings must be explicitly identified as constitutional-level concerns and submitted to the Constitution Authority for consideration under the full Amendment Procedure. No other action may follow from such findings until the Constitution Authority has reviewed them.

---

## Article X — Version History

| Version | Date | Change | Authority |
|---------|------|--------|-----------|
| 1.0 | 2026-07-18 | Initial draft | Document Maintainer |
| 1.0 | 2026-07-19 | Ratified by Constitution Authority | Constitution Authority |

---

*End of Oracle Audit Standard v1.0 Draft*
