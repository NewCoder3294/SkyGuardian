"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Entity, EntityType } from "@/lib/contracts";

/**
 * Top-down 2D tactical map. Renders building footprints (offline, from the
 * pre-cached OSM JSON) and live world-model entities into a single Canvas.
 *
 * Why 2D: a 3D scene at the 800 m AO scale buries 6–30 m tall buildings as
 * flat blue patches, and per-entity `<Html>` labels in R3F re-mount on every
 * WS broadcast, which feels glitchy. Canvas draws are idempotent — a WS
 * snapshot just re-paints the same scene at ~steady fps.
 *
 * Axis convention: world (x, y) = (east, north), metres. North → up on
 * screen. The launch point is (0, 0).
 */

interface BuildingRecord {
  id: number | null;
  name: string | null;
  height_m: number;
  polygon: [number, number][];
}

interface BuildingsPayload {
  origin: { lat: number; lng: number };
  radius_m: number;
  count: number;
  buildings: BuildingRecord[];
}

interface Props {
  entities: Entity[];
  apiBase?: string;
  /** Half-width of the initial view, metres. 0 = auto-fit to building cache. */
  initialSpanM?: number;
}

interface ViewState {
  scale: number; // metres per screen pixel
  cx: number; // world east at screen centre
  cy: number; // world north at screen centre
}

