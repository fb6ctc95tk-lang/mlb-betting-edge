"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";

type Odds = {
  sportsbook: string;
  away_moneyline: number;
  away_implied_probability: number;
  home_moneyline: number;
  home_implied_probability: number;
  recorded_at: string;
};

type Game = {
  game_id: number;
  game_date: string;
  game_time: string | null;
  away_team: string;
  home_team: string;
  away_pitcher: string | null;
  home_pitcher: string | null;
  away_record: string | null;
  home_record: string | null;
  status: string;
  odds: Odds[];
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

const cellStyle: CSSProperties = {
  border: "1px solid #ccc",
  padding: "8px",
  textAlign: "left",
};

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

export default function Home() {
  const [games, setGames] = useState<Game[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [movement, setMovement] = useState<Movement[] | null>(null);
  const [movementError, setMovementError] = useState<string | null>(null);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;

    fetch(`${apiUrl}/games/today-with-odds`)
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

    fetch(`${apiUrl}/odds/movement`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Request failed with status ${res.status}`);
        }
        return res.json();
      })
      .then((data: Movement[]) => setMovement(data))
      .catch((err) => {
        setMovementError(err instanceof Error ? err.message : "Unknown error");
      });
  }, []);

  return (
    <main style={{ padding: "2rem", fontFamily: "Arial, sans-serif" }}>
      <h1>MLB Betting Edge</h1>

      <h2 style={{ marginTop: "1.5rem" }}>Today&apos;s MLB Games</h2>

      {error && <p style={{ color: "red" }}>Error loading games: {error}</p>}

      {!error && games === null && <p>Loading games...</p>}

      {!error && games !== null && games.length === 0 && (
        <p>No games scheduled for today.</p>
      )}

      {!error && games !== null && games.length > 0 && (
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th style={cellStyle}>Away Team</th>
              <th style={cellStyle}>Home Team</th>
              <th style={cellStyle}>Game Time</th>
              <th style={cellStyle}>Status</th>
              <th style={cellStyle}>Away Pitcher</th>
              <th style={cellStyle}>Home Pitcher</th>
              <th style={cellStyle}>Away Record</th>
              <th style={cellStyle}>Home Record</th>
              <th style={cellStyle}>Bet365 Moneyline (Away / Home)</th>
              <th style={cellStyle}>Bet365 Implied Prob (Away / Home)</th>
              <th style={cellStyle}>DraftKings Moneyline (Away / Home)</th>
              <th style={cellStyle}>DraftKings Implied Prob (Away / Home)</th>
            </tr>
          </thead>
          <tbody>
            {games.map((game) => {
              const bet365 = findOdds(game, "Bet365");
              const draftKings = findOdds(game, "DraftKings");

              return (
                <tr key={game.game_id}>
                  <td style={cellStyle}>{game.away_team}</td>
                  <td style={cellStyle}>{game.home_team}</td>
                  <td style={cellStyle}>
                    {game.game_time ? `${game.game_time} UTC` : "TBD"}
                  </td>
                  <td style={cellStyle}>{game.status.replace("_", " ")}</td>
                  <td style={cellStyle}>{game.away_pitcher ?? "-"}</td>
                  <td style={cellStyle}>{game.home_pitcher ?? "-"}</td>
                  <td style={cellStyle}>{game.away_record ?? "-"}</td>
                  <td style={cellStyle}>{game.home_record ?? "-"}</td>
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
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <h2 style={{ marginTop: "2.5rem" }}>Line Movement</h2>

      {movementError && (
        <p style={{ color: "red" }}>
          Error loading line movement: {movementError}
        </p>
      )}

      {!movementError && movement === null && <p>Loading line movement...</p>}

      {!movementError && movement !== null && movement.length === 0 && (
        <p>No line movement data available.</p>
      )}

      {!movementError && movement !== null && movement.length > 0 && (
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
            {movement.map((row, i) => (
              <tr key={i}>
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
