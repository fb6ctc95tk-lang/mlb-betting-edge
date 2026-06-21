export const LINE_MOVE_THRESHOLD = 10;

export type FilterableGame = {
  away_injuries: unknown[];
  home_injuries: unknown[];
  line_movement: { movement: number }[];
  weather: unknown | null;
};

export type ActiveFilters = {
  hasInjuries: boolean;
  hasLineMovement: boolean;
  hasWeather: boolean;
};

export function applyFilters<T extends FilterableGame>(
  games: T[],
  filters: ActiveFilters
): T[] {
  let result = games;

  if (filters.hasInjuries) {
    result = result.filter(
      (g) => g.away_injuries.length > 0 || g.home_injuries.length > 0
    );
  }

  if (filters.hasLineMovement) {
    result = result.filter((g) => {
      const maxMove =
        g.line_movement.length > 0
          ? Math.max(...g.line_movement.map((m) => Math.abs(m.movement)))
          : 0;
      return maxMove >= LINE_MOVE_THRESHOLD;
    });
  }

  if (filters.hasWeather) {
    result = result.filter((g) => g.weather !== null);
  }

  return result;
}
