"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";

type Game = {
  game_id: number;
  game_date: string;
  game_time: string | null;
  home_team: string;
  away_team: string;
  status: string;
  home_score: number | null;
  away_score: number | null;
  probable_home_pitcher: string | null;
  probable_away_pitcher: string | null;
};

const cellStyle: CSSProperties = {
  border: "1px solid #ccc",
  padding: "8px",
  textAlign: "left",
};

export default function Home() {
  const [games, setGames] = useState<Game[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;

    fetch(`${apiUrl}/games/today`)
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
  }, []);

  return (
    <main style={{ padding: "2rem", fontFamily: "Arial, sans-serif" }}>
      <h1>MLB Betting Edge</h1>
      <h2>Today&apos;s MLB Games</h2>

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
            </tr>
          </thead>
          <tbody>
            {games.map((game) => (
              <tr key={game.game_id}>
                <td style={cellStyle}>{game.away_team}</td>
                <td style={cellStyle}>{game.home_team}</td>
                <td style={cellStyle}>
                  {game.game_time ? `${game.game_time} UTC` : "TBD"}
                </td>
                <td style={cellStyle}>{game.status.replace("_", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
