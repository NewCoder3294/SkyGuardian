"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Clock } from "@/components/Clock";
import { ConsolePanel } from "@/components/ConsolePanel";
import { FollowInset } from "@/components/FollowInset";
import FoundryDataView from "@/components/FoundryDataView";
import { IntelChat } from "@/components/IntelChat";
import { IntelPanel } from "@/components/IntelPanel";
import { IntelSummaryCard } from "@/components/IntelSummaryCard";
import { LocalMap2D } from "@/components/LocalMap2D";
import { LocalMap3D } from "@/components/LocalMap3D";
import { LocalMapGL } from "@/components/LocalMapGL";
import { OperationalArea } from "@/components/OperationalArea";
import { SourceSelector, type SourceState } from "@/components/SourceSelector";
import { StatusBar } from "@/components/StatusBar";
import { ClassificationBanner, CoordReadout, SectionHeader } from "@/components/tactical";
import { ThreatAlert } from "@/components/ThreatAlert";
import { VideoFeed } from "@/components/VideoFeed";
import { VideoPlayer } from "@/components/VideoPlayer";
import type { Entity, EntityStatus, EntityType, Health } from "@/lib/contracts";
import { operationalEntities } from "@/lib/entities";
import { fetchBasemapMeta } from "@/lib/basemapMeta";
import { cn } from "@/lib/cn";
import { httpFromWs } from "@/lib/feedUrl";
import {
  cumulativeEntitiesAt,
  frameAt,
  type PlaybackData,
} from "@/lib/playback";
import type { ConnectionState, DetectionEvent, DetectionLayer } from "@/lib/useWorldClient";
import { useWorldClient } from "@/lib/useWorldClient";
import { resolveWsUrl } from "@/lib/wsConfig";

type Tab = "feed" | "map" | "intel" | "data";

const TABS: { id: Tab; label: string }[] = [
  { id: "feed", label: "Feed" },
  { id: "map", label: "Map" },
  { id: "intel", label: "Intel" },
  { id: "data", label: "Data" },
];