export function LocalMap2D({ entities, apiBase, initialSpanM = 0 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<ViewState>({ scale: 1, cx: 0, cy: 0 });
  const entitiesRef = useRef<Entity[]>(entities);
  const buildingsRef = useRef<BuildingRecord[]>([]);
  const hoverRef = useRef<{ x: number; y: number } | null>(null);
  const [buildingsState, setBuildingsState] = useState<
    "loading" | "ready" | "missing"
  >("loading");

  // Keep entities visible to imperative draw() without re-binding the effect.
  entitiesRef.current = entities;

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.fillStyle = "#06121f";
    ctx.fillRect(0, 0, w, h);

    const v = viewRef.current;
    drawGrid(ctx, w, h, v);
    drawBuildings(ctx, w, h, v, buildingsRef.current);
    drawOrigin(ctx, w, h, v);
    drawEntities(ctx, w, h, v, entitiesRef.current);
    drawScaleBar(ctx, w, h, v);
    if (hoverRef.current) drawCursor(ctx, w, h, v, hoverRef.current);
  }, []);

  const fitToBuildings = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (w === 0 || h === 0) return;

    let radius = initialSpanM;
    if (radius <= 0) {
      let maxR = 0;
      for (const b of buildingsRef.current) {
        for (const p of b.polygon) {
          const r = Math.hypot(p[0], p[1]);
          if (r > maxR) maxR = r;
        }
      }
      radius = maxR > 0 ? maxR * 1.05 : 100;
    }
    const span = Math.min(w, h);
    viewRef.current = { scale: (radius * 2) / span, cx: 0, cy: 0 };
    draw();
  }, [draw, initialSpanM]);

  // Load buildings once.
  useEffect(() => {
    if (!apiBase) {
      setBuildingsState("missing");
      return;
    }
    let stopped = false;
    fetch(`${apiBase}/map/buildings`, { cache: "no-store" })
      .then(async (res) => {
        if (res.status === 404) return null;
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as BuildingsPayload;
      })
      .then((d) => {
        if (stopped) return;
        if (d) {
          buildingsRef.current = d.buildings;
          setBuildingsState("ready");
          fitToBuildings();
        } else {
          setBuildingsState("missing");
        }
      })
      .catch(() => {
        if (!stopped) setBuildingsState("missing");
      });
    return () => {
      stopped = true;
    };
  }, [apiBase, fitToBuildings]);

  // Redraw whenever entities change.
  useEffect(() => {
    draw();
  }, [entities, draw]);

  // Resize.
  useEffect(() => {
    const node = wrapRef.current;
    if (!node) return;
    const ro = new ResizeObserver(() => {
      // First resize after mount also handles the initial fit before buildings
      // arrive (so empty-state still looks reasonable).
      if (buildingsRef.current.length === 0 && viewRef.current.scale === 1) {
        viewRef.current = { scale: 0.5, cx: 0, cy: 0 };
      }
      draw();
    });
    ro.observe(node);
    return () => ro.disconnect();
  }, [draw]);

  // Pan + zoom.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;

    const onDown = (e: MouseEvent) => {
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
    };
    const onMove = (e: MouseEvent) => {
      const v = viewRef.current;
      if (dragging) {
        const dx = e.clientX - lastX;
        const dy = e.clientY - lastY;
        lastX = e.clientX;
        lastY = e.clientY;
        v.cx -= dx * v.scale;
        v.cy += dy * v.scale;
        draw();
        return;
      }
      const rect = canvas.getBoundingClientRect();
      hoverRef.current = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      };
      draw();
    };
    const onLeave = () => {
      hoverRef.current = null;
      draw();
    };
    const onUp = () => {
      dragging = false;
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const v = viewRef.current;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const wxBefore = v.cx + (mx - rect.width / 2) * v.scale;
      const wyBefore = v.cy - (my - rect.height / 2) * v.scale;
      const factor = Math.exp(e.deltaY * 0.0012);
      const newScale = Math.max(0.02, Math.min(20, v.scale * factor));
      v.cx = wxBefore - (mx - rect.width / 2) * newScale;
      v.cy = wyBefore + (my - rect.height / 2) * newScale;
      v.scale = newScale;
      draw();
    };

    canvas.addEventListener("mousedown", onDown);
    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mouseleave", onLeave);
    window.addEventListener("mouseup", onUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      canvas.removeEventListener("mousedown", onDown);
      canvas.removeEventListener("mousemove", onMove);
      canvas.removeEventListener("mouseleave", onLeave);
      window.removeEventListener("mouseup", onUp);
      canvas.removeEventListener("wheel", onWheel);
    };
  }, [draw]);

  return (
    <div ref={wrapRef} className="relative h-full w-full bg-bg">
      <canvas
        ref={canvasRef}
        className="block h-full w-full cursor-grab active:cursor-grabbing"
      />
      <div className="pointer-events-none absolute left-4 top-4 space-y-1 rounded-md border border-border-strong bg-surface/80 px-3 py-2 font-mono text-[10px] uppercase tracking-widest text-text-muted backdrop-blur-sm">
        <div className="text-accent">Local frame · top-down</div>
        <div className="text-text-dim">
          {buildingsState === "loading" && "loading buildings…"}
          {buildingsState === "ready" && "drag · scroll zoom"}
          {buildingsState === "missing" && "no buildings cached"}
        </div>
      </div>
      <button
        type="button"
        onClick={fitToBuildings}
        className="absolute right-4 top-4 rounded-md border border-border-strong bg-surface/80 px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest text-text-muted backdrop-blur-sm transition hover:border-accent/60 hover:text-accent"
      >
        Recenter
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Painting primitives
// ---------------------------------------------------------------------------

function worldToScreen(
  e: number,
  n: number,
  w: number,
  h: number,
  v: ViewState,
): [number, number] {
  return [w / 2 + (e - v.cx) / v.scale, h / 2 - (n - v.cy) / v.scale];
}

function screenToWorld(
  sx: number,
  sy: number,
  w: number,
  h: number,
  v: ViewState,
): [number, number] {
  return [v.cx + (sx - w / 2) * v.scale, v.cy - (sy - h / 2) * v.scale];
}

function niceNumber(x: number): number {
  if (x <= 0) return 1;
  const exp = Math.floor(Math.log10(x));
  const f = x / Math.pow(10, exp);
  let nf: number;
  if (f < 1.5) nf = 1;
  else if (f < 3) nf = 2;
  else if (f < 7) nf = 5;
  else nf = 10;
  return nf * Math.pow(10, exp);
}

function drawGrid(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  v: ViewState,
) {
  const targetPx = 80;
  const major = niceNumber(targetPx * v.scale);
  const minor = major / 5;
  const left = v.cx - (w / 2) * v.scale;
  const right = v.cx + (w / 2) * v.scale;
  const top = v.cy + (h / 2) * v.scale;
  const bottom = v.cy - (h / 2) * v.scale;

  // Minor
  ctx.strokeStyle = "rgba(34, 211, 238, 0.05)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = Math.ceil(left / minor) * minor; x <= right; x += minor) {
    const sx = w / 2 + (x - v.cx) / v.scale;
    ctx.moveTo(sx, 0);
    ctx.lineTo(sx, h);
  }
  for (let y = Math.ceil(bottom / minor) * minor; y <= top; y += minor) {
    const sy = h / 2 - (y - v.cy) / v.scale;
    ctx.moveTo(0, sy);
    ctx.lineTo(w, sy);
  }
  ctx.stroke();

  // Major
  ctx.strokeStyle = "rgba(34, 211, 238, 0.14)";
  ctx.beginPath();
  for (let x = Math.ceil(left / major) * major; x <= right; x += major) {
    const sx = w / 2 + (x - v.cx) / v.scale;
    ctx.moveTo(sx, 0);
    ctx.lineTo(sx, h);
  }
  for (let y = Math.ceil(bottom / major) * major; y <= top; y += major) {
    const sy = h / 2 - (y - v.cy) / v.scale;
    ctx.moveTo(0, sy);
    ctx.lineTo(w, sy);
  }
  ctx.stroke();

  // Cardinal axes through origin (slightly brighter).
  const [ox, oy] = worldToScreen(0, 0, w, h, v);
  ctx.strokeStyle = "rgba(34, 211, 238, 0.22)";
  ctx.beginPath();
  ctx.moveTo(0, oy);
  ctx.lineTo(w, oy);
  ctx.moveTo(ox, 0);
  ctx.lineTo(ox, h);
  ctx.stroke();
}

