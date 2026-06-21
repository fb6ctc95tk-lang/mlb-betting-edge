"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import DataQualityCard from "./components/DataQualityCard";
import IngestionStatusCard from "./components/IngestionStatusCard";
import { applyFilters } from "../lib/gameFilters";
import { getGameFlags } from "../lib/gameFlags";
import { getGameFlagSummary } from "../lib/gameFlagSummary";
import ResearchFlags from "../components/ResearchFlags";

type Odds = {
  sportsbook: string;
  away_moneyline: number;
  away_implied_probability: number;
  home_moneyline: number;
  home_implied_probability: number;
};

type Movement = {
  game_id: number;
  sportsbook: string;
  team: string;
  side: string;
  opening_moneyline: number;
  latest_moneyline: number;
  movement: number;
  opening_timestamp: string;
  latest_timestamp: string;
};

type TeamForm = {
  last_10_games_count: number;
  last_10_wins: number;
  last_10_losses: number;
  last_10_record: string;
  last_10_run_diff: number;
};

type TeamStreak = {
  streak_type: string | null;
  streak_count: number;
  streak_label: string;
};

type TeamSplits = {
  road_record?: string;
  road_wins?: number;
  road_losses?: number;
  home_record?: string;
  home_wins?: number;
  home_losses?: number;
};

type Injury = {
  player_name: string;
  injury_status: string | null;
  injury_description: string | null;
};

type Bullpen = {
  previous_game_date: string | null;
  bullpen_innings_last_game: number | null;
  played_yesterday: boolean;
};

type Weather = {
  temperature: number | null;
  wind_speed: number | null;
  wind_direction: number | null;
  precipitation_chance: number | null;
};

type Game = {
  game_id: number;
  game_date: string;
  game_time: string | null;
  status: string;
  away_team: string;
  home_team: string;
  away_pitcher: string | null;
  home_pitcher: string | null;
  away_record: string | null;
  home_record: string | null;
  away_team_form: TeamForm | null;
  home_team_form: TeamForm | null;
  away_team_streak: TeamStreak | null;
  home_team_streak: TeamStreak | null;
  away_team_splits: TeamSplits | null;
  home_team_splits: TeamSplits | null;
  odds: Odds[];
  line_movement: Movement[];
  weather: Weather | null;
  away_injuries: Injury[];
  home_injuries: Injury[];
  away_bullpen: Bullpen | null;
  home_bullpen: Bullpen | null;
};

const cellStyle: CSSProperties = {
  border: "1px solid #ccc",
  padding: "8px",
  textAlign: "left",
};

const WORKSPACE_STORAGE_KEY = "mlb_workspace_ids";
const NOTES_STORAGE_KEY = "mlb_workspace_notes";

function findOdds(game: Game, sportsbook: string): Odds | undefined {
  return game.odds.find((o) => o.sportsbook === sportsbook);
}

function formatMoneyline(value: number): string {
  return value > 0 ? `+${value}` : `${value}`;
}

function formatProbability(value: number): string {
  return `${value.toFixed(2)}%`;
}

