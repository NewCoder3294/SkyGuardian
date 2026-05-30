"use client";

import { useEffect, useRef, useState } from "react";
import type { DetectionLayer } from "@/lib/useWorldClient";

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
  useEffect(() => {
    const img = imgRef.current;
    const canvas = canvasRef.current;
    if (!img || !canvas) return;
    const dpr = window.devicePixelRatio || 1;

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
      let dispW = containerW;
      let dispH = containerH;
      let offX = 0;
      let offY = 0;
      if (natW > 0 && natH > 0) {
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
      }

      const boxes = detections?.boxes ?? [];
      ctx.strokeStyle = "#0a0a0a";
      ctx.lineWidth = 1.5;
      ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, monospace";

      for (const b of boxes) {
        const x = offX + (b.cx - b.w / 2) * dispW;
        const y = offY + (b.cy - b.h / 2) * dispH;
        const bw = b.w * dispW;
        const bh = b.h * dispH;
        ctx.strokeRect(x, y, bw, bh);
        const tag = `${b.label.toUpperCase()} ${(b.confidence * 100).toFixed(0)}`;
        const pad = 3;
        const tw = ctx.measureText(tag).width + pad * 2;
        const th = 12;
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(x, Math.max(offY, y - th), tw, th);
        ctx.fillStyle = "#0a0a0a";
        ctx.fillText(tag, x + pad, Math.max(offY + th - 3, y - 3));
      }
    };

    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(img);
    return () => ro.disconnect();
  }, [detections]);

  // 1x1 transparent placeholder so the <img> has a valid src before the first
  // polled frame arrives. Without this, browsers render a "broken image" icon
  // and the img collapses to its intrinsic alt-text size — which then makes
  // the parent flex/grid cell collapse too.
  const PLACEHOLDER =
    "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

  return (
    <div className="relative h-full min-h-0 w-full bg-surface-elevated">
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
      {!hasFrame && (
        <div className="absolute inset-0 grid place-items-center">
          <div className="rounded-sm border border-border bg-surface px-3 py-2 font-mono text-[10px] uppercase tracking-[0.3em] text-text-dim">
            {errored ? "feed offline" : "linking feed…"}
          </div>
        </div>
      )}
      <div className="pointer-events-none absolute left-2 top-2 flex items-center gap-1.5 rounded-sm border border-border bg-surface/90 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.3em] text-text">
        <span aria-hidden className="relative inline-flex h-2 w-2">
          {isLive && (
            <span className="absolute inset-0 animate-ping rounded-full bg-ok opacity-60" />
          )}
          <span
            className={`relative inline-block h-2 w-2 rounded-full ${
              isLive ? "bg-ok" : "bg-fail"
            }`}
          />
        </span>
        {label}
      </div>
    </div>
  );
}
