"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  answerData,
  classesForMission,
  detectionsByClass,
  fetchData,
  totals,
  type CaptureMission,
  type ClassTotal,
  type DetectionClass,
  type FoundryData,
} from "@/lib/foundryData";

type LoadState =
  | { kind: "loading" }
  | { kind: "notConfigured" }
  | { kind: "error"; message: string }
  | { kind: "ready"; data: FoundryData };

/**
 * Self-contained Foundry mission-data view. Fetches /api/foundry on mount and
 * runs its own loading/notConfigured/error/ready state machine. Renders
 * full-width and flows naturally so it sits inside a non-viewport content area
 * (the operator "Data" tab) as well as the standalone /data deep link.
 */
export default function FoundryDataView() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let stopped = false;
    (async () => {
      try {
        const data = await fetchData();
        if (stopped) return;
        if (!data.configured) {
          setState({ kind: "notConfigured" });
        } else if (data.error) {
          setState({ kind: "error", message: data.error });
        } else {
          setState({ kind: "ready", data });
        }
      } catch (exc) {
        if (!stopped) {
          setState({
            kind: "error",
            message: exc instanceof Error ? exc.message : String(exc),
          });
        }
      }
    })();
    return () => {
      stopped = true;
    };
  }, []);

  const configured = state.kind === "ready" || state.kind === "error";

  return (
    <div className="hud-grid w-full bg-bg text-text">
      <div className="mx-auto w-full max-w-[1400px] px-6 py-6">
        <CommandHeader configured={configured} />

        {state.kind === "loading" && <LoadingState />}
        {state.kind === "notConfigured" && <NotConfiguredState />}
        {state.kind === "error" && <ErrorState message={state.message} />}
        {state.kind === "ready" && <DataDashboard data={state.data} />}
      </div>
    </div>
  );
}

// ---- header --------------------------------------------------------------

function CommandHeader({ configured }: { configured: boolean }) {
  return (
    <header className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-border pb-5">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-baseline gap-2">
          <span className="text-[18px] font-bold uppercase tracking-[0.2em] text-text">
            SkyGuardian
          </span>
          <span className="font-mono text-[12px] uppercase tracking-[0.3em] text-accent">
            // Mission Data
          </span>
        </div>
        {configured ? (
          <span className="border border-ok/30 bg-ok/10 px-2.5 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.3em] text-ok">
            ◢ Foundry-Synced
          </span>
        ) : (
          <span className="border border-accent/30 bg-accent/10 px-2.5 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.3em] text-accent">
            ◢ Not Configured
          </span>
        )}
      </div>
      <LiveClock />
    </header>
  );
}

function LiveClock() {
  const [now, setNow] = useState<string>("");
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const hh = d.getHours().toString().padStart(2, "0");
      const mm = d.getMinutes().toString().padStart(2, "0");
      const ss = d.getSeconds().toString().padStart(2, "0");
      setNow(`${hh}:${mm}:${ss}`);
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <div className="flex items-center gap-3 border border-border-strong bg-surface-elevated px-4 py-1.5">
      <span className="h-1.5 w-1.5 rounded-full bg-ok shadow-glow-cyan" aria-hidden />
      <span className="font-mono text-[9px] uppercase tracking-[0.3em] text-text-dim">Z</span>
      <span className="font-mono text-sm tabular-nums tracking-widest text-accent">
        {now || "--:--:--"}
      </span>
    </div>
  );
}

// ---- dashboard -----------------------------------------------------------

