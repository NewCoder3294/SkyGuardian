"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import { Protocol } from "pmtiles";
import "maplibre-gl/dist/maplibre-gl.css";
import { buildBasemapStyle } from "@/lib/basemapStyle";
import { fetchBasemapMeta } from "@/lib/basemapMeta";
import { localMetersToLatLng } from "@/lib/projection";
import { isDesignatedTarget } from "@/lib/entities";
import type { Entity } from "@/lib/contracts";
import { cn } from "@/lib/cn";

/**
 * MapLibre rendering of the offline monochrome basemap with the live SLAM /
 * world-model entity overlay. Drop-in for {@link LocalMap2D}: it accepts the
 * same props (plus optional selection callbacks) and renders entities with the
 * same colour discipline — strict monochrome ink, red reserved strictly for
 * threats (hazards + the designated recon target).
 *
 * Axis convention matches LocalMap2D: world (x, y) = (east, north) metres,
 * north-up. The map is locked north-up (no rotate/pitch) and all network
 * requests are denied unless they resolve to a local origin (offline guard).
 */

interface Props {
  entities: Entity[];
  apiBase?: string;
  /** Half-width of the initial view, metres. Accepted for drop-in parity. */
  initialSpanM?: number;
  /** Optional single-line status (entity count, playback time, etc.). */
  statusLine?: string;
  buildingsVersion?: number;
  environment?: "outdoor" | "indoor";
  /** Optional: notified with an entity id when its glyph is clicked. */
  onSelect?: (id: string) => void;
  /** Optional: currently selected entity id (reserved for highlight use). */
  selectedId?: string;
}

const ORIGIN: { lat: number; lng: number } = { lat: 0, lng: 0 };
const INK = "#202020";
const PAPER = "#f1f1f0";
const THREAT_RED = "#e0483a"; // threat red — hazards + designated target only

/** Threat predicate, mirrored from LocalMap2D: hazards and the designated
 *  recon target render red; everything else stays monochrome ink. */
function isThreatEntity(e: Entity): boolean {
  return e.type === "hazard" || isDesignatedTarget(e);
}

/** Short label, mirrored from LocalMap2D's drawEntities: uppercase id/label,
 *  capped at 14 chars for ordinary tracks; the designated callout is uncapped. */
function shortLabel(e: Entity): string {
  const raw = (e.label ?? e.id).toUpperCase();
  return isDesignatedTarget(e) ? raw : raw.slice(0, 14);
}

function entitiesToGeoJSON(
  entities: Entity[],
  origin: { lat: number; lng: number },
): GeoJSON.FeatureCollection<GeoJSON.Point> {
  const features: GeoJSON.Feature<GeoJSON.Point>[] = entities
    .filter((e) => e.status !== "lost")
    .map((e) => {
      const { lat, lng } = localMetersToLatLng(origin, e.position.x, e.position.y);
      return {
        type: "Feature",
        geometry: { type: "Point", coordinates: [lng, lat] },
        properties: {
          id: e.id,
          kind: e.type,
          label: shortLabel(e),
          threat: isThreatEntity(e),
        },
      };
    });
  return { type: "FeatureCollection", features };
}

