"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { buildBoardEntries, getBoardResearchUrl } from "../../lib/marketResearchBoard";
import type { BoardEntry } from "../../lib/marketResearchBoard";

type Odds = {
  sportsbook: string;
  away_moneyline: number;
  away_implied_probability: number;
  home_moneyline: number;
  home_implied_probability: number;
};

type TeamForm = {
  last_10_wins: number;
  last_10_games_count: number;
};

type ResearchGame = {
  game_id: number;
  game_date: string;
  game_time: string | null;
  status: string;
  away_team: string;
  home_team: string;
  away_team_form: TeamForm | null;
  home_team_form: TeamForm | null;
  odds: Odds[];
};

function formatMoneyline(value: number): string {
  return value > 0 ? `+${value}` : `${value}`;
}

function formatProbability(value: number): string {
  return `${value.toFixed(2)}%`;
}

const cardStyle: CSSProperties = {
  border: "1px solid #d1d5db",
  marginBottom: "1.25rem",
  background: "#fff",
};

const cardHeaderStyle: CSSProperties = {
  padding: "0.75rem 1rem",
  borderBottom: "1px solid #e5e7eb",
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  flexWrap: "wrap",
  gap: "0.5rem",
  background: "#f9fafb",
};

const cardBodyStyle: CSSProperties = {
  padding: "0.75rem 1rem",
};

function DateSelector({
  selectedDate,
  availableDates,
  onSelect,
}: {
  selectedDate: string;
  availableDates: string[];
  onSelect: (date: string) => void;
}) {
  return (
    <div
      style={{
        marginTop: "0.75rem",
        display: "flex",
        alignItems: "center",
        gap: "0.75rem",
        flexWrap: "wrap",
      }}
    >
      <label htmlFor="board-date-picker" style={{ fontWeight: "bold" }}>
        Date:
      </label>
      <select
        id="board-date-picker"
        value={selectedDate}
        onChange={(e) => onSelect(e.target.value)}
        style={{ padding: "4px", fontSize: "1rem" }}
      >
        <option value="">Today</option>
        {availableDates.map((d) => (
          <option key={d} value={d}>
            {d}
          </option>
        ))}
      </select>
      {selectedDate && (
        <button
          onClick={() => onSelect("")}
          style={{ padding: "4px 10px", cursor: "pointer" }}
        >
          Back to Today
        </button>
      )}
    </div>
  );
}