function DataDashboard({ data }: { data: FoundryData }) {
  const { missions, classes } = data;
  const t = useMemo(() => totals(missions, classes), [missions, classes]);
  const byClass = useMemo(() => detectionsByClass(classes), [classes]);
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <>
      {/* Stat strip */}
      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Missions" value={t.missionCount} />
        <StatTile label="Detections" value={t.totalDetections} />
        <StatTile label="Classes" value={t.distinctClasses} />
        <StatTile label="Vouched Frames" value={t.vouchedFrames} />
      </div>

      {/* Main two-column */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Operations */}
        <section className="lg:col-span-2">
          <PanelHeader label="Operations" count={missions.length} />
          {missions.length === 0 ? (
            <EmptyNote text="No capture missions in the ontology yet." />
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {missions.map((m) => (
                <MissionCard
                  key={m.missionId || m.datasetRid}
                  mission={m}
                  classes={classesForMission(classes, m.missionId)}
                  selected={selected === m.missionId}
                  onSelect={() =>
                    setSelected((cur) =>
                      cur === m.missionId ? null : m.missionId,
                    )
                  }
                />
              ))}
            </div>
          )}
        </section>

        {/* Right column */}
        <section className="flex flex-col gap-6 lg:col-span-1">
          <div>
            <PanelHeader label="Detections by Class" count={byClass.length} />
            <DetectionsPanel rows={byClass} />
          </div>
          <div>
            <PanelHeader label="Ask the Data" />
            <AskData missions={missions} classes={classes} />
          </div>
        </section>
      </div>

      <footer className="mt-8 border-t border-border pt-4 font-mono text-[10px] uppercase tracking-[0.3em] text-text-dim">
        Synced from Palantir Foundry · {t.missionCount} Missions · Read-Only
      </footer>
    </>
  );
}

// ---- stat tile (count-up) ------------------------------------------------

function StatTile({ label, value }: { label: string; value: number }) {
  const display = useCountUp(value);
  return (
    <div className="tac-corners border border-border bg-surface px-5 py-4">
      <div className="font-mono text-[28px] font-bold leading-none tabular-nums text-accent">
        {display.toLocaleString("en-US")}
      </div>
      <div className="mt-2 font-mono text-[10px] font-semibold uppercase tracking-[0.3em] text-text-dim">
        {label}
      </div>
    </div>
  );
}

/** Deterministic count-up: animates 0 -> target over ~700ms via rAF. */
function useCountUp(target: number): number {
  const [val, setVal] = useState(0);
  const rafRef = useRef<number | null>(null);
  useEffect(() => {
    const duration = 700;
    const start = performance.now();
    const step = (t: number) => {
      const p = Math.min(1, (t - start) / duration);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - p, 3);
      setVal(Math.round(target * eased));
      if (p < 1) {
        rafRef.current = requestAnimationFrame(step);
      }
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [target]);
  return val;
}

// ---- panel header --------------------------------------------------------

function PanelHeader({ label, count }: { label: string; count?: number }) {
  return (
    <div className="mb-3 flex items-center justify-between border-b border-border pb-2">
      <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.3em] text-accent">
        ◢ {label}
      </span>
      {count != null && (
        <span className="border border-border-strong bg-surface-elevated px-2 py-0.5 font-mono text-[10px] tabular-nums text-text-muted">
          {count.toString().padStart(2, "0")}
        </span>
      )}
    </div>
  );
}

function EmptyNote({ text }: { text: string }) {
  return (
    <div className="border border-border bg-surface px-4 py-6 text-center font-mono text-[11px] uppercase tracking-widest text-text-dim">
      {text}
    </div>
  );
}

// ---- mission card --------------------------------------------------------

