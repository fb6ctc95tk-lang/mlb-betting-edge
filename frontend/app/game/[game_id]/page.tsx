"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { getGameFlags } from "../../../lib/gameFlags";
import { getResearchInsights, type ResearchInsight } from "../../../lib/researchInsights";
import { getMarketOpportunities, type MarketOpportunity } from "../../../lib/marketOpportunities";
import ResearchFlags from "../../../components/ResearchFlags";

type Odds = {
  sportsbook: string;
  away_moneyline: number;
  away_implied_probability: number;
  home_moneyline: number;
  home_implied_probability: number;
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

type GameDetail = {
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

const sectionStyle: CSSProperties = {
  marginTop: "1.5rem",
};

const labelStyle: CSSProperties = {
  fontWeight: "bold",
  minWidth: "120px",
  display: "inline-block",
  color: "#555",
};

function degreesToCompass(deg: number): string {
  const dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  return dirs[Math.round(deg / 45) % 8];
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

function formatBullpenDate(dateStr: string, playedYesterday: boolean): string {
  const d = new Date(`${dateStr}T12:00:00`);
  const label = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return playedYesterday ? `${label} (yesterday)` : label;
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ marginBottom: "4px" }}>
      <span style={labelStyle}>{label}</span>
      {value}
    </div>
  );
}

function InjuryList({ team, injuries }: { team: string; injuries: Injury[] }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ fontWeight: "bold", marginBottom: "4px" }}>{team}</div>
      {injuries.length === 0 ? (
        <span style={{ color: "#888" }}>None reported</span>
      ) : (
        injuries.map((inj, i) => (
          <div key={i} style={{ marginBottom: "6px" }}>
            <div style={{ fontWeight: "bold", fontSize: "0.9em" }}>{inj.player_name}</div>
            {inj.injury_status && (
              <div style={{ fontSize: "0.85em", color: "crimson" }}>{inj.injury_status}</div>
            )}
            {inj.injury_description && (
              <div style={{ fontSize: "0.85em", color: "#555" }}>{inj.injury_description}</div>
            )}
          </div>
        ))
      )}
    </div>
  );
}

function BullpenSummary({ team, bullpen }: { team: string; bullpen: Bullpen | null }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ fontWeight: "bold", marginBottom: "4px" }}>{team}</div>
      {!bullpen || bullpen.previous_game_date === null ? (
        <span style={{ color: "#888" }}>No data</span>
      ) : (
        <>
          <div>
            {bullpen.bullpen_innings_last_game !== null
              ? bullpen.bullpen_innings_last_game.toFixed(1)
              : "—"}{" "}
            IP
          </div>
          <div style={{ fontSize: "0.85em", color: bullpen.played_yesterday ? "crimson" : "#555" }}>
            {formatBullpenDate(bullpen.previous_game_date, bullpen.played_yesterday)}
          </div>
        </>
      )}
    </div>
  );
}