export default function MarketResearchBoardPage() {
  const [games, setGames] = useState<ResearchGame[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [availableDates, setAvailableDates] = useState<string[]>([]);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    fetch(`${apiUrl}/research/available-dates`)
      .then((res) => res.json())
      .then((data) => setAvailableDates(data.available_dates ?? []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";
    const url = getBoardResearchUrl(apiUrl, selectedDate);

    function loadGames() {
      setGames(null);
      setError(null);
      fetch(url)
        .then((res) => {
          if (!res.ok) throw new Error(`Request failed (${res.status})`);
          return res.json();
        })
        .then((data: ResearchGame[]) => setGames(data))
        .catch((err: unknown) =>
          setError(err instanceof Error ? err.message : "Unknown error")
        );
    }
    loadGames();
  }, [selectedDate]);

  const dateLabel = selectedDate || "Today";

  if (error) {
    return (
      <main style={{ padding: "2rem", fontFamily: "Arial, sans-serif" }}>
        <Link href="/">← Dashboard</Link>
        <h1 style={{ marginTop: "1rem" }}>Market Research Board</h1>
        <DateSelector
          selectedDate={selectedDate}
          availableDates={availableDates}
          onSelect={setSelectedDate}
        />
        <p style={{ color: "crimson", marginTop: "1rem" }}>
          Error loading data for {dateLabel}: {error}
        </p>
      </main>
    );
  }

  if (!games) {
    return (
      <main style={{ padding: "2rem", fontFamily: "Arial, sans-serif" }}>
        <Link href="/">← Dashboard</Link>
        <h1 style={{ marginTop: "1rem" }}>Market Research Board</h1>
        <DateSelector
          selectedDate={selectedDate}
          availableDates={availableDates}
          onSelect={setSelectedDate}
        />
        <p style={{ marginTop: "1rem" }}>Loading...</p>
      </main>
    );
  }

  const entries = buildBoardEntries(games);
  const anyOdds = games.some((g) => g.odds.length > 0);
  const gameMap = new Map(games.map((g) => [String(g.game_id), g]));

  return (
    <main style={{ padding: "2rem", fontFamily: "Arial, sans-serif", maxWidth: "900px" }}>
      <Link href="/">← Dashboard</Link>

      <h1 style={{ marginTop: "1rem" }}>Market Research Board</h1>

      <DateSelector
        selectedDate={selectedDate}
        availableDates={availableDates}
        onSelect={setSelectedDate}
      />

      <p
        style={{
          marginTop: "0.5rem",
          marginBottom: "1.5rem",
          fontSize: "0.9em",
          color: "#555",
          borderLeft: "3px solid #d1d5db",
          paddingLeft: "0.75rem",
        }}
      >
        Market opportunities organize existing research context around available sportsbook prices.
        They are not betting recommendations and do not represent calculated edge or expected value.
      </p>

      {games.length === 0 && (
        <p style={{ color: "#888" }}>No games found for {dateLabel}.</p>
      )}

      {games.length > 0 && entries.length === 0 && !anyOdds && (
        <p style={{ color: "#888" }}>
          No sportsbook odds available for {dateLabel}. Market opportunities require odds data.
        </p>
      )}

      {games.length > 0 && entries.length === 0 && anyOdds && (
        <p style={{ color: "#888" }}>
          No market opportunities found for {dateLabel}.
        </p>
      )}

      {entries.map((entry: BoardEntry, i: number) => {
        const game = gameMap.get(entry.opportunity.gameId);
        if (!game) return null;
        return (
          <div key={i} style={cardStyle}>
            <div style={cardHeaderStyle}>
              <div>
                <div style={{ fontWeight: "bold", fontSize: "1.05em" }}>
                  {game.away_team} @ {game.home_team}
                </div>
                <div style={{ fontSize: "0.85em", color: "#555", marginTop: "2px" }}>
                  {game.game_time ? `${game.game_time} UTC` : ""}
                  {game.game_time ? " · " : ""}
                  {game.status.replace(/_/g, " ")}
                </div>
              </div>
              <Link
                href={`/game/${game.game_id}`}
                style={{ fontSize: "0.85em", whiteSpace: "nowrap" }}
              >
                View Game Research →
              </Link>
            </div>

            <div style={cardBodyStyle}>
              <div
                style={{
                  fontSize: "0.72em",
                  fontWeight: "bold",
                  color: "#1e40af",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  marginBottom: "2px",
                }}
              >
                {entry.opportunity.marketType.replace(/_/g, " ")}
              </div>
              <div style={{ fontWeight: "bold", marginBottom: "0.75rem" }}>
                {entry.opportunity.title}
              </div>

              {entry.sourceInsights.length > 0 && (
                <div style={{ marginBottom: "0.75rem" }}>
                  <div
                    style={{
                      fontSize: "0.8em",
                      fontWeight: "bold",
                      color: "#374151",
                      marginBottom: "4px",
                    }}
                  >
                    Research Context
                  </div>
                  {entry.sourceInsights.map((insight, j) => (
                    <div
                      key={j}
                      style={{
                        padding: "0.5rem 0.6rem",
                        marginBottom: "4px",
                        borderLeft: "3px solid #b45309",
                        background: "#fffbeb",
                      }}
                    >
                      <div
                        style={{
                          fontWeight: "bold",
                          fontSize: "0.85em",
                          color: "#92400e",
                        }}
                      >
                        {insight.title}
                      </div>
                      <div
                        style={{
                          fontSize: "0.82em",
                          color: "#374151",
                          marginTop: "2px",
                        }}
                      >
                        {insight.description}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {game.odds.length === 0 ? (
                <div style={{ fontSize: "0.85em", color: "#888" }}>
                  No sportsbook odds available
                </div>
              ) : (
                <div>
                  <div
                    style={{
                      fontSize: "0.8em",
                      fontWeight: "bold",
                      color: "#374151",
                      marginBottom: "4px",
                    }}
                  >
                    Available Odds
                  </div>
                  {game.odds.map((o) => (
                    <div key={o.sportsbook} style={{ fontSize: "0.85em", marginBottom: "2px" }}>
                      <span
                        style={{
                          fontWeight: "bold",
                          minWidth: "100px",
                          display: "inline-block",
                        }}
                      >
                        {o.sportsbook}
                      </span>
                      Away {formatMoneyline(o.away_moneyline)} (
                      {formatProbability(o.away_implied_probability)}) / Home{" "}
                      {formatMoneyline(o.home_moneyline)} (
                      {formatProbability(o.home_implied_probability)})
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </main>
  );
}