function drawBuildings(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  v: ViewState,
  buildings: BuildingRecord[],
) {
  if (buildings.length === 0) return;

  // World-space bbox of the viewport, padded a polygon-radius for safety.
  const left = v.cx - (w / 2) * v.scale - 50;
  const right = v.cx + (w / 2) * v.scale + 50;
  const bottom = v.cy - (h / 2) * v.scale - 50;
  const top = v.cy + (h / 2) * v.scale + 50;

  ctx.lineWidth = 1;
  for (const b of buildings) {
    if (b.polygon.length < 3) continue;

    // Cheap bbox cull on the polygon vs viewport.
    let bxMin = Infinity,
      bxMax = -Infinity,
      byMin = Infinity,
      byMax = -Infinity;
    for (const p of b.polygon) {
      if (p[0] < bxMin) bxMin = p[0];
      if (p[0] > bxMax) bxMax = p[0];
      if (p[1] < byMin) byMin = p[1];
      if (p[1] > byMax) byMax = p[1];
    }
    if (bxMax < left || bxMin > right || byMax < bottom || byMin > top) continue;

    // Taller building → slightly hotter fill so the campus has visual depth.
    const t = Math.max(0, Math.min(1, (b.height_m - 4) / 40));
    const fillAlpha = 0.22 + t * 0.28;
    const strokeAlpha = 0.45 + t * 0.35;

    ctx.fillStyle = `rgba(34, 211, 238, ${fillAlpha.toFixed(3)})`;
    ctx.strokeStyle = `rgba(34, 211, 238, ${strokeAlpha.toFixed(3)})`;

    ctx.beginPath();
    const first = b.polygon[0];
    const [fx, fy] = worldToScreen(first[0], first[1], w, h, v);
    ctx.moveTo(fx, fy);
    for (let i = 1; i < b.polygon.length; i++) {
      const p = b.polygon[i];
      const [sx, sy] = worldToScreen(p[0], p[1], w, h, v);
      ctx.lineTo(sx, sy);
    }
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }
}

function drawOrigin(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  v: ViewState,
) {
  const [x, y] = worldToScreen(0, 0, w, h, v);
  if (x < -50 || y < -50 || x > w + 50 || y > h + 50) return;

  ctx.strokeStyle = "#22d3ee";
  ctx.fillStyle = "#22d3ee";
  ctx.lineWidth = 1.5;

  ctx.beginPath();
  ctx.arc(x, y, 10, 0, Math.PI * 2);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(x, y, 3, 0, Math.PI * 2);
  ctx.fill();

  ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, monospace";
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "#22d3ee";
  ctx.fillText("LAUNCH", x + 16, y);
}