export default function Page() {
  const wsUrl = useMemo(() => resolveWsUrl(process.env.NEXT_PUBLIC_WS_URL), []);

  const leaderSrc = useMemo(() => httpFromWs(wsUrl, "/video/leader.jpg"), [wsUrl]);
  const apiBase = useMemo(() => httpFromWs(wsUrl, ""), [wsUrl]);

  const wsLive = useWorldClient(wsUrl);
  const { connection, lastError, health } = wsLive;

  // Persist the active tab so a Fast Refresh / hard reload doesn't snap the
  // operator back to Feed every time. Server and first client render both use
  // "feed" so the markup matches; the persisted tab is restored after mount to
  // avoid a hydration mismatch.
  const [tab, setTab] = useState<Tab>("feed");
  useEffect(() => {
    const saved = window.localStorage.getItem("sg.tab");
    if (
      saved === "feed" ||
      saved === "map" ||
      saved === "intel" ||
      saved === "data"
    ) {
      setTab(saved as Tab);
    }
  }, []);
  useEffect(() => {
    window.localStorage.setItem("sg.tab", tab);
  }, [tab]);

  // Map view dimension. Persisted alongside the tab so reloads stay put.
  // Same SSR/CSR pattern: render "2d" first, restore after mount.
  const [mapView, setMapView] = useState<"2d" | "3d">("2d");
  useEffect(() => {
    const saved = window.localStorage.getItem("sg.mapView");
    if (saved === "2d" || saved === "3d") setMapView(saved);
  }, []);
  useEffect(() => {
    window.localStorage.setItem("sg.mapView", mapView);
  }, [mapView]);

  // Environment: outdoor (OSM buildings shown, ops-area form visible) vs
  // indoor (buildings hidden, ops-area hidden — the local SLAM frame stands
  // alone). The OSM polygons are city building footprints in lat/lon and have
  // no relationship to an indoor scene, so showing them indoors looks broken.
  const [environment, setEnvironment] = useState<"outdoor" | "indoor">("outdoor");
  useEffect(() => {
    const saved = window.localStorage.getItem("sg.environment");
    if (saved === "outdoor" || saved === "indoor") setEnvironment(saved);
  }, []);
  useEffect(() => {
    window.localStorage.setItem("sg.environment", environment);
  }, [environment]);

  // Basemap vs grid backdrop for the 2D map. Persisted like mapView. A cached
  // basemap must be staged (Set Area while online) before "BASEMAP" is usable;
  // until then the toggle is disabled and the grid renders.
  const [basemap, setBasemap] = useState<"grid" | "map">("grid");
  useEffect(() => {
    const s = window.localStorage.getItem("sg.basemap");
    if (s === "grid" || s === "map") setBasemap(s);
  }, []);
  useEffect(() => {
    window.localStorage.setItem("sg.basemap", basemap);
  }, [basemap]);
  const [bmStaged, setBmStaged] = useState(false);
  useEffect(() => {
    void fetchBasemapMeta(apiBase).then((m) => setBmStaged(m.staged));
  }, [apiBase, wsLive.buildingsVersion]);

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
      // `f.t` is video-relative seconds (small, ~12.5); downstream consumers
      // (ThreatAlert, IntelPanel, ConsolePanel) assume unix-epoch seconds like
      // the live path (pipeline.py stamps time.time()). Map the current
      // playhead frame onto "now" so "visible"/age/alert math matches live.
      t: Date.now() / 1000,
    };
  }, [playbackData, playbackTime]);

  const playbackDetectionLog = useMemo<DetectionEvent[]>(() => {
    if (!playbackData) return [];
    // Build a rolling log of detection events from the start of the clip up
    // to currentTime. Newest first to match the live console. Stamp each event
    // with a wall-clock epoch in the same time domain the live path uses: the
    // current playhead frame is "now", earlier frames are aged by how far they
    // sit behind the playhead. (Video-relative `f.t` would render as 1970 and
    // break age readouts.)
    const nowEpoch = Date.now() / 1000;
    const log: DetectionEvent[] = [];
    for (const f of playbackData.frames) {
      if (f.t > playbackTime) break;
      if (f.boxes.length > 0) {
        log.push({
          t: nowEpoch - (playbackTime - f.t),
          source: "leader",
          boxes: f.boxes,
        });
      }
    }
    return log.reverse().slice(0, 80);
  }, [playbackData, playbackTime]);

  // Status-bar feeds. In playback we synthesise the same shape the live
  // path uses so StatusBar doesn't need a special mode prop.
  const effectiveOpEntities = isPlayback
    ? operationalEntities(playbackEntities)
    : liveOpEntities;
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

  const mapStatus =
    isPlayback && playbackData
      ? `${effectiveOpEntities.length} entities · t=${playbackTime.toFixed(1)}s`
      : `${effectiveOpEntities.length} entities`;

  return (
    <div className="operator-theme flex h-screen w-screen flex-col bg-bg text-text">
      <header className="relative flex items-center justify-between gap-4 border-b border-border bg-surface/80 px-6 py-3 backdrop-blur-sm">
        <div className="flex items-center gap-4">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/skyguardian-lockup.png"
            alt="SkyGuardian"
            className="h-9 w-auto select-none"
            draggable={false}
          />
          <span className="hidden border-l border-border-strong pl-4 font-mono text-[10px] uppercase tracking-[0.45em] text-text-muted sm:inline">
            Operator
          </span>
          <ClassificationBanner caveat="DEMO" className="hidden md:inline-flex" />
        </div>
        <div className="flex items-center gap-5">
          <div className="hidden lg:block">
            <StatusBar
              connection={effectiveConnection}
              health={effectiveHealth}
              entityCount={effectiveOpEntities.length}
              detectionCount={detectionCount}
            />
          </div>
          <span className="hidden h-5 w-px bg-border lg:block" aria-hidden />
          <CoordReadout
            lat={49.2827}
            lng={-123.1207}
            label="POS"
            className="hidden xl:inline-flex text-text-muted"
          />
          <div className="flex items-center gap-3 border border-border-strong bg-surface-elevated px-4 py-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-ok shadow-glow-cyan" aria-hidden />
            <span className="font-mono text-[9px] uppercase tracking-[0.3em] text-text-dim">Z</span>
            <Clock />
          </div>
        </div>
      </header>

      {lastError && (
        <div className="flex items-center gap-2 border-b border-border-strong bg-surface-elevated px-6 py-1 font-mono text-[10px] uppercase tracking-[0.2em] text-text">
          ▲ Fault: {lastError}
        </div>
      )}

      <div className="border-b border-border bg-surface/60">
        <div className="flex items-center justify-between gap-x-4 px-4">
          <nav className="flex items-stretch gap-0">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={`relative -mb-px border-b-2 px-5 py-2.5 font-sans text-[12px] font-semibold uppercase tracking-[0.25em] transition-colors ${
                  tab === t.id
                    ? "border-text text-text"
                    : "border-transparent text-text-dim hover:text-text-muted"
                }`}
              >
                {tab === t.id && (
                  <span aria-hidden className="mr-2 text-text">▸</span>
                )}
                {t.label}
              </button>
            ))}
          </nav>
          <div className={tab === "feed" ? "shrink-0" : "invisible shrink-0"}>
            <SourceSelector apiBase={apiBase} onState={onSource} />
          </div>
        </div>
      </div>

      <main className="flex min-h-0 flex-1">
        <section className="flex min-h-0 flex-1 flex-col">
          {tab === "feed" && (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="flex min-h-0 flex-1">
                <div className="relative flex min-w-0 flex-1">
                  {/* `key` includes the source kind + (when in file mode) the
                      uploaded filename so React fully unmounts the prior
                      <video> / <img> when we swap modes or swap clips. Without
                      it the old element could linger across a kind change in
                      some browsers (cached frame, paused player) — which the
                      operator reads as "stuck video after clicking RTMP". */}
                  {isPlayback ? (
                    <VideoPlayer
                      key={`pb:${playbackName}`}
                      apiBase={apiBase}
                      name={playbackName}
                      onTimeUpdate={onPlayheadMove}
                    />
                  ) : (
                    <VideoFeed
                      key={`live:${source?.kind ?? "boot"}`}
                      src={leaderSrc}
                      detections={wsLive.detections["leader"]}
                      label="Leader · Recon"
                    />
                  )}
                  {/* Threat alert anchored to the video pane's bottom-right,
                      not the viewport. The viewport corner sits behind the
                      ConsolePanel on this layout — putting the alert here
                      means the operator always sees it on top of the feed. */}
                  <ThreatAlert detections={effectiveDetections} />
                </div>
                <div className="hidden w-80 shrink-0 md:block">
                  <ConsolePanel log={effectiveDetectionLog} />
                </div>
              </div>
            </div>
          )}
          {tab === "map" && (
            <div className="relative min-h-0 flex-1">
              {mapView === "2d" ? (
                basemap === "map" && bmStaged ? (
                  <LocalMapGL
                    entities={effectiveOpEntities}
                    apiBase={apiBase}
                    buildingsVersion={wsLive.buildingsVersion}
                    environment={environment}
                    statusLine={mapStatus}
                  />
                ) : (
                  <LocalMap2D
                    entities={effectiveOpEntities}
                    apiBase={apiBase}
                    buildingsVersion={wsLive.buildingsVersion}
                    environment={environment}
                    statusLine={mapStatus}
                  />
                )
              ) : (
                <LocalMap3D
                  entities={effectiveOpEntities}
                  spanMeters={20}
                  showLandmarks={false}
                  apiBase={apiBase}
                  buildingsRadiusM={800}
                  buildingsVersion={wsLive.buildingsVersion}
                  environment={environment}
                  statusLine={mapStatus}
                />
              )}
              <MapViewToggle value={mapView} onChange={setMapView} />
              {mapView === "2d" && (
                <BasemapToggle value={basemap} onChange={setBasemap} staged={bmStaged} />
              )}
              <EnvironmentToggle value={environment} onChange={setEnvironment} />
              {environment === "outdoor" && (
                <div className="pointer-events-auto absolute left-3 top-3 z-10 max-w-sm">
                  <OperationalArea apiBase={apiBase} />
                </div>
              )}
              <div className="pointer-events-auto absolute left-3 bottom-3 right-3 md:right-auto md:max-w-md">
                <IntelSummaryCard apiBase={apiBase} variant="compact" />
              </div>
              {wsLive.followState && (
                <div className="pointer-events-none absolute right-3 top-3">
                  <FollowInset state={wsLive.followState} />
                </div>
              )}
            </div>
          )}
          {tab === "intel" && (
            <div className="flex min-h-0 flex-1">
              <div className="min-w-0 flex-1 overflow-auto">
                <div className="bg-bg p-5">
                  <SectionHeader index="01" label="Summary" className="mb-3 px-0" />
                  <IntelSummaryCard apiBase={apiBase} />
                </div>
                <IntelPanel detections={effectiveDetections} detectionLog={effectiveDetectionLog} />
              </div>
              <aside className="hidden w-96 shrink-0 border-l border-border bg-bg md:flex md:flex-col">
                <div className="min-h-0 flex-1 overflow-auto p-4">
                  <SectionHeader index="02" label="Intel" className="mb-3 px-0" />
                  <IntelChat apiBase={apiBase} />
                </div>
              </aside>
            </div>
          )}
          {tab === "data" && (
            <div className="min-h-0 flex-1 overflow-auto">
              <FoundryDataView />
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function MapViewToggle({
  value,
  onChange,
}: {
  value: "2d" | "3d";
  onChange: (v: "2d" | "3d") => void;
}) {
  return (
    <div className="pointer-events-auto absolute right-4 top-4 flex border border-border bg-surface/85 font-mono text-[10px] uppercase tracking-[0.3em] backdrop-blur-sm">
      {(["2d", "3d"] as const).map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          aria-pressed={value === v}
          className={`px-3 py-1.5 transition-colors ${
            value === v
              ? "bg-text text-invert"
              : "text-text-dim hover:text-text"
          }`}
        >
          {v.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

function EnvironmentToggle({
  value,
  onChange,
}: {
  value: "outdoor" | "indoor";
  onChange: (v: "outdoor" | "indoor") => void;
}) {
  return (
    <div className="pointer-events-auto absolute right-4 top-14 flex border border-border bg-surface/85 font-mono text-[10px] uppercase tracking-[0.3em] backdrop-blur-sm">
      {(["outdoor", "indoor"] as const).map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          aria-pressed={value === v}
          className={`px-3 py-1.5 transition-colors ${
            value === v
              ? "bg-text text-invert"
              : "text-text-dim hover:text-text"
          }`}
        >
          {v}
        </button>
      ))}
    </div>
  );
}

function BasemapToggle({
  value,
  onChange,
  staged,
}: {
  value: "grid" | "map";
  onChange: (v: "grid" | "map") => void;
  staged: boolean;
}) {
  const opts: { v: "grid" | "map"; label: string }[] = [
    { v: "grid", label: "grid" },
    { v: "map", label: "basemap" },
  ];
  return (
    <div className="pointer-events-auto absolute right-4 top-24 flex border border-border bg-surface/85 font-mono text-[10px] uppercase tracking-[0.3em] backdrop-blur-sm">
      {opts.map(({ v, label }) => {
        const disabled = v === "map" && !staged;
        return (
          <button
            key={v}
            type="button"
            onClick={() => onChange(v)}
            disabled={disabled}
            aria-pressed={value === v}
            title={disabled ? "Set Area while online to cache a basemap" : undefined}
            className={cn(
              "px-3 py-1.5 transition-colors",
              value === v ? "bg-text text-invert" : "text-text-dim hover:text-text",
              disabled && "cursor-not-allowed opacity-40 hover:text-text-dim",
            )}
          >
            {label}
          </button>
        );
      })}
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
