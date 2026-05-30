"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface UploadStatus {
  name: string | null;
  state: "idle" | "uploading" | "processing" | "ready" | "error";
  progress: number;
  error: string | null;
  duration_s: number;
  frame_count: number;
  detection_count: number;
}

export interface SourceState {
  kind: "rtmp" | "file" | "device" | "none";
  label: string;
  streaming: boolean;
  rtmp_default: string;
  upload?: UploadStatus;
}

interface Props {
  /** http origin of the backend (derived from the WS URL upstream). */
  apiBase: string;
  /** Notified whenever the polled source state changes. The parent uses this
   *  to swap between live VideoFeed and playback VideoPlayer. */
  onState?: (state: SourceState | null) => void;
}

/**
 * Toolbar that lets the operator pick the leader video source — live RTMP or
 * a pre-recorded clip. RTMP uses the live perception pipeline; file uploads
 * are pre-processed once and then played back natively with a scrubber.
 */
export function SourceSelector({ apiBase, onState }: Props) {
  const [state, setState] = useState<SourceState | null>(null);
  const [busy, setBusy] = useState<"" | "rtmp" | "upload">("");
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/video/source`, { cache: "no-store" });
      if (res.ok) {
        const s = (await res.json()) as SourceState;
        setState(s);
        onState?.(s);
      }
    } catch {
      // Ignore; we'll retry on the interval.
    }
  }, [apiBase, onState]);

  useEffect(() => {
    refresh();
    // Poll faster during upload/processing so the progress bar feels live.
    const isActive =
      state?.upload?.state === "uploading" || state?.upload?.state === "processing";
    const interval = isActive ? 500 : 2000;
    const t = window.setInterval(refresh, interval);
    return () => window.clearInterval(t);
  }, [refresh, state?.upload?.state]);

  const switchToRtmp = async () => {
    setBusy("rtmp");
    setError(null);
    try {
      const res = await fetch(`${apiBase}/video/source/rtmp`, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body?.detail ?? `HTTP ${res.status}`);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy("");
      refresh();
    }
  };

  const onFilePicked = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy("upload");
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const res = await fetch(`${apiBase}/video/source/upload`, {
        method: "POST",
        body: fd,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body?.detail ?? `HTTP ${res.status}`);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy("");
      e.target.value = "";
      refresh();
    }
  };

  const kind = state?.kind ?? "none";
  const upload = state?.upload;
  const labelText = state
    ? state.kind === "rtmp"
      ? "RTMP"
      : state.kind === "file"
      ? `File · ${state.label || "uploaded"}`
      : state.kind === "device"
      ? `Device · ${state.label}`
      : "No source"
    : "…";

  const showProcessing =
    upload?.state === "uploading" || upload?.state === "processing";

  const live = state?.streaming || upload?.state === "ready";

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-border bg-surface/60 px-4 py-3">
      <div className="flex items-center gap-2 rounded-full border border-border-strong bg-surface-elevated px-3 py-1">
        <span
          className={`inline-block h-1.5 w-1.5 rounded-full ${
            live ? "bg-accent shadow-glow-cyan" : "bg-fail"
          }`}
          aria-hidden
        />
        <span className="font-sans text-[10px] uppercase tracking-[0.3em] text-text-dim">
          Source
        </span>
        <span className="font-mono text-[12px] font-semibold text-text">{labelText}</span>
      </div>

      {upload?.state === "ready" && state?.kind === "file" && (
        <span className="rounded-full border border-border bg-surface-elevated px-3 py-1 font-mono text-[10px] uppercase tracking-widest text-text-muted">
          {upload.frame_count} frames · {upload.detection_count} detections
        </span>
      )}

      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          onClick={switchToRtmp}
          disabled={busy !== "" || kind === "rtmp"}
          className={`rounded-full px-4 py-1.5 font-sans text-[11px] font-semibold uppercase tracking-[0.25em] transition ${
            kind === "rtmp"
              ? "bg-accent/15 text-accent shadow-glow-cyan"
              : "border border-border-strong text-text hover:border-accent hover:text-accent"
          } ${busy !== "" ? "cursor-not-allowed opacity-50" : ""}`}
        >
          {busy === "rtmp" ? "Switching…" : "RTMP"}
        </button>

        <label
          className={`group flex cursor-pointer items-center gap-2 rounded-full px-4 py-1.5 font-sans text-[11px] font-semibold uppercase tracking-[0.25em] transition ${
            busy !== "" || showProcessing
              ? "cursor-not-allowed bg-cta/40 text-white/80"
              : "bg-cta text-white shadow-glow-blue hover:bg-cta-hover"
          }`}
        >
          {busy === "upload" || showProcessing ? "Uploading…" : "Upload video"}
          <input
            ref={fileRef}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={onFilePicked}
            disabled={busy !== "" || showProcessing}
          />
        </label>
      </div>

      {showProcessing && upload && (
        <div className="basis-full">
          <div className="flex items-baseline justify-between font-mono text-[10px] uppercase tracking-widest text-text-muted">
            <span>
              {upload.state === "uploading" ? "Uploading" : "Processing"} · {upload.name}
            </span>
            <span className="text-accent">{Math.round((upload.progress || 0) * 100)}%</span>
          </div>
          <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-border">
            <div
              className="h-full rounded-full bg-accent shadow-glow-cyan transition-[width]"
              style={{ width: `${Math.round((upload.progress || 0) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {(error || upload?.error) && (
        <div className="basis-full rounded-md border border-fail/60 bg-fail/10 px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest text-fail">
          ▲ {error || upload?.error}
        </div>
      )}
    </div>
  );
}
