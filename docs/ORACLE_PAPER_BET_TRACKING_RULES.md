# Oracle Paper Bet Tracking Rules

This document governs the Edge Oracle paper-bet tracking process for the MLB Betting Edge project.

---

## Purpose

Edge Oracle is an MLB-only betting research analyst. This tracker exists to test Edge Oracle's analytical process quality using mock (paper) bets — with no real money at risk. Results from this tracker do not constitute proof of profitability, and no real-money betting decisions should be based solely on this record.

---

## Rules

**1. Assign a Play ID to every Oracle recommendation entered into the tracker.**
Use the format `EO-YYYY-###`, where `YYYY` is the calendar year and `###` is a zero-padded sequential number starting at 001 (e.g., `EO-2026-001`, `EO-2026-002`). IDs must be unique and sequential. Assign the Play ID at the moment the entry is created — before pregame conditions are evaluated. If a conditional play later fails its pregame conditions, keep the existing Play ID and record Status: No Play, Result: No Play, and Mock Profit/Loss: 0. Only games that were never entered into the tracker should have no Play ID.

**2. Paper betting only.**
All bets tracked here are mock plays. No real money is placed. This is a process evaluation tool.

**3. Flat 1-unit paper stakes.**
Every paper play uses a stake of 1 unit. Do not size plays differently based on confidence level during this evaluation phase.

**4. Maximum 0–3 paper plays per slate.**
Limit daily plays to three or fewer. If nothing qualifies, zero plays is correct. Volume is not the goal.

**5. Do not force a play.**
If the conditions for a play are not present, pass. Forced plays undermine process evaluation.

**6. Conditional plays only count if conditions are met before first pitch.**
Any play marked as conditional (Price Condition, Lineup Status, Starting Pitcher Status, Game Script, etc.) is only active if those conditions are confirmed prior to the first pitch of the targeted game.

**7. If conditions are not met, mark Result as "No play" and Mock Profit/Loss as 0.**
An unmet condition is not a loss. It is a void. Record it as such.

**8. Profit calculation for + odds wins.**
`Profit = Odds / 100`
Example: +130 win → +1.30 units.

**9. Profit calculation for - odds wins.**
`Profit = 100 / |Odds|`
Example: -150 win → +0.67 units.

**10. Loss equals -1 unit.**
All losses, regardless of odds, are recorded as -1 unit.

**11. Push equals 0.**
Pushes are recorded as 0 units. They do not count as wins or losses.

**12. Review milestones: 7 days, 30 paper bets, 100 paper bets.**
Conduct a structured review of process quality, verdict accuracy, and condition discipline at each milestone. Do not draw conclusions before the 30-bet minimum.

**13. Track passes separately if they reveal useful process lessons.**
If a pass would have been a significant win or loss, note it separately. Passes that illuminate reasoning gaps are valuable data.

**14. Do not treat paper-bet results as proof of profitability until sample size is meaningful.**
Small samples produce misleading win rates in both directions. Process quality evaluation is the primary goal at this stage.

---

## Boundaries

- Edge Oracle can suggest paper plays. It does not guarantee outcomes.
- This tracker is for testing process quality, not proving an edge immediately.
- No real-money recommendations should be stored as app data or used as production signals.
- No automated betting.
- No production decision engine.
- No Parlay Builder integration.
- No EV or fair-odds calculations unless separately approved and properly supported.

---

## Column Reference

| Column | Description |
|--------|-------------|
| Play ID | Unique sequential identifier in EO-YYYY-### format (blank for no-play entries) |
| Date | Calendar date of the game (YYYY-MM-DD) |
| Game | Teams involved (e.g., NYY @ BOS) |
| Game Start Time | Scheduled first pitch (local or ET) |
| Market | Bet type (e.g., Moneyline, Run Line, Total, F5) |
| Pick | The side or total direction selected |
| Odds | American odds at time of paper play |
| Book/Source | Sportsbook or data source referenced |
| Data Timestamp | When Edge Oracle retrieved or evaluated the data |
| Market Close Time | When the market closed or last meaningful line check |
| Oracle Verdict | Edge Oracle's classification (Playable / Thin / Overpriced / Watch / Pass) |
| Risk Tier | Oracle's assigned risk level (Low / Medium / High) |
| Paper Stake | Units staked (always 1 during evaluation phase) |
| Status | Play status at tracking time (Active / Conditional / Voided / Final) |
| Reason | Primary analytical rationale for the play |
| Weakest Point | The most defensible vulnerability in the pick's logic |
| Lineup Status | Confirmed / Projected / Unknown at time of play |
| Starting Pitcher Status | Confirmed / Projected / Unknown at time of play |
| Price Condition | Required odds threshold, if conditional (e.g., +120 or better) |
| Game Script | Expected game flow assumption supporting the play |
| Condition Met Before First Pitch | Yes / No / N/A |
| Result | Win / Loss / Push / No play |
| Closing Line | Final market price before game start |
| Mock Profit/Loss | Calculated per rules above (units) |
| Review Notes | Post-result observations, lessons, or process flags |
