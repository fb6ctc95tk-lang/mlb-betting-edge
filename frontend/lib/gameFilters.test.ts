import { describe, it, expect } from "vitest";
import { applyFilters, LINE_MOVE_THRESHOLD } from "./gameFilters";

type TestGame = {
  id: number;
  away_injuries: unknown[];
  home_injuries: unknown[];
  line_movement: { movement: number }[];
  weather: unknown | null;
};

function makeGame(overrides: Partial<TestGame> = {}): TestGame {
  return {
    id: 1,
    away_injuries: [],
    home_injuries: [],
    line_movement: [],
    weather: null,
    ...overrides,
  };
}

const injury = { player_name: "Test Player" };
const bigMove = { movement: LINE_MOVE_THRESHOLD };
const smallMove = { movement: LINE_MOVE_THRESHOLD - 1 };
const weather = { temperature: 72 };

const gameWithInjuries = makeGame({ id: 1, away_injuries: [injury] });
const gameWithLineMove = makeGame({ id: 2, line_movement: [bigMove] });
const gameWithWeather = makeGame({ id: 3, weather });
const gameWithAll = makeGame({
  id: 4,
  away_injuries: [injury],
  line_movement: [bigMove],
  weather,
});
const gameWithNone = makeGame({ id: 5 });
const gameWithSmallMove = makeGame({ id: 6, line_movement: [smallMove] });

const allGames = [
  gameWithInjuries,
  gameWithLineMove,
  gameWithWeather,
  gameWithAll,
  gameWithNone,
  gameWithSmallMove,
];

const noFilters = { hasInjuries: false, hasLineMovement: false, hasWeather: false };

describe("applyFilters", () => {
  it("returns all games when no filters are active", () => {
    expect(applyFilters(allGames, noFilters)).toEqual(allGames);
  });

  it("filters by injuries only", () => {
    const result = applyFilters(allGames, { ...noFilters, hasInjuries: true });
    expect(result).toEqual([gameWithInjuries, gameWithAll]);
  });

  it("filters by line movement only", () => {
    const result = applyFilters(allGames, { ...noFilters, hasLineMovement: true });
    expect(result).toEqual([gameWithLineMove, gameWithAll]);
  });

  it("filters by weather only", () => {
    const result = applyFilters(allGames, { ...noFilters, hasWeather: true });
    expect(result).toEqual([gameWithWeather, gameWithAll]);
  });

  it("filters by injuries AND line movement", () => {
    const result = applyFilters(allGames, {
      hasInjuries: true,
      hasLineMovement: true,
      hasWeather: false,
    });
    expect(result).toEqual([gameWithAll]);
  });

  it("filters by injuries AND weather", () => {
    const result = applyFilters(allGames, {
      hasInjuries: true,
      hasLineMovement: false,
      hasWeather: true,
    });
    expect(result).toEqual([gameWithAll]);
  });

  it("filters by line movement AND weather", () => {
    const result = applyFilters(allGames, {
      hasInjuries: false,
      hasLineMovement: true,
      hasWeather: true,
    });
    expect(result).toEqual([gameWithAll]);
  });

  it("filters by all three simultaneously", () => {
    const result = applyFilters(allGames, {
      hasInjuries: true,
      hasLineMovement: true,
      hasWeather: true,
    });
    expect(result).toEqual([gameWithAll]);
  });

  it("returns empty array when no games match all active filters", () => {
    const result = applyFilters([gameWithNone], {
      hasInjuries: true,
      hasLineMovement: true,
      hasWeather: true,
    });
    expect(result).toEqual([]);
  });

  it("excludes line movement below the threshold", () => {
    const result = applyFilters([gameWithSmallMove], {
      ...noFilters,
      hasLineMovement: true,
    });
    expect(result).toEqual([]);
  });

  it("includes line movement exactly at the threshold", () => {
    const atThreshold = makeGame({ id: 7, line_movement: [{ movement: LINE_MOVE_THRESHOLD }] });
    const result = applyFilters([atThreshold], { ...noFilters, hasLineMovement: true });
    expect(result).toEqual([atThreshold]);
  });

  it("does not mutate the input array", () => {
    const input = [gameWithNone];
    applyFilters(input, { hasInjuries: true, hasLineMovement: true, hasWeather: true });
    expect(input).toHaveLength(1);
  });
});