export default function GameDetailPage() {
  const params = useParams<{ game_id: string }>();
  const [game, setGame] = useState<GameDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!params?.game_id) return;
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    fetch(`${apiUrl}/research/game/${params.game_id}`)
      .then((res) => {
        if (res.status === 404) throw new Error("Game not found");
        if (!res.ok) throw new Error(`Request failed (${res.status})`);
        return res.json();
      })
      .then((data: GameDetail) => setGame(data))
      .catch((err) => setError(err instanceof Error ? err.message : "Unknown error"));
  }, [params?.game_id]);

  if (error) {
    return (
      <main style={{ padding: "2rem", fontFamily: "Arial, sans-serif" }}>
        <Link href="/">← Dashboard</Link>
        <p style={{ color: "crimson", marginTop: "1rem" }}>{error}</p>
      </main>
    );
  }

  if (!game) {
    return (
      <main style={{ padding: "2rem", fontFamily: "Arial, sans-serif" }}>
        <Link href="/">← Dashboard</Link>
        <p style={{ marginTop: "1rem" }}>Loading...</p>
      </main>
    );
  }

  const flags = getGameFlags(game);
  const insights = getResearchInsights(game);
  const opportunities = getMarketOpportunities(game, insights);

  return (
    <main style={{ padding: "2rem", fontFamily: "Arial, sans-serif", maxWidth: "900px" }}>
      <Link href="/">← Dashboard</Link>

      <h1 style={{ marginTop: "1rem" }}>
        {game.away_team} @ {game.home_team}
      </h1>
      <div style={{ color: "#555", fontSize: "0.95em" }}>
        {game.game_date}
        {game.game_time ? ` · ${game.game_time} UTC` : ""}
        {" · "}
        {game.status.replace("_", " ")}
      </div>
      {flags.length > 0 && (
        <div style={{ marginTop: "0.5rem" }}>
          <ResearchFlags flags={flags} />
        </div>
      )}

      {insights.length > 0 && (
        <div style={{ marginTop: "1rem" }}>
          <h2 style={{ margin: "0 0 0.5rem" }}>Research Insights</h2>
          {insights.map((insight: ResearchInsight, i: number) => (
            <div
              key={i}
              style={{
                padding: "0.6rem 0.75rem",
                marginBottom: "0.5rem",
                borderLeft: `3px solid ${insight.severity === "attention" ? "#b45309" : "#2563eb"}`,
                background: insight.severity === "attention" ? "#fffbeb" : "#eff6ff",
              }}
            >
              <div style={{ fontWeight: "bold", fontSize: "0.9em", color: insight.severity === "attention" ? "#92400e" : "#1e40af" }}>
                {insight.title}
              </div>
              <div style={{ fontSize: "0.85em", color: "#374151", marginTop: "2px" }}>
                {insight.description}
              </div>
            </div>
          ))}
        </div>
      )}

      {opportunities.length > 0 && (
        <div style={{ marginTop: "1rem" }}>
          <h2 style={{ margin: "0 0 0.5rem" }}>Market Opportunities</h2>
          {opportunities.map((opp: MarketOpportunity, i: number) => (
            <div
              key={i}
              style={{
                padding: "0.75rem",
                marginBottom: "0.75rem",
                border: "1px solid #bfdbfe",
                background: "#eff6ff",
              }}
            >
              <div style={{ fontSize: "0.75em", fontWeight: "bold", color: "#1e40af", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "4px" }}>
                {opp.marketType.replace(/_/g, " ")}
              </div>
              <div style={{ fontWeight: "bold", fontSize: "0.95em", marginBottom: "4px" }}>
                {opp.title}
              </div>
              <div style={{ fontSize: "0.85em", color: "#374151", marginBottom: "8px" }}>
                {opp.summary}
              </div>
              {opp.reasons.length > 0 && (
                <div style={{ marginBottom: "8px" }}>
                  <div style={{ fontSize: "0.8em", fontWeight: "bold", color: "#374151", marginBottom: "2px" }}>Why this game:</div>
                  <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
                    {opp.reasons.map((r, j) => (
                      <li key={j} style={{ fontSize: "0.82em", color: "#374151" }}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              {opp.cautionNotes.length > 0 && (
                <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
                  {opp.cautionNotes.map((n, j) => (
                    <li key={j} style={{ fontSize: "0.8em", color: "#6b7280", fontStyle: "italic" }}>{n}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Records & Pitchers */}
      <div style={sectionStyle}>
        <h2>Teams</h2>
        <Row label="Away record" value={game.away_record ?? "—"} />
        <Row label="Home record" value={game.home_record ?? "—"} />
        <Row label="Away pitcher" value={game.away_pitcher ?? "TBD"} />
        <Row label="Home pitcher" value={game.home_pitcher ?? "TBD"} />
      </div>

      {/* Weather */}
      <div style={sectionStyle}>
        <h2>Weather</h2>
        {!game.weather ? (
          <span style={{ color: "#888" }}>No weather data</span>
        ) : (
          <>
            {game.weather.temperature !== null && (
              <Row label="Temperature" value={`${Math.round(game.weather.temperature)}°F`} />
            )}
            {game.weather.wind_speed !== null && (
              <Row
                label="Wind"
                value={`${Math.round(game.weather.wind_speed)} mph${
                  game.weather.wind_direction !== null
                    ? ` ${degreesToCompass(game.weather.wind_direction)}`
                    : ""
                }`}
              />
            )}
            {game.weather.precipitation_chance !== null && (
              <Row label="Precip chance" value={`${game.weather.precipitation_chance}%`} />
            )}
          </>
        )}
      </div>

      {/* Odds */}
      <div style={sectionStyle}>
        <h2>Current Odds</h2>
        {game.odds.length === 0 ? (
          <span style={{ color: "#888" }}>No odds available</span>
        ) : (
          <table style={{ borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={cellStyle}>Sportsbook</th>
                <th style={cellStyle}>Away ({game.away_team})</th>
                <th style={cellStyle}>Away Prob</th>
                <th style={cellStyle}>Home ({game.home_team})</th>
                <th style={cellStyle}>Home Prob</th>
              </tr>
            </thead>
            <tbody>
              {game.odds.map((o) => (
                <tr key={o.sportsbook}>
                  <td style={cellStyle}>{o.sportsbook}</td>
                  <td style={cellStyle}>{formatMoneyline(o.away_moneyline)}</td>
                  <td style={cellStyle}>{formatProbability(o.away_implied_probability)}</td>
                  <td style={cellStyle}>{formatMoneyline(o.home_moneyline)}</td>
                  <td style={cellStyle}>{formatProbability(o.home_implied_probability)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Injuries */}
      <div style={sectionStyle}>
        <h2>Injuries</h2>
        <div style={{ display: "flex", gap: "2rem" }}>
          <InjuryList team={game.away_team} injuries={game.away_injuries} />
          <InjuryList team={game.home_team} injuries={game.home_injuries} />
        </div>
      </div>

      {/* Bullpen */}
      <div style={sectionStyle}>
        <h2>Bullpen Context (Last Game)</h2>
        <div style={{ display: "flex", gap: "2rem" }}>
          <BullpenSummary team={game.away_team} bullpen={game.away_bullpen} />
          <BullpenSummary team={game.home_team} bullpen={game.home_bullpen} />
        </div>
      </div>

      {/* Line Movement */}
      <div style={sectionStyle}>
        <h2>Line Movement</h2>
        {game.line_movement.length === 0 ? (
          <span style={{ color: "#888" }}>No line movement data</span>
        ) : (
          <table style={{ borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={cellStyle}>Sportsbook</th>
                <th style={cellStyle}>Team</th>
                <th style={cellStyle}>Side</th>
                <th style={cellStyle}>Opening</th>
                <th style={cellStyle}>Current</th>
                <th style={cellStyle}>Move</th>
                <th style={cellStyle}>Opened</th>
                <th style={cellStyle}>Updated</th>
              </tr>
            </thead>
            <tbody>
              {game.line_movement.map((row) => (
                <tr key={`${row.sportsbook}-${row.side}`}>
                  <td style={cellStyle}>{row.sportsbook}</td>
                  <td style={cellStyle}>{row.team}</td>
                  <td style={cellStyle}>{row.side}</td>
                  <td style={cellStyle}>{formatMoneyline(row.opening_moneyline)}</td>
                  <td style={cellStyle}>{formatMoneyline(row.latest_moneyline)}</td>
                  <td style={{
                    ...cellStyle,
                    color: movementColor(row.movement),
                    fontWeight: row.movement !== 0 ? "bold" : "normal",
                  }}>
                    {formatMoneyline(row.movement)}
                  </td>
                  <td style={cellStyle}>{formatTimestamp(row.opening_timestamp)}</td>
                  <td style={cellStyle}>{formatTimestamp(row.latest_timestamp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </main>
  );
}
