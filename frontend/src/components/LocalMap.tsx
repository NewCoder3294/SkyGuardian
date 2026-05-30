"use client";

import { useEffect, useRef } from "react";
import type { Entity, EntityStatus } from "@/lib/contracts";
import { MapProjection } from "@/lib/projection";

// Light theme: black ink on white paper. Entities differentiated by SHAPE,
// status by alpha. No hue anywhere.
const INK = "#0a0a0a";
const PAPER = "#ffffff";

const STATUS_ALPHA: Record<EntityStatus, number> = {
  active: 1.0,
  stale: 0.55,
  lost: 0.28,
};

interface Props {
  entities: Entity[];
  spanMeters?: number;
}

export function LocalMap({ entities, spanMeters = 20 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;

    const dpr = window.devicePixelRatio || 1;
    const proj = new MapProjection(spanMeters);

    const draw = () => {
      const rect = wrap.getBoundingClientRect();
      const w = Math.max(1, Math.floor(rect.width));
      const h = Math.max(1, Math.floor(rect.height));
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = `${w}px`;
        canvas.style.height = `${h}px`;
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      drawBackground(ctx, w, h);
      drawGrid(ctx, w, h, proj.scale(w, h));
      drawOrigin(ctx, w, h);
      for (const e of entities) drawEntity(ctx, e, proj, w, h);
    };

    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [entities, spanMeters]);

  return (
    <div ref={wrapRef} className="relative h-full w-full bg-bg">
      <canvas ref={canvasRef} className="block h-full w-full" />
    </div>
  );
}

function drawBackground(ctx: CanvasRenderingContext2D, w: number, h: number) {
  ctx.fillStyle = PAPER;
  ctx.fillRect(0, 0, w, h);
}

function drawGrid(ctx: CanvasRenderingContext2D, w: number, h: number, step: number) {
  if (step <= 1) return;
  ctx.strokeStyle = "rgba(10,10,10,0.08)";
  ctx.lineWidth = 0.5;
  ctx.beginPath();
  for (let x = w / 2; x <= w; x += step) {
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
  }
  for (let x = w / 2 - step; x >= 0; x -= step) {
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
  }
  for (let y = h / 2; y <= h; y += step) {
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
  }
  for (let y = h / 2 - step; y >= 0; y -= step) {
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
  }
  ctx.stroke();

  const major = step * 5;
  ctx.strokeStyle = "rgba(10,10,10,0.18)";
  ctx.lineWidth = 0.5;
  ctx.beginPath();
  for (let x = w / 2; x <= w; x += major) {
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
  }
  for (let x = w / 2 - major; x >= 0; x -= major) {
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
  }
  for (let y = h / 2; y <= h; y += major) {
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
  }
  for (let y = h / 2 - major; y >= 0; y -= major) {
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
  }
  ctx.stroke();
}

function drawOrigin(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const cx = w / 2;
  const cy = h / 2;
  ctx.strokeStyle = "rgba(10,10,10,0.7)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(cx - 10, cy);
  ctx.lineTo(cx + 10, cy);
  ctx.moveTo(cx, cy - 10);
  ctx.lineTo(cx, cy + 10);
  ctx.stroke();
  ctx.fillStyle = "rgba(10,10,10,0.7)";
  ctx.font = "600 9px ui-monospace, SFMono-Regular, Menlo, monospace";
  ctx.textAlign = "center";
  ctx.fillText("LAUNCH", cx, cy + 22);
}

function drawEntity(
  ctx: CanvasRenderingContext2D,
  e: Entity,
  proj: MapProjection,
  w: number,
  h: number,
) {
  const { x, y } = proj.project(e.position, w, h);
  ctx.globalAlpha = STATUS_ALPHA[e.status];
  ctx.fillStyle = INK;
  ctx.strokeStyle = INK;
  const r = e.type === "soldier" || e.type === "drone" ? 8 : 6;

  switch (e.type) {
    case "soldier":
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
      break;
    case "drone":
      ctx.beginPath();
      ctx.moveTo(x, y - r);
      ctx.lineTo(x - r, y + r * 0.8);
      ctx.lineTo(x + r, y + r * 0.8);
      ctx.closePath();
      ctx.fill();
      break;
    case "poi":
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(x, y - r);
      ctx.lineTo(x + r, y);
      ctx.lineTo(x, y + r);
      ctx.lineTo(x - r, y);
      ctx.closePath();
      ctx.stroke();
      break;
    case "hazard":
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x - r, y - r);
      ctx.lineTo(x + r, y + r);
      ctx.moveTo(x + r, y - r);
      ctx.lineTo(x - r, y + r);
      ctx.stroke();
      break;
    case "object":
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fill();
      break;
  }

  if (e.label) {
    ctx.font = "8px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.textAlign = "center";
    ctx.fillText(e.label.toUpperCase(), x, y - r - 6);
  }
  ctx.globalAlpha = 1;
}
