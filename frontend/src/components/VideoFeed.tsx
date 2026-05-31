"use client";

import { useEffect, useRef, useState } from "react";
import type { DetectionLayer } from "@/lib/useWorldClient";
import { isThreat } from "@/lib/threats";

interface Props {
  /** Base URL for the single-frame JPEG endpoint. Polled at ~10 Hz. */
  src: string;
  /** Latest detection layer for this feed. */
  detections: DetectionLayer | undefined;
  /** Display label shown in the corner badge. */
  label: string;
  /** Frame poll interval (ms). 100 = 10 fps; tune lower for smoother video. */
  pollMs?: number;
}

/**
 * Live video as a polled single-frame JPEG with YOLO bounding boxes overlaid
 * on a canvas.
 *
 * Why polled instead of <img src=mjpg>: a multipart/x-mixed-replace stream
 * keeps the browser tab's loading spinner active forever and triggers
 * continuous layout passes. Polling completes every request, so the tab
 * settles between frames and operators stop perceiving "the tab is
 * refreshing." Each frame is fetched as a Blob → Object URL → assigned to
 * img.src, then revoked on the next frame.
 */
export function VideoFeed({ src, detections, label, pollMs = 100 }: Props) {
  const imgRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hasFrame, setHasFrame] = useState(false);
  const [errored, setErrored] = useState(false);

  // Live signal: a real JPEG frame has been fetched. Don't trust the
  // detections timestamp alone — backend keeps broadcasting empty-detection
  // frames before any video has connected, which would falsely flip the
  // Leader badge green.
  const isLive = hasFrame;

  // --- frame polling loop ------------------------------------------------
  useEffect(() => {
    let stopped = false;
    let currentUrl: string | null = null;
    let timer: number | null = null;

    const tick = async () => {
      if (stopped) return;
      try {
        const res = await fetch(`${src}?n=${Date.now()}`, { cache: "no-store" });
        if (res.status === 200) {
          const blob = await res.blob();
          const url = URL.createObjectURL(blob);
          if (imgRef.current) imgRef.current.src = url;
          if (currentUrl) URL.revokeObjectURL(currentUrl);
          currentUrl = url;
          setHasFrame(true);
          setErrored(false);
        }
        // 204 = no frame yet; just retry next tick.
      } catch {
        setErrored(true);
      } finally {
        if (!stopped) timer = window.setTimeout(tick, pollMs);
      }
    };

    tick();
    return () => {
      stopped = true;
      if (timer != null) window.clearTimeout(timer);
      if (currentUrl) URL.revokeObjectURL(currentUrl);
    };
  }, [src, pollMs]);

  // --- box overlay -------------------------------------------------------
  // Only draws when a real frame is loaded (`hasFrame`). Without that gate,
  // the canvas re-renders on every WS detection tick even after a tab switch
  // — producing stretched orphan rectangles floating over the "linking feed"
  // overlay (no <img> for them to align to). The clear-when-not-live path
  // also wipes any previously-drawn boxes the moment the feed drops.
  useEffect(() => {
    const img = imgRef.current;
    const canvas = canvasRef.current;
    if (!img || !canvas) return;
    const dpr = window.devicePixelRatio || 1;

    const clear = () => {
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    };

    if (!hasFrame) {
      clear();
      return;
    }

    const draw = () => {
      const rect = img.getBoundingClientRect();
      const containerW = Math.max(1, Math.floor(rect.width));
      const containerH = Math.max(1, Math.floor(rect.height));
      if (canvas.width !== containerW * dpr || canvas.height !== containerH * dpr) {
        canvas.width = containerW * dpr;
        canvas.height = containerH * dpr;
        canvas.style.width = `${containerW}px`;
        canvas.style.height = `${containerH}px`;
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, containerW, containerH);

      // <img> uses object-contain — letterboxed inside the container. Project
      // normalised boxes onto the actually-displayed image rect, not the box.
      const natW = img.naturalWidth || (detections?.imageW ?? 0);
      const natH = img.naturalHeight || (detections?.imageH ?? 0);
      // If we still don't know the image's natural aspect, skip drawing —
      // projecting onto the raw container produces stretched boxes that don't
      // match the visible video.
      if (natW <= 0 || natH <= 0) return;

      let dispW = containerW;
      let dispH = containerH;
      let offX = 0;
      let offY = 0;
      const containerAspect = containerW / containerH;
      const imgAspect = natW / natH;
      if (imgAspect > containerAspect) {
        dispW = containerW;
        dispH = containerW / imgAspect;
        offY = (containerH - dispH) / 2;
      } else {
        dispH = containerH;
        dispW = containerH * imgAspect;
        offX = (containerW - dispW) / 2;
      }

      const boxes = detections?.boxes ?? [];
      // Tactical reticle: amber corner brackets (targeting frame) over a faint
      // full outline, with a square label tab. Threat classes lock in signal
      // red instead of amber — the only place red appears on the feed.
      const AMBER = "#d9a441";
      const RED = "#e0483a";
      ctx.font = "11px ui-monospace, SFMono-Regular, Menlo, monospace";
      for (const b of boxes) {
        const x = offX + (b.cx - b.w / 2) * dispW;
        const y = offY + (b.cy - b.h / 2) * dispH;
        const bw = b.w * dispW;
        const bh = b.h * dispH;
        const threat = isThreat(b.label);
        const stroke = threat ? RED : AMBER;
        // faint full frame
        ctx.strokeStyle = threat ? "rgba(224,72,58,0.28)" : "rgba(217,164,65,0.24)";
        ctx.lineWidth = 1;
        ctx.strokeRect(x, y, bw, bh);
        // corner brackets
        const c = Math.max(7, Math.min(bw, bh) * 0.22);
        ctx.strokeStyle = stroke;
        ctx.lineWidth = 2;
        ctx.beginPath();
        // top-left
        ctx.moveTo(x, y + c); ctx.lineTo(x, y); ctx.lineTo(x + c, y);
        // top-right
        ctx.moveTo(x + bw - c, y); ctx.lineTo(x + bw, y); ctx.lineTo(x + bw, y + c);
        // bottom-right
        ctx.moveTo(x + bw, y + bh - c); ctx.lineTo(x + bw, y + bh); ctx.lineTo(x + bw - c, y + bh);
        // bottom-left
        ctx.moveTo(x + c, y + bh); ctx.lineTo(x, y + bh); ctx.lineTo(x, y + bh - c);
        ctx.stroke();
        // label tab
        const tag = b.label.toUpperCase();
        const pad = 4;
        const tw = ctx.measureText(tag).width + pad * 2;
        const th = 14;
        ctx.fillStyle = "rgba(10,14,9,0.92)";
        ctx.fillRect(x, Math.max(offY, y - th), tw, th);
        ctx.fillStyle = stroke;
        ctx.fillText(tag, x + pad, Math.max(offY + th - 4, y - 4));
      }
    };

    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(img);
    return () => ro.disconnect();
  }, [detections, hasFrame]);

  // 1x1 transparent placeholder so the <img> has a valid src before the first
  // polled frame arrives. Without this, browsers render a "broken image" icon
  // and the img collapses to its intrinsic alt-text size — which then makes
  // the parent flex/grid cell collapse too.
  const PLACEHOLDER =
    "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

  return (
    <div className="tac-corners relative h-full min-h-0 w-full overflow-hidden border border-border bg-bg hud-grid shadow-card">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        ref={imgRef}
        src={PLACEHOLDER}
        alt=""
        className="block h-full w-full object-contain"
        style={{ visibility: hasFrame ? "visible" : "hidden" }}
      />
      <canvas
        ref={canvasRef}
        className="pointer-events-none absolute inset-0 m-auto h-full w-full"
      />
      {/* Boresight crosshair — fixed graticule the operator reads against. */}
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <span className="absolute left-1/2 top-1/2 h-px w-5 -translate-x-1/2 -translate-y-1/2 bg-accent/30" />
        <span className="absolute left-1/2 top-1/2 h-5 w-px -translate-x-1/2 -translate-y-1/2 bg-accent/30" />
      </div>
      {/* No "linking feed…" placeholder. When nothing's connected the pane
          stays visually empty — the LEADER status dot + the "Source" toolbar
          already tell the operator what's going on. A pulsing prompt here
          would just imply something is actively trying. The fault state
          ("feed offline") is preserved because it's actionable. */}
      {errored && (
        <div className="absolute inset-0 grid place-items-center">
          <div className="border border-fail/60 bg-surface/90 px-4 py-2 font-mono text-[11px] uppercase tracking-[0.3em] text-fail">
            ▲ Feed offline
          </div>
        </div>
      )}
      <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-2 border border-border-strong bg-bg px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.3em] text-text-muted">
        <span aria-hidden className="relative inline-flex h-2 w-2">
          {isLive && (
            <span className="absolute inset-0 animate-ping rounded-full bg-accent opacity-60" />
          )}
          <span
            className={`relative inline-block h-2 w-2 rounded-full ${
              isLive ? "bg-accent shadow-glow-cyan" : "bg-fail"
            }`}
          />
        </span>
        <span className="text-text">{label}</span>
      </div>
    </div>
  );
}
