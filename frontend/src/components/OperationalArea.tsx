"use client";

import { useState } from "react";

type Status =
  | { kind: "idle" }
  | { kind: "fetching" }
  | { kind: "success"; count: number }
  | { kind: "error"; message: string };

interface Props {
  apiBase: string;
}

const OPERATOR_KEY = process.env.NEXT_PUBLIC_OPERATOR_KEY || "";

/**
 * Operator control to re-anchor the map's buildings layer on a new lat/long.
 * This is a PRE-MISSION staging action: it hits the internet at the moment of
 * fetch (OSM Overpass) and then the system runs fully offline on the result.
 */
export function OperationalArea({ apiBase }: Props) {
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [radius, setRadius] = useState("400");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const submit = async () => {
    const body = { lat: Number(lat), lng: Number(lng), radius_m: Number(radius) };
    setStatus({ kind: "fetching" });
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (OPERATOR_KEY) headers["X-Operator-Key"] = OPERATOR_KEY;
      const res = await fetch(`${apiBase}/map/area`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        cache: "no-store",
      });
      if (!res.ok) {
        const msg = res.status === 503
          ? "No internet — pre-mission only"
          : `Failed (HTTP ${res.status})`;
        setStatus({ kind: "error", message: msg });
        return;
      }
      const data = (await res.json()) as { count: number };
      setStatus({ kind: "success", count: data.count });
    } catch {
      setStatus({ kind: "error", message: "No internet — pre-mission only" });
    }
  };

  const fetching = status.kind === "fetching";

  return (
    <div className="border border-border bg-surface-elevated p-3 font-mono text-[11px] text-text">
      <div className="mb-2 uppercase tracking-[0.2em] text-text-dim">Operational Area</div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-[9px] uppercase tracking-wider text-text-dim">Latitude</span>
          <input
            aria-label="latitude"
            value={lat}
            onChange={(e) => setLat(e.target.value)}
            inputMode="decimal"
            className="w-28 border border-border bg-surface px-2 py-1 tabular-nums text-accent outline-none focus:border-border-strong"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[9px] uppercase tracking-wider text-text-dim">Longitude</span>
          <input
            aria-label="longitude"
            value={lng}
            onChange={(e) => setLng(e.target.value)}
            inputMode="decimal"
            className="w-28 border border-border bg-surface px-2 py-1 tabular-nums text-accent outline-none focus:border-border-strong"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[9px] uppercase tracking-wider text-text-dim">Radius m</span>
          <input
            aria-label="radius"
            value={radius}
            onChange={(e) => setRadius(e.target.value)}
            inputMode="numeric"
            className="w-20 border border-border bg-surface px-2 py-1 tabular-nums text-accent outline-none focus:border-border-strong"
          />
        </label>
        <button
          onClick={submit}
          disabled={fetching}
          className="border border-border-strong bg-surface px-3 py-1 uppercase tracking-wider text-text hover:bg-surface/70 disabled:opacity-40"
        >
          {fetching ? "Fetching…" : "Set Area"}
        </button>
      </div>
      <div className="mt-2 h-4 text-[10px]">
        {status.kind === "success" && (
          <span className="text-ok">✓ {status.count} buildings cached for this area</span>
        )}
        {status.kind === "error" && <span className="text-fail">{status.message}</span>}
        {status.kind === "idle" && (
          <span className="text-text-dim">Requires internet — pre-mission staging only</span>
        )}
      </div>
    </div>
  );
}