export function LocalMapGL({
  entities,
  apiBase = "",
  statusLine,
  onSelect,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const resizeObsRef = useRef<ResizeObserver | null>(null);
  const loadedRef = useRef(false);
  const originRef = useRef<{ lat: number; lng: number }>({ ...ORIGIN });
  const entitiesRef = useRef<Entity[]>(entities);
  const onSelectRef = useRef<Props["onSelect"]>(onSelect);

  // Keep imperative MapLibre handlers reading the latest props without
  // re-binding the mount effect (which must run exactly once).
  entitiesRef.current = entities;
  onSelectRef.current = onSelect;

  // Mount once: register the pmtiles protocol, fetch the geo origin, build the
  // map, wire the SLAM overlay. Tear everything down on unmount.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const protocol = new Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);

    let cancelled = false;
    let map: maplibregl.Map | null = null;

    // Offline guard: permit only requests that resolve to an allowed ORIGIN.
    // Compare on parsed origin (not string prefix) so look-alike hosts like
    // `http://localhost:8000.evil.com` or userinfo tricks (`...@evil.com`)
    // can't slip past. apiBase may be "" (same-origin).
    const base = typeof window !== "undefined" ? window.location.href : undefined;
    const allowedOrigins = new Set<string>();
    if (typeof window !== "undefined") allowedOrigins.add(window.location.origin);
    if (apiBase) {
      try {
        allowedOrigins.add(new URL(apiBase, base).origin);
      } catch {
        /* malformed apiBase → only same-origin is allowed */
      }
    }
    const transformRequest: maplibregl.RequestTransformFunction = (url) => {
      const probe = url.startsWith("pmtiles://") ? url.slice("pmtiles://".length) : url;
      try {
        // Relative URLs resolve against the page origin (same-origin → allowed).
        return allowedOrigins.has(new URL(probe, base).origin) ? { url } : { url: "" };
      } catch {
        return { url: "" };
      }
    };

    fetchBasemapMeta(apiBase).then((meta) => {
      if (cancelled || !containerRef.current) return;
      const origin = {
        lat: meta.origin.lat ?? 0,
        lng: meta.origin.lng ?? 0,
      };
      originRef.current = origin;
      const bbox =
        Array.isArray(meta.bbox) && meta.bbox.length === 4
          ? (meta.bbox as [number, number, number, number])
          : null;
      // Stay within the extracted zoom range so MapLibre never requests tiles
      // above the archive's maxzoom (which would render blank).
      const fitZoom = Math.min(meta.maxzoom || 15, 16);

      map = new maplibregl.Map({
        container: containerRef.current,
        style: buildBasemapStyle(apiBase),
        center: [origin.lng, origin.lat],
        zoom: Math.min(fitZoom, 15),
        maxZoom: fitZoom,
        dragRotate: false,
        pitchWithRotate: false,
        attributionControl: {},
        transformRequest,
      });
      mapRef.current = map;

      // North-up lock.
      map.dragRotate.disable();
      map.touchZoomRotate.disableRotation();
      map.keyboard.disableRotation?.();

      map.addControl(new maplibregl.ScaleControl({ unit: "metric" }));

      // GL canvas can initialise at 0×0 if the flex container hasn't settled;
      // resize on container changes so the map paints instead of staying blank.
      const ro = new ResizeObserver(() => mapRef.current?.resize());
      ro.observe(containerRef.current);
      resizeObsRef.current = ro;

      map.on("load", () => {
        const m = mapRef.current;
        if (!m) return;

        // Force a layout measure, then frame the cached area exactly.
        m.resize();
        if (bbox) {
          m.fitBounds(
            [
              [bbox[0], bbox[1]],
              [bbox[2], bbox[3]],
            ],
            { padding: 32, maxZoom: fitZoom, duration: 0 },
          );
        }

        m.addSource("slam", {
          type: "geojson",
          data: entitiesToGeoJSON(entitiesRef.current, originRef.current),
        });

        m.addLayer({
          id: "slam-entities",
          type: "circle",
          source: "slam",
          paint: {
            "circle-radius": 5,
            "circle-color": [
              "case",
              ["get", "threat"],
              THREAT_RED,
              INK,
            ],
            "circle-stroke-width": 1.5,
            "circle-stroke-color": PAPER,
          },
        });

        m.addLayer({
          id: "slam-labels",
          type: "symbol",
          source: "slam",
          layout: {
            "text-field": ["get", "label"],
            "text-font": ["Noto Sans Regular"],
            "text-size": 10,
            "text-offset": [0, -1.2],
            "text-anchor": "bottom",
            "text-letter-spacing": 0.04,
          },
          paint: {
            "text-color": [
              "case",
              ["get", "threat"],
              THREAT_RED,
              INK,
            ],
            "text-halo-color": PAPER,
            "text-halo-width": 1.2,
          },
        });

        loadedRef.current = true;

        // Selection wiring (optional).
        if (onSelectRef.current) {
          m.on("click", "slam-entities", (e) => {
            const id = e.features?.[0]?.properties?.id;
            if (id !== undefined && id !== null) onSelectRef.current?.(String(id));
          });
          m.on("mouseenter", "slam-entities", () => {
            m.getCanvas().style.cursor = "pointer";
          });
          m.on("mouseleave", "slam-entities", () => {
            m.getCanvas().style.cursor = "";
          });
        }
      });
    });

    return () => {
      cancelled = true;
      loadedRef.current = false;
      resizeObsRef.current?.disconnect();
      resizeObsRef.current = null;
      const m = mapRef.current;
      mapRef.current = null;
      if (m) m.remove();
      try {
        maplibregl.removeProtocol("pmtiles");
      } catch {
        // protocol already removed / never registered — ignore.
      }
    };
    // apiBase is the only external dependency; entities + onSelect are read
    // through refs so the map is built exactly once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase]);

  // Reactive overlay update: push new entity geometry into the source once the
  // map + source exist.
  useEffect(() => {
    const m = mapRef.current;
    if (!m || !loadedRef.current) return;
    const source = m.getSource("slam") as maplibregl.GeoJSONSource | undefined;
    source?.setData(entitiesToGeoJSON(entities, originRef.current));
  }, [entities]);

  return (
    <div className="relative h-full w-full bg-bg">
      {/* MapLibre forces position:relative on its container, which would void an
          `absolute inset-0` and collapse the element to 0 height — give it an
          intrinsic h-full/w-full box instead so the GL canvas gets real size. */}
      <div ref={containerRef} className="h-full w-full" />
      <div className="tac-corners absolute left-4 top-4 border border-border-strong bg-surface/85 backdrop-blur-sm">
        <div className="space-y-1 px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest text-text-muted">
          <div className="text-text-dim">drag · scroll zoom</div>
          {statusLine && <div className={cn("text-text-muted")}>{statusLine}</div>}
        </div>
      </div>
    </div>
  );
}