function MissionCard({
  mission,
  classes,
  selected,
  onSelect,
}: {
  mission: CaptureMission;
  classes: DetectionClass[];
  selected: boolean;
  onSelect: () => void;
}) {
  const chips = mission.classes
    ? mission.classes.split(",").map((c) => c.trim()).filter(Boolean)
    : classes.map((c) => c.label);
  const segTotal = classes.reduce((n, c) => n + c.count, 0);

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`tac-corners group flex flex-col border bg-surface px-4 py-4 text-left transition-colors ${
        selected
          ? "border-accent bg-surface-elevated"
          : "border-border hover:bg-surface-elevated"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-[14px] font-bold uppercase tracking-[0.12em] text-text">
          {mission.missionId || "unnamed"}
        </span>
        <span className="font-mono text-[9px] uppercase tracking-[0.3em] text-text-dim">
          {mission.createdT ? mission.createdT.slice(0, 10) : ""}
        </span>
      </div>

      {/* class chips */}
      <div className="mt-2.5 flex flex-wrap gap-1">
        {chips.length > 0 ? (
          chips.map((c) => (
            <span
              key={c}
              className="border border-accent/30 bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-accent"
            >
              {c}
            </span>
          ))
        ) : (
          <span className="font-mono text-[10px] uppercase tracking-widest text-text-dim">
            no classes
          </span>
        )}
      </div>

      {/* 3-up readout */}
      <div className="mt-3 grid grid-cols-3 gap-2 border-t border-border pt-3">
        <Readout label="Frames" value={mission.framesOut.toLocaleString("en-US")} />
        <Readout
          label="Train·Val"
          value={`${mission.trainCount.toLocaleString("en-US")}·${mission.valCount.toLocaleString("en-US")}`}
        />
        <Readout label="Vouched" value={mission.gemmaLabeledCount.toLocaleString("en-US")} />
      </div>

      {/* stacked proportion bar */}
      <StackedBar classes={classes} total={segTotal} />
    </button>
  );
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[13px] font-semibold tabular-nums text-text">
        {value}
      </div>
      <div className="mt-0.5 font-mono text-[9px] uppercase tracking-[0.22em] text-text-dim">
        {label}
      </div>
    </div>
  );
}

/** Thin full-width stacked proportion bar of a mission's class counts.
 *  Segments use accent at varying opacity (red is reserved for threats). */
function StackedBar({
  classes,
  total,
}: {
  classes: DetectionClass[];
  total: number;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);

  // Opacity tiers stepping down so adjacent segments read distinctly.
  const tiers = [0.85, 0.6, 0.42, 0.3, 0.22, 0.15];
  const segs = classes.filter((c) => c.count > 0);

  return (
    <div className="mt-3 h-1.5 w-full overflow-hidden border border-border bg-surface-elevated">
      {total > 0 && segs.length > 0 ? (
        <div className="flex h-full w-full">
          {segs.map((c, i) => (
            <div
              key={c.classKey || c.label}
              title={`${c.label}: ${c.count.toLocaleString("en-US")}`}
              className="h-full transition-[width] duration-700 ease-out"
              style={{
                width: mounted ? `${(c.count / total) * 100}%` : "0%",
                backgroundColor: "var(--accent)",
                opacity: tiers[Math.min(i, tiers.length - 1)],
              }}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ---- detections by class -------------------------------------------------

function DetectionsPanel({ rows }: { rows: ClassTotal[] }) {
  if (rows.length === 0) {
    return <EmptyNote text="No detection classes recorded." />;
  }
  const max = rows[0]?.total || 1;
  return (
    <div className="border border-border bg-surface px-4 py-4">
      <div className="space-y-3">
        {rows.map((r) => (
          <ClassBar key={r.label} row={r} max={max} />
        ))}
      </div>
    </div>
  );
}

function ClassBar({ row, max }: { row: ClassTotal; max: number }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);
  const pct = max > 0 ? (row.total / max) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-20 shrink-0 truncate font-mono text-[10px] uppercase tracking-[0.18em] text-text-muted">
        {row.label}
      </span>
      <div className="relative h-3.5 flex-1 border border-border bg-surface-elevated">
        <div
          className="h-full bg-accent transition-[width] duration-700 ease-out"
          style={{ width: mounted ? `${pct}%` : "0%" }}
        />
      </div>
      <span className="w-12 shrink-0 text-right font-mono text-[11px] font-semibold tabular-nums text-text">
        {row.total.toLocaleString("en-US")}
      </span>
    </div>
  );
}

// ---- ask the data -------------------------------------------------------

const EXAMPLE_CHIPS = ["most vehicles", "summarize overwatch-charlie", "total person"];

/** Source of the rendered answer: real Foundry AIP, or the local responder. */
type AnswerSource = "aip" | "local";

interface AskResult {
  text: string;
  source: AnswerSource;
}

/** Shape returned by /api/foundry/ask. */
interface AskApiResponse {
  configured: boolean;
  answer?: string;
  error?: string;
  source?: string;
}

function AskData({
  missions,
  classes,
}: {
  missions: CaptureMission[];
  classes: DetectionClass[];
}) {
  const [input, setInput] = useState("");
  const [result, setResult] = useState<AskResult | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    try {
      const res = await fetch("/api/foundry/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      const body = (await res.json()) as AskApiResponse;
      if (body.configured && body.answer && !body.error) {
        setResult({ text: body.answer, source: "aip" });
      } else {
        // Not configured, AIP error, or empty answer -> local fallback.
        setResult({ text: answerData(trimmed, missions, classes), source: "local" });
      }
    } catch {
      setResult({ text: answerData(trimmed, missions, classes), source: "local" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="tac-corners border border-border bg-surface">
      <div className="px-4 py-4">
        <form
          className="flex items-stretch gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void submit(input);
          }}
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Query the loaded missions…"
            className="flex-1 border border-border bg-surface-elevated px-3 py-2 font-mono text-[12px] text-text placeholder:text-text-dim focus:border-accent/60 focus:outline-none"
          />
          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="border border-cta bg-cta px-4 py-2 font-mono text-[11px] uppercase tracking-[0.25em] text-bg transition hover:bg-cta-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "◢ Querying…" : "Ask"}
          </button>
        </form>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {EXAMPLE_CHIPS.map((c) => (
            <button
              key={c}
              type="button"
              disabled={loading}
              onClick={() => {
                setInput(c);
                void submit(c);
              }}
              className="border border-border-strong bg-surface-elevated px-2 py-1 font-mono text-[10px] uppercase tracking-wide text-text-muted transition hover:border-accent/60 hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {c}
            </button>
          ))}
        </div>

        {result && (
          <div className="mt-4 border border-accent/30 bg-accent/10 px-3 py-2.5">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="font-mono text-[9px] uppercase tracking-[0.3em] text-text-dim">
                Readout
              </span>
              {result.source === "aip" ? (
                <span className="border border-ok/30 bg-ok/10 px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-[0.3em] text-ok">
                  ◢ AIP
                </span>
              ) : (
                <span className="border border-accent/30 bg-accent/10 px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-[0.3em] text-accent">
                  ◢ Local
                </span>
              )}
            </div>
            <div className="font-mono text-[12px] leading-snug text-text">
              {result.text}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// ---- non-ready states ----------------------------------------------------

function LoadingState() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <span className="font-mono text-[11px] uppercase tracking-[0.3em] text-text-dim">
        ▌ Syncing from Foundry…
      </span>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="mx-auto mt-10 max-w-2xl">
      <div className="tac-corners border border-warn/40 bg-warn/10 px-6 py-6">
        <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.3em] text-warn">
          ◢ Foundry Fetch Fault
        </div>
        <p className="mt-3 font-mono text-[12px] leading-relaxed text-text-muted">
          {message}
        </p>
        <p className="mt-3 font-mono text-[10px] uppercase tracking-widest text-text-dim">
          Verify FOUNDRY_HOST reachability and token scope, then reload.
        </p>
      </div>
    </div>
  );
}

function NotConfiguredState() {
  return (
    <div className="mx-auto mt-10 max-w-2xl">
      <div className="tac-corners border border-border bg-surface px-6 py-7">
        <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.3em] text-accent">
          ◢ Foundry Link Not Configured
        </div>
        <p className="mt-4 font-sans text-[13px] leading-relaxed text-text-muted">
          This surface reads mission data from a Palantir Foundry ontology. Set
          the following in{" "}
          <code className="font-mono text-accent">frontend/.env.local</code> and
          restart the dev server.
        </p>
        <ul className="mt-4 space-y-1.5">
          {["FOUNDRY_HOST", "FOUNDRY_TOKEN", "FOUNDRY_ONTOLOGY_RID"].map((v) => (
            <li
              key={v}
              className="border border-border-strong bg-surface-elevated px-3 py-2 font-mono text-[11px] tracking-wide text-text"
            >
              {v}=<span className="text-text-dim">…</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 font-mono text-[10px] uppercase tracking-widest text-text-dim">
          Token stays server-side · never reaches the client bundle.
        </p>
      </div>
    </div>
  );
}
