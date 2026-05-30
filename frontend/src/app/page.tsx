"use client";

import { useEffect, useMemo, useState } from "react";
import { ConsolePanel } from "@/components/ConsolePanel";
import { IntelPanel } from "@/components/IntelPanel";
import { LocalMap3D } from "@/components/LocalMap3D";
import { StatusBar } from "@/components/StatusBar";
import { ThreatAlert } from "@/components/ThreatAlert";
import { VideoFeed } from "@/components/VideoFeed";
import { operationalEntities } from "@/lib/entities";
import { httpFromWs } from "@/lib/feedUrl";
import { useWorldClient } from "@/lib/useWorldClient";

const DEFAULT_WS = "ws://localhost:8001/ws";

type Tab = "feed" | "map" | "intel";

const TABS: { id: Tab; label: string }[] = [
  { id: "feed", label: "Feed" },
  { id: "map", label: "Map" },
  { id: "intel", label: "Intel" },
];

export default function Page() {
  const wsUrl = useMemo(() => {
    const override = process.env.NEXT_PUBLIC_WS_URL;
    return override && override.length > 0 ? override : DEFAULT_WS;
  }, []);

  // Offline reality: only the recon (Leader) feed reaches the dashboard. The
  // companion (Follower) is paired with the mobile app over its own AP and is
  // not multiplexed onto the same network as the laptop's brain.
  // Use the single-frame JPEG endpoint, not MJPEG: multipart/x-mixed-replace
  // streams keep the browser tab's loading spinner perpetually active, which
  // looks to operators like the tab is constantly refreshing.
  const leaderSrc = useMemo(() => httpFromWs(wsUrl, "/video/leader.jpg"), [wsUrl]);

  const { connection, entities, lastError, health, detections, detectionLog } = useWorldClient(wsUrl);
  // Persist the active tab so a Fast Refresh / hard reload doesn't snap the
  // operator back to Feed every time. Lazy init avoids the initial paint
  // flicker where tab briefly shows "feed" before localStorage is read.
  const [tab, setTab] = useState<Tab>(() => {
    if (typeof window === "undefined") return "feed";
    const saved = window.localStorage.getItem("sg.tab");
    return saved === "feed" || saved === "map" || saved === "intel"
      ? (saved as Tab)
      : "feed";
  });
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("sg.tab", tab);
  }, [tab]);
  // Operator-facing views (Map / Intel / Status counter) hide SLAM landmark
  // entities — they're internal triangulated map points, not real-world
  // things. SLAM tab keeps the full set so the diagnostic count still makes
  // sense.
  const opEntities = useMemo(() => operationalEntities(entities), [entities]);
  const landmarks = useMemo(
    () => entities.filter((e) => e.id.startsWith("lm_")),
    [entities],
  );
  const detectionCount = Object.values(detections).reduce(
    (n, d) => n + d.boxes.length,
    0,
  );

  return (
    <div className="flex h-screen w-screen flex-col bg-bg text-text">
      <header className="flex items-center justify-between gap-4 border-b border-border bg-surface px-5 py-3">
        <div className="flex items-center gap-4">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/skyguardian-logo.png"
            alt="SkyGuardian"
            className="h-9 w-auto select-none"
            draggable={false}
          />
          <span className="hidden text-[10px] uppercase tracking-[0.35em] text-text-dim sm:inline">
            Operator
          </span>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-widest text-text-dim">
          {wsUrl}
        </span>
      </header>

      <StatusBar
        connection={connection}
        lastError={lastError}
        health={health}
        entityCount={opEntities.length}
        detectionCount={detectionCount}
      />

      <nav className="flex border-b border-border bg-surface">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`relative border-r border-border px-5 py-3 font-mono text-[11px] uppercase tracking-[0.3em] transition ${
              tab === t.id
                ? "text-text"
                : "text-text-dim hover:text-text-muted"
            }`}
          >
            {t.label}
            {tab === t.id && (
              <span className="absolute inset-x-0 -bottom-px h-[3px] bg-text" />
            )}
          </button>
        ))}
      </nav>

      <ThreatAlert detections={detections} />

      <main className="flex min-h-0 flex-1">
        <section className="flex min-h-0 flex-1 flex-col">
          {tab === "feed" && (
            // Flex row (not grid) so the row height stretches to fill the
            // parent flex column even when the <img> hasn't loaded a real
            // frame yet — grid auto-rows collapse to their intrinsic content.
            <div className="flex min-h-0 flex-1">
              <div className="flex min-w-0 flex-1">
                <VideoFeed
                  src={leaderSrc}
                  detections={detections["leader"]}
                  label="Leader · Recon"
                />
              </div>
              <div className="hidden w-80 shrink-0 md:block">
                <ConsolePanel log={detectionLog} />
              </div>
            </div>
          )}
          {tab === "map" && (
            <div className="relative min-h-0 flex-1">
              <LocalMap3D
                entities={opEntities}
                landmarks={landmarks}
                spanMeters={20}
                showLandmarks={false}
              />
              <div className="pointer-events-none absolute right-3 top-3 font-mono text-[10px] uppercase tracking-widest text-text-dim">
                {opEntities.length} entities
              </div>
            </div>
          )}
          {tab === "intel" && (
            <div className="min-h-0 flex-1 overflow-auto">
              <IntelPanel detections={detections} detectionLog={detectionLog} />
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
