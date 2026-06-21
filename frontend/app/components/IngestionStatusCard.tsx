"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";

type IngestionHealth = {
  last_run_at: string | null;
  last_exit_code: number | null;
  status: "healthy" | "failed" | "unknown";
};

const cardStyle: CSSProperties = {
  border: "1px solid #ccc",
  padding: "10px 14px",
  marginTop: "1rem",
  display: "inline-block",
  minWidth: "280px",
  fontSize: "0.9rem",
};

const STATUS_COLOR: Record<string, string> = {
  healthy: "green",
  failed: "crimson",
  unknown: "#888",
};

export default function IngestionStatusCard() {
  const [data, setData] = useState<IngestionHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    fetch(`${apiUrl}/health/ingestion`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((d: IngestionHealth) => setData(d))
      .catch((err) =>
        setFetchError(err instanceof Error ? err.message : "Unknown error")
      )
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div style={cardStyle}>Loading ingestion status...</div>;
  }

  if (fetchError) {
    return (
      <div style={cardStyle}>
        <span style={{ color: "crimson" }}>
          Ingestion status unavailable: {fetchError}
        </span>
      </div>
    );
  }

  if (!data) return null;

  const color = STATUS_COLOR[data.status] ?? "#888";

  return (
    <div style={cardStyle}>
      <strong>Data Ingestion</strong>
      <div style={{ marginTop: "6px" }}>
        Status:{" "}
        <span style={{ color, fontWeight: "bold" }}>{data.status}</span>
      </div>
      <div>Last run: {data.last_run_at ?? "—"}</div>
      <div>Exit code: {data.last_exit_code ?? "—"}</div>
    </div>
  );
}
