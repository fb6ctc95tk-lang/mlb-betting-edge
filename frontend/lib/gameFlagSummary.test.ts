import { describe, it, expect } from "vitest";
import { getGameFlagSummary } from "./gameFlagSummary";
import { LINE_MOVE_THRESHOLD } from "./gameFilters";

const injury = { player_name: "Test Player" };
const bigMove = { movement: LINE_MOVE_THRESHOLD };
const weather = { temperature: 72 };

function bare() {
  return { away_injuries: [], home_injuries: [], line_movement: [], weather: null };
}

describe("getGameFlagSummary", () => {
  it("returns zero counts for an empty game list", () => {
    expect(getGameFlagSummary([])).toEqual({ injuries: 0, lineMovement: 0, weather: 0 });
  });

  it("returns zero counts when no games have any flags", () => {
    expect(getGameFlagSummary([bare(), bare()])).toEqual({
      injuries: 0,
      lineMovement: 0,
      weather: 0,
    });
  });

  it("counts injury flags across multiple games", () => {
    const summary = getGameFlagSummary([
      { ...bare(), away_injuries: [injury] },
      { ...bare(), home_injuries: [injury] },
      bare(),
    ]);
    expect(summary.injuries).toBe(2);
    expect(summary.lineMovement).toBe(0);
    expect(summary.weather).toBe(0);
  });

  it("counts line movement flags across multiple games", () => {
    const summary = getGameFlagSummary([
      { ...bare(), line_movement: [bigMove] },
      { ...bare(), line_movement: [bigMove] },
      bare(),
    ]);
    expect(summary.lineMovement).toBe(2);
    expect(summary.injuries).toBe(0);
    expect(summary.weather).toBe(0);
  });

  it("counts weather flags across multiple games", () => {
    const summary = getGameFlagSummary([{ ...bare(), weather }, bare()]);
    expect(summary.weather).toBe(1);
    expect(summary.injuries).toBe(0);
    expect(summary.lineMovement).toBe(0);
  });

  it("counts all three flag types simultaneously across different games", () => {
    const summary = getGameFlagSummary([
      { away_injuries: [injury], home_injuries: [], line_movement: [bigMove], weather },
      { away_injuries: [], home_injuries: [injury], line_movement: [], weather },
      { away_injuries: [], home_injuries: [], line_movement: [bigMove], weather: null },
    ]);
    expect(summary.injuries).toBe(2);
    expect(summary.lineMovement).toBe(2);
    expect(summary.weather).toBe(2);
  });

  it("counts a game with injuries on both teams as one injury flag", () => {
    const summary = getGameFlagSummary([
      { away_injuries: [injury], home_injuries: [injury], line_movement: [], weather: null },
    ]);
    expect(summary.injuries).toBe(1);
  });

  it("only counts games passed in, reflecting a filtered list", () => {
    const allGames = [
      { ...bare(), away_injuries: [injury] },
      bare(),
      bare(),
    ];
    expect(getGameFlagSummary(allGames).injuries).toBe(1);
    expect(getGameFlagSummary(allGames.slice(1)).injuries).toBe(0);
  });
});
