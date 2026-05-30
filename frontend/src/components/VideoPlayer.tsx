"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { PlaybackData, PlaybackBox } from "@/lib/playback";
import { frameAt } from "@/lib/playback";
import { isThreat } from "@/lib/threats";

interface Props {
  /** http origin of the backend (used to build /video/file and /video/detections URLs). */
  apiBase: string;
  /** Filename to play back (matches the upload's safe_name on the backend). */
  name: string;
  /** Optional: notified each time the playhead moves so the Map tab can sync. */
  onTimeUpdate?: (currentTime: number, data: PlaybackData | null) => void;
}

/**
 * Native HTML5 video player with a YOLO box overlay that follows the
 * playhead. The browser handles play/pause/scrub/keyboard controls; we
 * supply the box-drawing canvas on top and look up boxes by currentTime
 * from a sidecar JSON loaded once on mount.
 *
 * Layout: video and canvas live in a `relative` flex column that contains
 * them at their natural aspect via object-contain. The canvas matches the
 * displayed video rect so the boxes (normalised [0,1]) land on the right
 * pixels regardless of letterboxing.
 */
export function VideoPlayer({ apiBase, name, onTimeUpdate }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [data, setData] = useState<PlaybackData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // --- load detections JSON ----------------------------------------------
  useEffect(() => {
    let cancelled = false;
    setData(null);
    setLoadError(null);
    fetch(`${apiBase}/video/detections/${encodeURIComponent(name)}`, { cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as PlaybackData;
      })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setLoadError(String(e?.message ?? e));
      });
    return () => {
      cancelled = true;
    };
  }, [apiBase, name]);

  // --- overlay redraw on time updates / resize / data load ---------------
  const drawOverlay = useCallback(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    const dpr = window.devicePixelRatio || 1;

    const rect = video.getBoundingClientRect();
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

    if (!data) return;
    const frame = frameAt(data.frames, video.currentTime);
    if (!frame || frame.boxes.length === 0) return;

    // The <video> uses object-contain inside its container. Compute the
    // displayed video rect from natural dimensions; otherwise boxes drift
    // into the letterbox margins. Fall back to the JSON's image_w/h if the
    // browser hasn't reported videoWidth yet (e.g. during initial mount).
    const natW = video.videoWidth || data.image_w || 0;
    const natH = video.videoHeight || data.image_h || 0;
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

    // Match the live feed reticle: amber corner brackets, signal-red on threats.
    const AMBER = "#d9a441";
    const RED = "#e0483a";
    ctx.font = "11px ui-monospace, SFMono-Regular, Menlo, monospace";
    for (const b of frame.boxes as PlaybackBox[]) {
      const x = offX + (b.cx - b.w / 2) * dispW;
      const y = offY + (b.cy - b.h / 2) * dispH;
      const bw = b.w * dispW;
      const bh = b.h * dispH;
      const threat = isThreat(b.label);
      const stroke = threat ? RED : AMBER;
      ctx.strokeStyle = threat ? "rgba(224,72,58,0.28)" : "rgba(217,164,65,0.24)";
      ctx.lineWidth = 1;
      ctx.strokeRect(x, y, bw, bh);
      const c = Math.max(7, Math.min(bw, bh) * 0.22);
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, y + c); ctx.lineTo(x, y); ctx.lineTo(x + c, y);
      ctx.moveTo(x + bw - c, y); ctx.lineTo(x + bw, y); ctx.lineTo(x + bw, y + c);
      ctx.moveTo(x + bw, y + bh - c); ctx.lineTo(x + bw, y + bh); ctx.lineTo(x + bw - c, y + bh);
      ctx.moveTo(x + c, y + bh); ctx.lineTo(x, y + bh); ctx.lineTo(x, y + bh - c);
      ctx.stroke();
      const tag = b.label.toUpperCase();
      const pad = 4;
      const tw = ctx.measureText(tag).width + pad * 2;
      const th = 14;
      ctx.fillStyle = "rgba(10,14,9,0.92)";
      ctx.fillRect(x, Math.max(offY, y - th), tw, th);
      ctx.fillStyle = stroke;
      ctx.fillText(tag, x + pad, Math.max(offY + th - 4, y - 4));
    }
  }, [data]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const onTime = () => {
      drawOverlay();
      onTimeUpdate?.(video.currentTime, data);
    };
    video.addEventListener("timeupdate", onTime);
    video.addEventListener("seeked", onTime);
    video.addEventListener("loadedmetadata", onTime);
    video.addEventListener("play", onTime);
    // Also tick on rAF while playing so the overlay updates between
    // timeupdate events (Chrome fires those at ~4 Hz, too coarse for boxes).
    let rafId = 0;
    const loop = () => {
      if (!video.paused && !video.ended) drawOverlay();
      rafId = requestAnimationFrame(loop);
    };
    rafId = requestAnimationFrame(loop);
    const ro = new ResizeObserver(drawOverlay);
    ro.observe(video);
    return () => {
      video.removeEventListener("timeupdate", onTime);
      video.removeEventListener("seeked", onTime);
      video.removeEventListener("loadedmetadata", onTime);
      video.removeEventListener("play", onTime);
      ro.disconnect();
      cancelAnimationFrame(rafId);
    };
  }, [drawOverlay, data, onTimeUpdate]);

  const videoSrc = `${apiBase}/video/file/${encodeURIComponent(name)}`;

  return (
    <div className="relative h-full min-h-0 w-full overflow-hidden rounded-md border border-border bg-bg hud-grid shadow-card">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video
        ref={videoRef}
        src={videoSrc}
        controls
        playsInline
        preload="metadata"
        className="block h-full w-full object-contain bg-bg"
      />
      <canvas
        ref={canvasRef}
        className="pointer-events-none absolute inset-0 m-auto h-full w-full"
      />

      <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-2 border border-border-strong bg-surface/85 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.3em] text-text-muted backdrop-blur-sm">
        <span aria-hidden className="relative inline-flex h-2 w-2">
          <span className={`relative inline-block h-2 w-2 rounded-full ${data ? "bg-ok shadow-glow-cyan" : "bg-fail"}`} />
        </span>
        <span className="text-text">Playback · {name}</span>
      </div>

      {loadError && (
        <div className="absolute inset-x-4 bottom-16 rounded-md border border-fail/60 bg-surface/90 p-3 font-mono text-[10px] uppercase tracking-widest text-fail">
          ▲ Detections fetch failed: {loadError}
        </div>
      )}
    </div>
  );
}
