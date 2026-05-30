"use client";

import { useEffect, useState } from "react";

interface IntelResponse {
  available: boolean;
  running: boolean;
  last_error: string | null;
  model: string | null;
  summary: {
    text: string;
    threat_level: "low" | "med" | "high" | "unknown";
    labels_seen: string[];
    t: number;
    model: string;
    latency_ms: number;
  } | null;
}

interface Props {
  apiBase: string;
  /** Polling interval in ms (default 2000). */
  intervalMs?: number;
  /** Visual size — full = padded card, compact = floating widget. */
  variant?: "full" | "compact";
}

/**
 * On-device tactical reasoning card. Polls the backend's /intel/summary,
 * which is fed by a local vision LLM (Ollama + Gemma 3). Fully offline.
 *
 * Three visual states:
 *   - service offline (Ollama not running) → muted note
 *   - waiting for first inference          → "Analysing…"
 *   - have a summary                       → text + threat-level chip
 */
export function IntelSummaryCard({
  apiBase,
  intervalMs = 2000,
  variant = "full",
}: Props) {
  const [data, setData] = useState<IntelResponse | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: number | null = null;
    const tick = async () => {
      try {
        const res = await fetch(`${apiBase}/intel/summary`, { cache: "no-store" });
        if (res.ok) {
          const j = (await res.json()) as IntelResponse;
          if (!stopped) setData(j);
        }
      } catch {
        // ignore; we'll retry next tick
      } finally {
        if (!stopped) timer = window.setTimeout(tick, intervalMs);
      }
    };
    tick();
    return () => {
      stopped = true;
      if (timer != null) window.clearTimeout(timer);
    };
  }, [apiBase, intervalMs]);

  const isCompact = variant === "compact";
  const wrap = isCompact
    ? "max-w-md rounded-md border border-border-strong bg-surface/85 px-3 py-2 backdrop-blur-sm shadow-card"
    : "rounded-md border border-border bg-surface px-4 py-4 shadow-card";

  if (!data) {
    return (
      <section className={wrap}>
        <Header label="Intelligence" model={null} />
        <p className="mt-2 font-mono text-[11px] uppercase tracking-widest text-text-dim">
          connecting…
        </p>
      </section>
    );
  }

  if (!data.available) {
    return (
      <section className={wrap}>
        <Header label="Intelligence" model={data.model} />
        <p className="mt-2 font-sans text-[12px] text-text-muted">
          On-device reasoning unavailable. Start Ollama (
          <code className="font-mono text-accent">brew services start ollama</code>
          ) and pull the model.
        </p>
        {data.last_error && (
          <p className="mt-1 font-mono text-[10px] uppercase tracking-widest text-fail">
            ▲ {data.last_error}
          </p>
        )}
      </section>
    );
  }

  const s = data.summary;
  if (!s) {
    return (
      <section className={wrap}>
        <Header label="Intelligence" model={data.model} />
        <p className="mt-2 font-sans text-[12px] text-text-muted">
          {data.running ? "Analysing scene…" : "Waiting for first frame to analyse."}
        </p>
      </section>
    );
  }

  const tier =
    s.threat_level === "high" ? "fail" : s.threat_level === "med" ? "warn" : "ok";
  const tierStyles: Record<string, string> = {
    fail: "border-fail/60 bg-fail/10 text-fail",
    warn: "border-warn/60 bg-warn/10 text-warn",
    ok: "border-accent/40 bg-accent/10 text-accent",
  };

  return (
    <section className={wrap}>
      <div className="flex items-baseline justify-between gap-3">
        <Header label="Intelligence" model={s.model} />
        <span
          className={`rounded-full border px-2.5 py-0.5 font-sans text-[10px] font-bold uppercase tracking-[0.25em] ${tierStyles[tier]}`}
        >
          {s.threat_level}
        </span>
      </div>
      <p
        className={`mt-2 font-sans ${
          isCompact ? "text-[13px]" : "text-[14px]"
        } leading-snug text-text`}
      >
        {s.text || "—"}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {s.labels_seen.length > 0 ? (
          s.labels_seen.map((l) => (
            <span
              key={l}
              className="rounded-full border border-border-strong bg-surface-elevated px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest text-text-muted"
            >
              {l}
            </span>
          ))
        ) : (
          <span className="font-mono text-[10px] uppercase tracking-widest text-text-dim">
            no detections in frame
          </span>
        )}
      </div>
      <div className="mt-2 flex items-center justify-between font-mono text-[9px] uppercase tracking-widest text-text-dim">
        <span>{ageString(s.t)}</span>
        <span>{Math.round(s.latency_ms)} ms</span>
      </div>
    </section>
  );
}

function Header({ label, model }: { label: string; model: string | null }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="font-sans text-[11px] font-semibold uppercase tracking-[0.3em] text-accent">
        {label}
      </span>
      {model && (
        <span className="font-mono text-[9px] uppercase tracking-widest text-text-dim">
          · {model}
        </span>
      )}
    </div>
  );
}

function ageString(unixSeconds: number): string {
  if (!unixSeconds) return "—";
  const dt = Math.max(0, Date.now() / 1000 - unixSeconds);
  if (dt < 2) return "just now";
  if (dt < 60) return `${dt.toFixed(0)}s ago`;
  return `${Math.floor(dt / 60)}m ago`;
}