function drawEntities(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  v: ViewState,
  entities: Entity[],
) {
  if (entities.length === 0) return;
  const labelFont = "10px ui-monospace, SFMono-Regular, Menlo, monospace";
  for (const e of entities) {
    const [x, y] = worldToScreen(e.position.x, e.position.y, w, h, v);
    if (x < -40 || y < -40 || x > w + 40 || y > h + 40) continue;
    const alpha =
      e.status === "active" ? 1 : e.status === "stale" ? 0.55 : 0.28;
    drawEntityGlyph(ctx, x, y, e.type, alpha);

    if (e.status !== "lost") {
      const label = (e.label ?? e.id).toUpperCase().slice(0, 14);
      ctx.font = labelFont;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillStyle = `rgba(34, 211, 238, ${(alpha * 0.9).toFixed(3)})`;
      ctx.fillText(label, x + 10, y - 10);
    }
  }
}

function drawEntityGlyph(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  type: EntityType,
  alpha: number,
) {
  ctx.lineWidth = 1.5;
  const stroke = `rgba(34, 211, 238, ${alpha.toFixed(3)})`;
  const fill = `rgba(34, 211, 238, ${(alpha * 0.45).toFixed(3)})`;
  ctx.strokeStyle = stroke;
  ctx.fillStyle = fill;

  switch (type) {
    case "soldier": {
      ctx.beginPath();
      ctx.arc(x, y, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      return;
    }
    case "drone": {
      // Triangle pointing up.
      ctx.beginPath();
      ctx.moveTo(x, y - 7);
      ctx.lineTo(x + 6, y + 5);
      ctx.lineTo(x - 6, y + 5);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      return;
    }
    case "poi": {
      // Diamond.
      ctx.beginPath();
      ctx.moveTo(x, y - 7);
      ctx.lineTo(x + 7, y);
      ctx.lineTo(x, y + 7);
      ctx.lineTo(x - 7, y);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      return;
    }
    case "hazard": {
      // Warn X.
      ctx.strokeStyle = `rgba(245, 158, 11, ${alpha.toFixed(3)})`;
      ctx.beginPath();
      ctx.moveTo(x - 6, y - 6);
      ctx.lineTo(x + 6, y + 6);
      ctx.moveTo(x + 6, y - 6);
      ctx.lineTo(x - 6, y + 6);
      ctx.stroke();
      return;
    }
    default: {
      ctx.beginPath();
      ctx.arc(x, y, 3.5, 0, Math.PI * 2);
      ctx.fill();
      return;
    }
  }
}

function drawScaleBar(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  v: ViewState,
) {
  // Target ~120 px bar.
  const metres = niceNumber(120 * v.scale);
  const px = metres / v.scale;
  const x0 = w - 24 - px;
  const x1 = w - 24;
  const y = h - 24;

  ctx.strokeStyle = "rgba(147, 177, 203, 0.7)";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(x0, y);
  ctx.lineTo(x1, y);
  ctx.moveTo(x0, y - 4);
  ctx.lineTo(x0, y + 4);
  ctx.moveTo(x1, y - 4);
  ctx.lineTo(x1, y + 4);
  ctx.stroke();

  ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, monospace";
  ctx.textAlign = "right";
  ctx.textBaseline = "bottom";
  ctx.fillStyle = "rgba(147, 177, 203, 0.9)";
  ctx.fillText(formatMetres(metres), x1, y - 6);
}

function drawCursor(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  v: ViewState,
  cursor: { x: number; y: number },
) {
  const [wx, wy] = screenToWorld(cursor.x, cursor.y, w, h, v);
  ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, monospace";
  ctx.textAlign = "left";
  ctx.textBaseline = "bottom";
  ctx.fillStyle = "rgba(147, 177, 203, 0.75)";
  ctx.fillText(
    `E ${wx.toFixed(0)} m   N ${wy.toFixed(0)} m`,
    16,
    h - 8,
  );
}

function formatMetres(m: number): string {
  if (m >= 1000) return `${(m / 1000).toFixed(m % 1000 === 0 ? 0 : 1)} km`;
  return `${m.toFixed(0)} m`;
}
