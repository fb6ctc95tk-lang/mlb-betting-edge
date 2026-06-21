"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";

type DataQuality = {
  games: number;
  odds_records: number;
  weather_records: number;
  bullpen_records: number;
  injury_records: number;
  research_date: string | null;
  status: "healthy" | "warning" | "failed";
};

const cardStyle: CSSProperties = {
  border: "1px solid #ccc",
  padding: "10px 14px",
  marginTop: "1rem",
  display: "inline-block",
  minWidth: "200px",
  fontSize: "0.9rem",
  verticalAlign: "top",
};

const STATUS_COLOR: Record<string, string> = {
  healthy: "green",
  warning: "#b8860b",
  failed: "crimson",
};

export default function DataQualityCard() {
  const [data, setData] = useState<DataQuality | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    fetch(`${apiUrl}/health/data-quality`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((d: DataQuality) => setData(d))
      .catch((err) =>
        setFetchError(err instanceof Error ? err.message : "Unknown error")
      )
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div style={cardStyle}>Loading data quality...</div>;

  if (fetchError) {
    return (
      <div style={cardStyle}>
        <span style={{ color: "crimson" }}>Data quality unavailable: {fetchError}</span>
      </div>
    );
  }

  if (!data) return null;

  const color = STATUS_COLOR[data.status] ?? "#888";

  return (
    <div style={cardStyle}>
      <strong>Data Quality</strong>
      {data.research_date && (
        <div style={{ fontSize: "0.8em", color: "#555", marginTop: "2px" }}>
          {data.research_date}
        </div>
      )}
      <div style={{ marginTop: "6px" }}>
        Status:{" "}
        <span style={{ color, fontWeight: "bold" }}>{data.status}</span>
      </div>
      <div style={{ marginTop: "6px" }}>
        <div>Games: {data.games}</div>
        <div>Odds: {data.odds_records}</div>
        <div>Weather: {data.weather_records}</div>
        <div>Bullpen: {data.bullpen_records}</div>
        <div>Injuries: {data.injury_records}</div>
      </div>
    </div>
  );
}