function formatTimestamp(ts: string): string {
  return new Date(ts).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function movementColor(value: number): string {
  if (value > 0) return "green";
  if (value < 0) return "crimson";
  return "#888";
}

function formatTeamForm(form: TeamForm | null): string {
  if (!form || form.last_10_games_count === 0) return "-";
  const n = form.last_10_games_count;
  const label = n < 10 ? `Last ${n}` : "Last 10";
  const sign = form.last_10_run_diff >= 0 ? "+" : "";
  return `${label}: ${form.last_10_record}, Run Diff: ${sign}${form.last_10_run_diff}`;
}

function degreesToCompass(deg: number): string {
  const dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  return dirs[Math.round(deg / 45) % 8];
}

function WeatherCell({ weather }: { weather: Weather | null }) {
  if (!weather) {
    return <span style={{ color: "#888" }}>Weather unavailable</span>;
  }
  const lines: string[] = [];
  if (weather.temperature !== null) lines.push(`${Math.round(weather.temperature)}°F`);
  if (weather.wind_speed !== null) {
    const dir = weather.wind_direction !== null ? ` ${degreesToCompass(weather.wind_direction)}` : "";
    lines.push(`${Math.round(weather.wind_speed)} mph${dir}`);
  }
  if (weather.precipitation_chance !== null) lines.push(`${weather.precipitation_chance}% precip`);
  if (lines.length === 0) return <span style={{ color: "#888" }}>Weather unavailable</span>;
  return <>{lines.map((l, i) => <div key={i}>{l}</div>)}</>;
}

function formatBullpenDate(dateStr: string, playedYesterday: boolean): string {
  const d = new Date(`${dateStr}T12:00:00`);
  const label = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return playedYesterday ? `${label} (yesterday)` : label;
}

function BullpenCell({ bullpen }: { bullpen: Bullpen | null }) {
  if (!bullpen || bullpen.previous_game_date === null) {
    return <span style={{ color: "#888" }}>-</span>;
  }
  const ip = bullpen.bullpen_innings_last_game !== null
    ? bullpen.bullpen_innings_last_game.toFixed(1)
    : "-";
  const dateLabel = formatBullpenDate(bullpen.previous_game_date, bullpen.played_yesterday);
  return (
    <>
      <div>{ip} IP</div>
      <div style={{ fontSize: "0.85em", color: bullpen.played_yesterday ? "crimson" : "#555" }}>
        {dateLabel}
      </div>
    </>
  );
}

function InjuryCell({ injuries }: { injuries: Injury[] }) {
  if (!injuries || injuries.length === 0) {
    return <span style={{ color: "#888" }}>-</span>;
  }
  return (
    <>
      {injuries.map((inj, i) => (
        <div key={i} style={{ marginBottom: i < injuries.length - 1 ? "6px" : 0 }}>
          <div style={{ fontWeight: "bold", fontSize: "0.85em" }}>{inj.player_name}</div>
          {inj.injury_status && (
            <div style={{ fontSize: "0.8em", color: "crimson" }}>{inj.injury_status}</div>
          )}
          {inj.injury_description && (
            <div style={{ fontSize: "0.8em", color: "#555" }}>{inj.injury_description}</div>
          )}
        </div>
      ))}
    </>
  );
}

function compWeather(weather: Weather | null): string {
  if (!weather) return "—";
  const parts: string[] = [];
  if (weather.temperature !== null) parts.push(`${Math.round(weather.temperature)}°F`);
  if (weather.wind_speed !== null) {
    const dir = weather.wind_direction !== null ? ` ${degreesToCompass(weather.wind_direction)}` : "";
    parts.push(`${Math.round(weather.wind_speed)} mph${dir}`);
  }
  if (weather.precipitation_chance !== null) parts.push(`${weather.precipitation_chance}% precip`);
  return parts.length > 0 ? parts.join(", ") : "—";
}

function compBullpen(bullpen: Bullpen | null): string {
  if (!bullpen || bullpen.previous_game_date === null) return "—";
  const ip = bullpen.bullpen_innings_last_game !== null
    ? bullpen.bullpen_innings_last_game.toFixed(1)
    : "—";
  return `${ip} IP (${formatBullpenDate(bullpen.previous_game_date, bullpen.played_yesterday)})`;
}

function compInjuries(injuries: Injury[]): string {
  if (injuries.length === 0) return "None";
  return injuries.map((i) => i.player_name).join(", ");
}

function compOdds(game: Game, sportsbook: string): string {
  const o = findOdds(game, sportsbook);
  if (!o) return "—";
  return `${formatMoneyline(o.away_moneyline)} / ${formatMoneyline(o.home_moneyline)}`;
}

function compMaxMove(game: Game): string {
  if (game.line_movement.length === 0) return "—";
  const max = Math.max(...game.line_movement.map((m) => Math.abs(m.movement)));
  return max === 0 ? "0" : `+${Math.round(max)}`;
}

function SectionRow({ label }: { label: string }) {
  return (
    <tr>
      <td colSpan={3} style={{
        ...cellStyle,
        background: "#ebebeb",
        fontWeight: "bold",
        fontSize: "0.78em",
        color: "#555",
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        paddingTop: "10px",
      }}>
        {label}
      </td>
    </tr>
  );
}

function ComparisonTable({ a, b }: { a: Game; b: Game }) {
  const labelCell: CSSProperties = { ...cellStyle, fontWeight: "bold", background: "#f5f5f5", whiteSpace: "nowrap" };
  const headerCell: CSSProperties = { ...cellStyle, background: "#e8f0fe", fontWeight: "bold", textAlign: "center" };
  const noFlags = <span style={{ color: "#888" }}>None</span>;
  return (
    <div style={{ marginTop: "1rem", overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th style={labelCell}></th>
            <th style={headerCell}>{a.away_team} @ {a.home_team}</th>
            <th style={headerCell}>{b.away_team} @ {b.home_team}</th>
          </tr>
        </thead>
        <tbody>
          <SectionRow label="Research Flags" />
          <tr>
            <td style={labelCell}>Flags</td>
            <td style={cellStyle}><ResearchFlags flags={getGameFlags(a)} emptyState={noFlags} /></td>
            <td style={cellStyle}><ResearchFlags flags={getGameFlags(b)} emptyState={noFlags} /></td>
          </tr>

          <SectionRow label="Matchup" />
          <tr>
            <td style={labelCell}>Away Record</td>
            <td style={cellStyle}>{a.away_record ?? "—"}</td>
            <td style={cellStyle}>{b.away_record ?? "—"}</td>
          </tr>
          <tr>
            <td style={labelCell}>Home Record</td>
            <td style={cellStyle}>{a.home_record ?? "—"}</td>
            <td style={cellStyle}>{b.home_record ?? "—"}</td>
          </tr>

          <SectionRow label="Pitchers" />
          <tr>
            <td style={labelCell}>Away Pitcher</td>
            <td style={cellStyle}>{a.away_pitcher ?? "TBD"}</td>
            <td style={cellStyle}>{b.away_pitcher ?? "TBD"}</td>
          </tr>
          <tr>
            <td style={labelCell}>Home Pitcher</td>
            <td style={cellStyle}>{a.home_pitcher ?? "TBD"}</td>
            <td style={cellStyle}>{b.home_pitcher ?? "TBD"}</td>
          </tr>

          <SectionRow label="Recent Form" />
          <tr>
            <td style={labelCell}>Away Last 10</td>
            <td style={cellStyle}>{formatTeamForm(a.away_team_form)}</td>
            <td style={cellStyle}>{formatTeamForm(b.away_team_form)}</td>
          </tr>
          <tr>
            <td style={labelCell}>Home Last 10</td>
            <td style={cellStyle}>{formatTeamForm(a.home_team_form)}</td>
            <td style={cellStyle}>{formatTeamForm(b.home_team_form)}</td>
          </tr>
          <tr>
            <td style={labelCell}>Away Streak</td>
            <td style={cellStyle}>{a.away_team_streak?.streak_label ?? "—"}</td>
            <td style={cellStyle}>{b.away_team_streak?.streak_label ?? "—"}</td>
          </tr>
          <tr>
            <td style={labelCell}>Home Streak</td>
            <td style={cellStyle}>{a.home_team_streak?.streak_label ?? "—"}</td>
            <td style={cellStyle}>{b.home_team_streak?.streak_label ?? "—"}</td>
          </tr>
          <tr>
            <td style={labelCell}>Away Road Record</td>
            <td style={cellStyle}>{a.away_team_splits?.road_record ?? "—"}</td>
            <td style={cellStyle}>{b.away_team_splits?.road_record ?? "—"}</td>
          </tr>
          <tr>
            <td style={labelCell}>Home Home Record</td>
            <td style={cellStyle}>{a.home_team_splits?.home_record ?? "—"}</td>
            <td style={cellStyle}>{b.home_team_splits?.home_record ?? "—"}</td>
          </tr>

          <SectionRow label="Weather" />
          <tr>
            <td style={labelCell}>Weather</td>
            <td style={cellStyle}>{compWeather(a.weather)}</td>
            <td style={cellStyle}>{compWeather(b.weather)}</td>
          </tr>

          <SectionRow label="Bullpen" />
          <tr>
            <td style={labelCell}>Away Bullpen</td>
            <td style={cellStyle}>{compBullpen(a.away_bullpen)}</td>
            <td style={cellStyle}>{compBullpen(b.away_bullpen)}</td>
          </tr>
          <tr>
            <td style={labelCell}>Home Bullpen</td>
            <td style={cellStyle}>{compBullpen(a.home_bullpen)}</td>
            <td style={cellStyle}>{compBullpen(b.home_bullpen)}</td>
          </tr>

          <SectionRow label="Injuries" />
          <tr>
            <td style={labelCell}>Away Injuries</td>
            <td style={cellStyle}>{compInjuries(a.away_injuries)}</td>
            <td style={cellStyle}>{compInjuries(b.away_injuries)}</td>
          </tr>
          <tr>
            <td style={labelCell}>Home Injuries</td>
            <td style={cellStyle}>{compInjuries(a.home_injuries)}</td>
            <td style={cellStyle}>{compInjuries(b.home_injuries)}</td>
          </tr>

          <SectionRow label="Odds" />
          <tr>
            <td style={labelCell}>Bet365 (Away / Home)</td>
            <td style={cellStyle}>{compOdds(a, "Bet365")}</td>
            <td style={cellStyle}>{compOdds(b, "Bet365")}</td>
          </tr>
          <tr>
            <td style={labelCell}>DraftKings (Away / Home)</td>
            <td style={cellStyle}>{compOdds(a, "DraftKings")}</td>
            <td style={cellStyle}>{compOdds(b, "DraftKings")}</td>
          </tr>

          <SectionRow label="Line Movement" />
          <tr>
            <td style={labelCell}>Max Line Move</td>
            <td style={cellStyle}>{compMaxMove(a)}</td>
            <td style={cellStyle}>{compMaxMove(b)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export default function Home() {
  const [games, setGames] = useState<Game[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [filterHasInjuries, setFilterHasInjuries] = useState(false);
  const [filterHasLineMovement, setFilterHasLineMovement] = useState(false);
  const [filterHasWeather, setFilterHasWeather] = useState(false);
  const [sortBy, setSortBy] = useState<"default" | "largest_movement">("default");
  const [workspaceIds, setWorkspaceIds] = useState<Set<number>>(new Set());
  const [compareIdA, setCompareIdA] = useState<number | null>(null);
  const [compareIdB, setCompareIdB] = useState<number | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});

  useEffect(() => {
    function loadFromStorage() {
      try {
        const raw = localStorage.getItem(WORKSPACE_STORAGE_KEY);
        if (raw) setWorkspaceIds(new Set(JSON.parse(raw) as number[]));
      } catch {}
      try {
        const raw = localStorage.getItem(NOTES_STORAGE_KEY);
        if (raw) setNotes(JSON.parse(raw) as Record<number, string>);
      } catch {}
    }
    loadFromStorage();
  }, []);

  function addToWorkspace(gameId: number) {
    setWorkspaceIds((prev) => {
      const next = new Set([...prev, gameId]);
      try { localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify([...next])); } catch {}
      return next;
    });
  }

  function updateNote(gameId: number, text: string) {
    setNotes((prev) => {
      const next = { ...prev };
      if (text) {
        next[gameId] = text;
      } else {
        delete next[gameId];
      }
      try { localStorage.setItem(NOTES_STORAGE_KEY, JSON.stringify(next)); } catch {}
      return next;
    });
  }

  function removeFromWorkspace(gameId: number) {
    setWorkspaceIds((prev) => {
      const next = new Set(prev);
      next.delete(gameId);
      try { localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify([...next])); } catch {}
      return next;
    });
    setCompareIdA((prev) => (prev === gameId ? null : prev));
    setCompareIdB((prev) => (prev === gameId ? null : prev));
  }

  useEffect(() => {
    function autoSelect() {
      const ws = (games ?? []).filter((g) => workspaceIds.has(g.game_id));
      if (ws.length === 2) {
        setCompareIdA(ws[0].game_id);
        setCompareIdB(ws[1].game_id);
      }
    }
    autoSelect();
  }, [games, workspaceIds]);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    fetch(`${apiUrl}/research/available-dates`)
      .then((res) => res.json())
      .then((data) => setAvailableDates(data.available_dates ?? []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    const url = selectedDate
      ? `${apiUrl}/research/date/${selectedDate}`
      : `${apiUrl}/research/today`;

    function loadGames() {
      setGames(null);
      setError(null);
      fetch(url)
        .then((res) => {
          if (!res.ok) {
            throw new Error(`Request failed with status ${res.status}`);
          }
          return res.json();
        })
        .then((data: Game[]) => setGames(data))
        .catch((err) => {
          setError(err instanceof Error ? err.message : "Unknown error");
        });
    }
    loadGames();
  }, [selectedDate]);

  let displayedGames: Game[] = applyFilters(games ?? [], {
    hasInjuries: filterHasInjuries,
    hasLineMovement: filterHasLineMovement,
    hasWeather: filterHasWeather,
  });
  if (sortBy === "largest_movement") {
    displayedGames = [...displayedGames].sort((a, b) => {
      const maxA = a.line_movement.length > 0
        ? Math.max(...a.line_movement.map((m) => Math.abs(m.movement)))
        : 0;
      const maxB = b.line_movement.length > 0
        ? Math.max(...b.line_movement.map((m) => Math.abs(m.movement)))
        : 0;
      return maxB - maxA;
    });
  }
  const flagSummary = getGameFlagSummary(displayedGames);
  const allMovement = displayedGames.flatMap((g) => g.line_movement);
  const workspaceGames = (games ?? []).filter((g) => workspaceIds.has(g.game_id));
  const compareGameA = compareIdA !== null ? (games ?? []).find((g) => g.game_id === compareIdA) ?? null : null;
  const compareGameB = compareIdB !== null ? (games ?? []).find((g) => g.game_id === compareIdB) ?? null : null;

  return (
    <main style={{ padding: "2rem", fontFamily: "Arial, sans-serif" }}>
      <h1>MLB Betting Edge</h1>

      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
        <IngestionStatusCard />
        <DataQualityCard />
      </div>

      <div style={{ marginTop: "1.5rem" }}>
        <label htmlFor="date-picker" style={{ marginRight: "0.5rem", fontWeight: "bold" }}>
          Date:
        </label>
        <select
          id="date-picker"
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          style={{ padding: "4px", fontSize: "1rem" }}
        >
          <option value="">Today</option>
          {availableDates.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
        {selectedDate && (
          <button
            onClick={() => setSelectedDate("")}
            style={{ marginLeft: "0.75rem", padding: "4px 10px", cursor: "pointer" }}
          >
            Back to Today
          </button>
        )}
      </div>

      <div style={{ marginTop: "1rem", display: "flex", gap: "1.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <div>
          <span style={{ fontWeight: "bold", marginRight: "0.5rem" }}>Filter:</span>
          <label>
            <input
              type="checkbox"
              checked={filterHasInjuries}
              onChange={(e) => setFilterHasInjuries(e.target.checked)}
              style={{ marginRight: "4px" }}
            />
            Has Injuries
          </label>
          <label style={{ marginLeft: "1rem" }}>
            <input
              type="checkbox"
              checked={filterHasLineMovement}
              onChange={(e) => setFilterHasLineMovement(e.target.checked)}
              style={{ marginRight: "4px" }}
            />
            Has Significant Line Movement
          </label>
          <label style={{ marginLeft: "1rem" }}>
            <input
              type="checkbox"
              checked={filterHasWeather}
              onChange={(e) => setFilterHasWeather(e.target.checked)}
              style={{ marginRight: "4px" }}
            />
            Has Weather Context
          </label>
        </div>
        <div>
          <label htmlFor="sort-picker" style={{ fontWeight: "bold", marginRight: "0.5rem" }}>
            Sort:
          </label>
          <select
            id="sort-picker"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as "default" | "largest_movement")}
            style={{ padding: "4px", fontSize: "1rem" }}
          >
            <option value="default">Default</option>
            <option value="largest_movement">Largest Line Movement</option>
          </select>
        </div>
        {games !== null && (
          <div style={{ fontSize: "0.88em", color: "#555", borderLeft: "1px solid #ddd", paddingLeft: "1.5rem" }}>
            <span style={{ fontWeight: "bold", marginRight: "0.75rem" }}>Flags:</span>
            <span style={{ marginRight: "0.75rem" }}>⚠ {flagSummary.injuries}</span>
            <span style={{ marginRight: "0.75rem" }}>📈 {flagSummary.lineMovement}</span>
            <span>🌬 {flagSummary.weather}</span>
          </div>
        )}
        <div style={{ marginLeft: "auto" }}>
          <span style={{ fontWeight: "bold" }}>Workspace ({workspaceIds.size})</span>
        </div>
      </div>

      {workspaceGames.length > 0 && (
        <div style={{ marginTop: "1rem", border: "1px solid #999", padding: "0.75rem 1rem", background: "#fafafa" }}>
          <strong>Research Workspace</strong>
          <div style={{ marginTop: "0.5rem" }}>
            {workspaceGames.map((game) => (
              <div key={game.game_id} style={{ padding: "6px 0", borderBottom: "1px solid #eee" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
                  <span style={{ fontWeight: "bold", minWidth: "120px" }}>
                    {game.away_team} @ {game.home_team}
                  </span>
                  <span style={{ color: "#555", fontSize: "0.9em" }}>{game.game_date}</span>
                  <Link href={`/game/${game.game_id}`} style={{ fontSize: "0.85em" }}>View</Link>
                  <button
                    onClick={() => removeFromWorkspace(game.game_id)}
                    style={{ padding: "2px 8px", cursor: "pointer", fontSize: "0.85em" }}
                  >
                    Remove
                  </button>
                </div>
                <textarea
                  value={notes[game.game_id] ?? ""}
                  onChange={(e) => updateNote(game.game_id, e.target.value)}
                  maxLength={1000}
                  placeholder="Notes..."
                  rows={2}
                  style={{
                    display: "block",
                    width: "100%",
                    marginTop: "4px",
                    padding: "4px",
                    fontSize: "0.85em",
                    fontFamily: "inherit",
                    border: "1px solid #ddd",
                    background: "#fff",
                    resize: "vertical",
                    boxSizing: "border-box",
                  }}
                />
              </div>
            ))}
          </div>
          {workspaceGames.length >= 2 && (
            <div style={{ marginTop: "0.75rem", borderTop: "1px solid #ddd", paddingTop: "0.75rem" }}>
              <span style={{ fontWeight: "bold", marginRight: "0.75rem" }}>Compare:</span>
              <select
                value={compareIdA ?? ""}
                onChange={(e) => setCompareIdA(e.target.value ? Number(e.target.value) : null)}
                style={{ padding: "3px", marginRight: "0.5rem" }}
              >
                <option value="">— Game A —</option>
                {workspaceGames.map((g) => (
                  <option key={g.game_id} value={g.game_id}>
                    {g.away_team} @ {g.home_team}
                  </option>
                ))}
              </select>
              <span style={{ marginRight: "0.5rem" }}>vs</span>
              <select
                value={compareIdB ?? ""}
                onChange={(e) => setCompareIdB(e.target.value ? Number(e.target.value) : null)}
                style={{ padding: "3px" }}
              >
                <option value="">— Game B —</option>
                {workspaceGames.map((g) => (
                  <option key={g.game_id} value={g.game_id}>
                    {g.away_team} @ {g.home_team}
                  </option>
                ))}
              </select>
            </div>
          )}
          {compareGameA && compareGameB && (
            <ComparisonTable a={compareGameA} b={compareGameB} />
          )}
        </div>
      )}

      <h2 style={{ marginTop: "1rem" }}>
        {selectedDate ? `Games for ${selectedDate}` : "Today’s MLB Games"}
      </h2>

      {error && <p style={{ color: "red" }}>Error loading games: {error}</p>}

      {!error && games === null && <p>Loading games...</p>}

      {!error && games !== null && games.length === 0 && (
        <p>No games found for this date.</p>
      )}

      {!error && games !== null && games.length > 0 && displayedGames.length === 0 && (
        <p>No games match the current filter.</p>
      )}

      {!error && games !== null && displayedGames.length > 0 && (
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th style={cellStyle}>Detail</th>
              <th style={cellStyle}>Flags</th>
              <th style={cellStyle}>Away Team</th>
              <th style={cellStyle}>Home Team</th>
              <th style={cellStyle}>Game Time</th>
              <th style={cellStyle}>Status</th>
              <th style={cellStyle}>Away Pitcher</th>
              <th style={cellStyle}>Home Pitcher</th>
              <th style={cellStyle}>Away Record</th>
              <th style={cellStyle}>Home Record</th>
              <th style={cellStyle}>Away Streak</th>
              <th style={cellStyle}>Home Streak</th>
              <th style={cellStyle}>Away Road Record</th>
              <th style={cellStyle}>Home Record (Home)</th>
              <th style={cellStyle}>Away Last 10</th>
              <th style={cellStyle}>Home Last 10</th>
              <th style={cellStyle}>Bet365 Moneyline (Away / Home)</th>
              <th style={cellStyle}>Bet365 Implied Prob (Away / Home)</th>
              <th style={cellStyle}>DraftKings Moneyline (Away / Home)</th>
              <th style={cellStyle}>DraftKings Implied Prob (Away / Home)</th>
              <th style={cellStyle}>Weather</th>
              <th style={cellStyle}>Away Injuries</th>
              <th style={cellStyle}>Home Injuries</th>
              <th style={cellStyle}>Away Bullpen (Last Game)</th>
              <th style={cellStyle}>Home Bullpen (Last Game)</th>
            </tr>
          </thead>
          <tbody>
            {displayedGames.map((game) => {
              const bet365 = findOdds(game, "Bet365");
              const draftKings = findOdds(game, "DraftKings");
              const flags = getGameFlags(game);

              return (
                <tr key={game.game_id}>
                  <td style={{ ...cellStyle, whiteSpace: "nowrap" }}>
                    <Link href={`/game/${game.game_id}`}>View</Link>
                    <br />
                    <button
                      onClick={() => addToWorkspace(game.game_id)}
                      style={{
                        marginTop: "4px",
                        padding: "2px 6px",
                        cursor: "pointer",
                        fontSize: "0.82em",
                        background: workspaceIds.has(game.game_id) ? "#e8f5e9" : undefined,
                      }}
                    >
                      {workspaceIds.has(game.game_id) ? "✓ Workspace" : "+ Workspace"}
                    </button>
                  </td>
                  <td style={{ ...cellStyle, whiteSpace: "nowrap" }}>
                    <ResearchFlags
                      flags={flags}
                      emptyState={<span style={{ color: "#aaa" }}>—</span>}
                      compact
                    />
                  </td>
                  <td style={{ ...cellStyle, fontWeight: "600" }}>{game.away_team}</td>
                  <td style={{ ...cellStyle, fontWeight: "600" }}>{game.home_team}</td>
                  <td style={cellStyle}>
                    {game.game_time ? `${game.game_time} UTC` : "TBD"}
                  </td>
                  <td style={cellStyle}>{game.status.replace("_", " ")}</td>
                  <td style={cellStyle}>{game.away_pitcher ?? "-"}</td>
                  <td style={cellStyle}>{game.home_pitcher ?? "-"}</td>
                  <td style={cellStyle}>{game.away_record ?? "-"}</td>
                  <td style={cellStyle}>{game.home_record ?? "-"}</td>
                  <td style={cellStyle}>{game.away_team_streak?.streak_label ?? "-"}</td>
                  <td style={cellStyle}>{game.home_team_streak?.streak_label ?? "-"}</td>
                  <td style={cellStyle}>{game.away_team_splits?.road_record ?? "-"}</td>
                  <td style={cellStyle}>{game.home_team_splits?.home_record ?? "-"}</td>
                  <td style={cellStyle}>{formatTeamForm(game.away_team_form)}</td>
                  <td style={cellStyle}>{formatTeamForm(game.home_team_form)}</td>
                  <td style={cellStyle}>
                    {bet365
                      ? `${formatMoneyline(bet365.away_moneyline)} / ${formatMoneyline(bet365.home_moneyline)}`
                      : "-"}
                  </td>
                  <td style={cellStyle}>
                    {bet365
                      ? `${formatProbability(bet365.away_implied_probability)} / ${formatProbability(bet365.home_implied_probability)}`
                      : "-"}
                  </td>
                  <td style={cellStyle}>
                    {draftKings
                      ? `${formatMoneyline(draftKings.away_moneyline)} / ${formatMoneyline(draftKings.home_moneyline)}`
                      : "-"}
                  </td>
                  <td style={cellStyle}>
                    {draftKings
                      ? `${formatProbability(draftKings.away_implied_probability)} / ${formatProbability(draftKings.home_implied_probability)}`
                      : "-"}
                  </td>
                  <td style={cellStyle}>
                    <WeatherCell weather={game.weather} />
                  </td>
                  <td style={cellStyle}>
                    <InjuryCell injuries={game.away_injuries} />
                  </td>
                  <td style={cellStyle}>
                    <InjuryCell injuries={game.home_injuries} />
                  </td>
                  <td style={cellStyle}>
                    <BullpenCell bullpen={game.away_bullpen} />
                  </td>
                  <td style={cellStyle}>
                    <BullpenCell bullpen={game.home_bullpen} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <h2 style={{ marginTop: "2.5rem" }}>Line Movement</h2>

      {error && (
        <p style={{ color: "red" }}>Error loading line movement: {error}</p>
      )}

      {!error && games === null && <p>Loading line movement...</p>}

      {!error && games !== null && allMovement.length === 0 && (
        <p>No line movement data available.</p>
      )}

      {!error && games !== null && allMovement.length > 0 && (
        <table style={{ borderCollapse: "collapse", width: "100%", marginTop: "0.5rem" }}>
          <thead>
            <tr>
              <th style={cellStyle}>Game ID</th>
              <th style={cellStyle}>Sportsbook</th>
              <th style={cellStyle}>Team</th>
              <th style={cellStyle}>Side</th>
              <th style={cellStyle}>Opening ML</th>
              <th style={cellStyle}>Latest ML</th>
              <th style={cellStyle}>Movement</th>
              <th style={cellStyle}>Opening Time</th>
              <th style={cellStyle}>Latest Time</th>
            </tr>
          </thead>
          <tbody>
            {allMovement.map((row) => (
              <tr key={`${row.game_id}-${row.sportsbook}-${row.side}`}>
                <td style={cellStyle}>{row.game_id}</td>
                <td style={cellStyle}>{row.sportsbook}</td>
                <td style={cellStyle}>{row.team}</td>
                <td style={cellStyle}>{row.side}</td>
                <td style={cellStyle}>{formatMoneyline(row.opening_moneyline)}</td>
                <td style={cellStyle}>{formatMoneyline(row.latest_moneyline)}</td>
                <td style={{ ...cellStyle, color: movementColor(row.movement), fontWeight: row.movement !== 0 ? "bold" : "normal" }}>
                  {formatMoneyline(row.movement)}
                </td>
                <td style={cellStyle}>{formatTimestamp(row.opening_timestamp)}</td>
                <td style={cellStyle}>{formatTimestamp(row.latest_timestamp)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
