"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Clock } from "@/components/Clock";
import { ConsolePanel } from "@/components/ConsolePanel";
import { IntelPanel } from "@/components/IntelPanel";
import { LocalMap3D } from "@/components/LocalMap3D";
import { SourceSelector, type SourceState } from "@/components/SourceSelector";
import { StatusBar } from "@/components/StatusBar";
import { ThreatAlert } from "@/components/ThreatAlert";
import { VideoFeed } from "@/components/VideoFeed";
import { VideoPlayer } from "@/components/VideoPlayer";
import type { Entity, EntityStatus, EntityType, Health } from "@/lib/contracts";
import { operationalEntities } from "@/lib/entities";
import { httpFromWs } from "@/lib/feedUrl";
import {
  cumulativeEntitiesAt,
  frameAt,
  type PlaybackData,
} from "@/lib/playback";
import type { ConnectionState, DetectionEvent, DetectionLayer } from "@/lib/useWorldClient";
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

  const leaderSrc = useMemo(() => httpFromWs(wsUrl, "/video/leader.jpg"), [wsUrl]);
  const apiBase = useMemo(() => httpFromWs(wsUrl, ""), [wsUrl]);

  const wsLive = useWorldClient(wsUrl);
  const { connection, lastError, health } = wsLive;

  // Persist the active tab so a Fast Refresh / hard reload doesn't snap the
  // operator back to Feed every time.
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

  // ---- mode dispatch: live RTMP vs playback file ------------------------
  const [source, setSource] = useState<SourceState | null>(null);
  const onSource = useCallback((s: SourceState | null) => setSource(s), []);
  const isPlayback =
    source?.kind === "file" && source?.upload?.state === "ready";
  const playbackName = isPlayback ? source?.label ?? "" : "";

  // ---- playback-time state (drives Map + Intel + Status when in file mode)
  const [playbackData, setPlaybackData] = useState<PlaybackData | null>(null);
  const [playbackTime, setPlaybackTime] = useState<number>(0);
  const onPlayheadMove = useCallback(
    (t: number, data: PlaybackData | null) => {
      setPlaybackTime(t);
      // Cache the data the first time the player gives it to us so the Map
      // tab can read it without an extra fetch.
      setPlaybackData((prev) => prev ?? data);
    },
    [],
  );
  // Reset playback caches when we leave file mode.
  useEffect(() => {
    if (!isPlayback) {
      setPlaybackData(null);
      setPlaybackTime(0);
    }
  }, [isPlayback]);

  // ---- entity + detection projection: live or replayed ------------------
  const liveOpEntities = useMemo(
    () => operationalEntities(wsLive.entities),
    [wsLive.entities],
  );
  const liveLandmarks = useMemo(
    () => wsLive.entities.filter((e) => e.id.startsWith("lm_")),
    [wsLive.entities],
  );

  const playbackEntities = useMemo<Entity[]>(() => {
    if (!playbackData) return [];
    return cumulativeEntitiesAt(playbackData.frames, playbackTime).map((e) =>
      toEntity(e, playbackTime),
    );
  }, [playbackData, playbackTime]);

  const playbackDetectionLayer = useMemo<DetectionLayer | undefined>(() => {
    if (!playbackData) return undefined;
    const f = frameAt(playbackData.frames, playbackTime);
    if (!f) return undefined;
    return {
      source: "leader",
      boxes: f.boxes,
      imageW: playbackData.image_w,
      imageH: playbackData.image_h,
      t: f.t,
    };
  }, [playbackData, playbackTime]);

  const playbackDetectionLog = useMemo<DetectionEvent[]>(() => {
    if (!playbackData) return [];
    // Build a rolling log of detection events from the start of the clip up
    // to currentTime. Newest first to match the live console.
    const log: DetectionEvent[] = [];
    for (const f of playbackData.frames) {
      if (f.t > playbackTime) break;
      if (f.boxes.length > 0) {
        log.push({ t: f.t, source: "leader", boxes: f.boxes });
      }
    }
    return log.reverse().slice(0, 80);
  }, [playbackData, playbackTime]);

  // Status-bar feeds. In playback we synthesise the same shape the live
  // path uses so StatusBar doesn't need a special mode prop.
  const effectiveOpEntities = isPlayback
    ? operationalEntities(playbackEntities)
    : liveOpEntities;
  const effectiveLandmarks = isPlayback ? [] : liveLandmarks;
  const effectiveDetections: Record<string, DetectionLayer> = isPlayback
    ? playbackDetectionLayer
      ? { leader: playbackDetectionLayer }
      : {}
    : wsLive.detections;
  const effectiveDetectionLog = isPlayback ? playbackDetectionLog : wsLive.detectionLog;
  const detectionCount = Object.values(effectiveDetections).reduce(
    (n, d) => n + d.boxes.length,
    0,
  );

  // In playback we replace the perception/leader health to honestly reflect
  // what the operator sees: the leader video is up (the file is loaded),
  // perception is up (boxes/entities are available).
  const effectiveHealth: Health | null = isPlayback
    ? {
        type: "health",
        tello: health?.tello ?? "unknown",
        mavic: "streaming",
        perception: "ok",
        t: Date.now() / 1000,
      }
    : health;
  const effectiveConnection: ConnectionState = isPlayback
    ? { kind: "connected" }
    : connection;

  return (
    <div className="flex h-screen w-screen flex-col bg-bg text-text">
      <header className="relative flex items-center justify-between gap-4 border-b border-border bg-surface/80 px-6 py-3 backdrop-blur-sm">
        <div className="flex items-center gap-4">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/skyguardian-logo.png"
            alt="SkyGuardian"
            className="logo-invert h-9 w-auto select-none"
            draggable={false}
          />
          <span className="hidden rounded-full border border-border-strong bg-surface-elevated px-3 py-1 text-[10px] uppercase tracking-[0.4em] text-text-muted sm:inline">
            Operator
          </span>
        </div>
        <div className="flex items-center gap-3 rounded-full border border-border-strong bg-surface-elevated px-4 py-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-accent shadow-glow-cyan" aria-hidden />
          <Clock />
        </div>
      </header>

      <StatusBar
        connection={effectiveConnection}
        lastError={lastError}
        health={effectiveHealth}
        entityCount={effectiveOpEntities.length}
        detectionCount={detectionCount}
      />

      <nav className="flex items-center gap-1 border-b border-border bg-surface/60 px-4 py-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`relative rounded-full px-5 py-1.5 font-sans text-[12px] font-semibold uppercase tracking-[0.25em] transition ${
              tab === t.id
                ? "bg-accent/15 text-accent shadow-glow-cyan"
                : "text-text-dim hover:bg-surface-elevated hover:text-text-muted"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <ThreatAlert detections={effectiveDetections} />

      <main className="flex min-h-0 flex-1">
        <section className="flex min-h-0 flex-1 flex-col">
          {tab === "feed" && (
            <div className="flex min-h-0 flex-1 flex-col">
              <SourceSelector apiBase={apiBase} onState={onSource} />
              <div className="flex min-h-0 flex-1">
                <div className="flex min-w-0 flex-1">
                  {isPlayback ? (
                    <VideoPlayer
                      apiBase={apiBase}
                      name={playbackName}
                      onTimeUpdate={onPlayheadMove}
                    />
                  ) : (
                    <VideoFeed
                      src={leaderSrc}
                      detections={wsLive.detections["leader"]}
                      label="Leader · Recon"
                    />
                  )}
                </div>
                <div className="hidden w-80 shrink-0 md:block">
                  <ConsolePanel log={effectiveDetectionLog} />
                </div>
              </div>
            </div>
          )}
          {tab === "map" && (
            <div className="relative min-h-0 flex-1">
              <LocalMap3D
                entities={effectiveOpEntities}
                landmarks={effectiveLandmarks}
                spanMeters={20}
                showLandmarks={false}
              />
              <div className="pointer-events-none absolute right-3 top-3 font-mono text-[10px] uppercase tracking-widest text-text-dim">
                {effectiveOpEntities.length} entities
                {isPlayback && playbackData && (
                  <> · t={playbackTime.toFixed(1)}s</>
                )}
              </div>
            </div>
          )}
          {tab === "intel" && (
            <div className="min-h-0 flex-1 overflow-auto">
              <IntelPanel detections={effectiveDetections} detectionLog={effectiveDetectionLog} />
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

/** Translate a PlaybackEntity (flat, JSON-friendly) into the same Entity
 *  shape the live WS path uses, so LocalMap3D can render either uniformly. */
function toEntity(
  e: { id: string; type: string; label?: string | null; x: number; y: number; z: number; confidence: number; source: string },
  t: number,
): Entity {
  return {
    id: e.id,
    type: e.type as EntityType,
    position: { x: e.x, y: e.y, z: e.z },
    confidence: e.confidence,
    timestamp: t,
    source: (e.source as Entity["source"]) ?? "yolo",
    label: e.label ?? null,
    ttl_s: 5,
    status: "active" as EntityStatus,
  };
}
