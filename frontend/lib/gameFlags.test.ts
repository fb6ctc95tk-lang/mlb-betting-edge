import { describe, it, expect } from "vitest";
import { getGameFlags, type GameFlag } from "./gameFlags";
import { LINE_MOVE_THRESHOLD } from "./gameFilters";

const injury = { player_name: "Test Player" };
const bigMove = { movement: LINE_MOVE_THRESHOLD };
const belowMove = { movement: LINE_MOVE_THRESHOLD - 1 };
const weather = { temperature: 72 };

function bare() {
  return { away_injuries: [], home_injuries: [], line_movement: [], weather: null };
}

function emojis(flags: GameFlag[]) {
  return flags.map((f) => f.emoji);
}

describe("getGameFlags", () => {
  it("returns no flags when no research data is present", () => {
    expect(getGameFlags(bare())).toEqual([]);
  });

  it("returns injury flag when away team has injuries", () => {
    const flags = getGameFlags({ ...bare(), away_injuries: [injury] });
    expect(flags).toHaveLength(1);
    expect(flags[0].emoji).toBe("⚠");
    expect(flags[0].label).toBe("Injuries Present");
  });

  it("returns injury flag when home team has injuries", () => {
    const flags = getGameFlags({ ...bare(), home_injuries: [injury] });
    expect(flags).toHaveLength(1);
    expect(flags[0].emoji).toBe("⚠");
  });

  it("returns injury flag when both teams have injuries", () => {
    const flags = getGameFlags({ ...bare(), away_injuries: [injury], home_injuries: [injury] });
    expect(flags).toHaveLength(1);
    expect(flags[0].emoji).toBe("⚠");
  });

  it("returns line movement flag when movement meets the threshold", () => {
    const flags = getGameFlags({ ...bare(), line_movement: [bigMove] });
    expect(flags).toHaveLength(1);
    expect(flags[0].emoji).toBe("📈");
    expect(flags[0].label).toBe("Significant Line Movement");
  });

  it("does not return line movement flag when movement is below the threshold", () => {
    expect(getGameFlags({ ...bare(), line_movement: [belowMove] })).toHaveLength(0);
  });

  it("does not return line movement flag when there is no movement data", () => {
    expect(getGameFlags(bare())).toHaveLength(0);
  });

  it("returns weather flag when weather context is present", () => {
    const flags = getGameFlags({ ...bare(), weather });
    expect(flags).toHaveLength(1);
    expect(flags[0].emoji).toBe("🌬");
    expect(flags[0].label).toBe("Weather Context");
  });

  it("does not return weather flag when weather is null", () => {
    expect(getGameFlags(bare())).toHaveLength(0);
  });

  it("returns injuries and line movement flags together", () => {
    const flags = getGameFlags({ ...bare(), away_injuries: [injury], line_movement: [bigMove] });
    expect(emojis(flags)).toEqual(["⚠", "📈"]);
  });

  it("returns injuries and weather flags together", () => {
    const flags = getGameFlags({ ...bare(), away_injuries: [injury], weather });
    expect(emojis(flags)).toEqual(["⚠", "🌬"]);
  });

  it("returns line movement and weather flags together", () => {
    const flags = getGameFlags({ ...bare(), line_movement: [bigMove], weather });
    expect(emojis(flags)).toEqual(["📈", "🌬"]);
  });

  it("returns all three flags simultaneously", () => {
    const flags = getGameFlags({
      away_injuries: [injury],
      home_injuries: [],
      line_movement: [bigMove],
      weather,
    });
    expect(emojis(flags)).toEqual(["⚠", "📈", "🌬"]);
  });

  it("each flag carries a non-empty color string", () => {
    const flags = getGameFlags({
      away_injuries: [injury],
      home_injuries: [],
      line_movement: [bigMove],
      weather,
    });
    flags.forEach((f) => expect(f.color.length).toBeGreaterThan(0));
  });
});
