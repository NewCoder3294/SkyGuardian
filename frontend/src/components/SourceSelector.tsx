"use client";

import { useCallback, useEffect, useRef, useState } from "react";

function RtmpIcon({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden className={className}>
      <circle cx="8" cy="8" r="1.6" fill="currentColor" />
      <path
        d="M5.2 5.2a4 4 0 0 0 0 5.6M10.8 5.2a4 4 0 0 1 0 5.6M3.5 3.5a6.4 6.4 0 0 0 0 9M12.5 3.5a6.4 6.4 0 0 1 0 9"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
      />
    </svg>
  );
}

function UploadIcon({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden className={className}>
      <path
        d="M8 2.5v8M4.5 6L8 2.5 11.5 6M3 12v1.5h10V12"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CloseIcon({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden className={className}>
      <path
        d="M4 4l8 8M12 4l-8 8"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

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
  /** LAN-reachable publish URL the operator should paste into a remote
   *  publisher. Differs from rtmp_default when MediaMTX is on loopback. */
  publish_url?: string;
  upload?: UploadStatus;
}

interface Props {
  /** http origin of the backend (derived from the WS URL upstream). */
  apiBase: string;
  /** Notified whenever the polled source state changes. The parent uses this
   *  to swap between live VideoFeed and playback VideoPlayer. */
  onState?: (state: SourceState | null) => void;
}

function requestErrorMessage(err: unknown, apiBase: string): string {
  if (err instanceof TypeError) {
    return `Backend unavailable · start API at ${apiBase}`;
  }
  if (err instanceof Error) return err.message;
  return "Request failed";
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
        setError((current) =>
          current?.startsWith("Backend unavailable") ? null : current
        );
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
      } else {
        // Optimistically clear local state the instant the server acks the
        // swap. The 2 s polling cadence is long enough that a previously-
        // uploaded clip would otherwise stay on screen until the next tick —
        // which reads as "stuck video" to the operator. Notify the parent so
        // it can flip out of playback immediately; the next refresh confirms.
        const optimistic: SourceState = {
          kind: "rtmp",
          label: state?.rtmp_default ?? "",
          streaming: false,
          rtmp_default: state?.rtmp_default ?? "",
          publish_url: state?.publish_url,
          upload: {
            name: null,
            state: "idle",
            progress: 0,
            error: null,
            duration_s: 0,
            frame_count: 0,
            detection_count: 0,
          },
        };
        setState(optimistic);
        onState?.(optimistic);
      }
    } catch (e) {
      setError(requestErrorMessage(e, apiBase));
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
      setError(requestErrorMessage(err, apiBase));
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
    <div>
    <div className="flex items-center justify-end gap-2 py-1">
      <div className="flex items-center gap-2 border border-border bg-surface-elevated px-3 py-1.5">
        <span
          className={`inline-block h-1.5 w-1.5 ${
            live
              ? "rounded-full bg-text shadow-glow-cyan"
              : "border border-dashed border-text-dim bg-transparent"
          }`}
          aria-hidden
        />
        <span className="font-mono text-[10px] uppercase tracking-[0.3em] text-text-dim">
          SRC
        </span>
        <span className="font-mono text-[12px] font-semibold tracking-wide text-text">{labelText}</span>
      </div>

      {upload?.state === "ready" && state?.kind === "file" && (
        <span className="border border-border bg-surface-elevated px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest text-text-muted">
          {upload.frame_count} frames · {upload.detection_count} det
        </span>
      )}

      {/* Clear / discard the uploaded clip. Hits the same /video/source/rtmp
          reset the RTMP button uses — kept as a separate control so operators
          who just want "remove this file" don't have to deduce that toggling
          the source is what discards it. Shown for any file-loaded state
          (uploading, processing, ready, error). */}
      {state?.kind === "file" && (
        <button
          type="button"
          onClick={switchToRtmp}
          disabled={busy !== ""}
          title="Discard uploaded clip"
          className={`inline-flex items-center gap-1.5 border px-3 py-1.5 font-mono text-[10px] font-bold uppercase tracking-[0.18em] transition-colors duration-100 ${
            busy !== ""
              ? "cursor-not-allowed border-border-strong bg-surface-elevated text-text-muted opacity-60"
              : "border-fail/60 bg-fail/5 text-fail hover:bg-fail/10"
          }`}
        >
          <CloseIcon className="h-3 w-3" />
          Clear
        </button>
      )}

      <div className="flex items-stretch gap-0">
        {/* RTMP — segmented-control style. Pressed (armed) when active. */}
        <button
          type="button"
          onClick={switchToRtmp}
          disabled={busy !== "" || kind === "rtmp"}
          aria-pressed={kind === "rtmp"}
          className={`group -mr-px inline-flex items-center gap-2 border px-4 py-2 font-mono text-[12px] font-bold uppercase tracking-[0.18em] transition-colors duration-100 ${
            kind === "rtmp"
              ? "cursor-default border-accent/70 bg-accent/15 text-accent"
              : "border-border-strong bg-surface-elevated text-text-muted hover:border-accent/60 hover:text-accent"
          } ${busy !== "" ? "cursor-not-allowed opacity-60" : ""}`}
        >
          <RtmpIcon
            className={`h-3.5 w-3.5 ${
              kind === "rtmp" ? "text-accent" : "text-text-dim group-hover:text-accent"
            }`}
          />
          {busy === "rtmp" ? "Switching…" : "RTMP"}
        </button>

        {/* Upload — primary action. Tactical green fill, hard corners, press depress. */}
        <label
          className={`inline-flex select-none items-center gap-2 border px-5 py-2 font-mono text-[12px] font-bold uppercase tracking-[0.18em] transition-colors duration-100 ${
            busy !== "" || showProcessing
              ? "cursor-not-allowed border-cta-active bg-cta/50 text-text/70"
              : "cursor-pointer border-cta-hover bg-cta text-text hover:bg-cta-hover active:bg-cta-active"
          }`}
        >
          <UploadIcon className="h-3.5 w-3.5" />
          {busy === "upload" || showProcessing ? "Uploading…" : "Upload"}
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

      </div>

      {showProcessing && upload && (
        <div className="px-1 pb-1">
          <div className="flex items-baseline justify-between font-mono text-[10px] uppercase tracking-widest text-text-muted">
            <span>
              {upload.state === "uploading" ? "Uploading" : "Processing"} · {upload.name}
            </span>
            <span className="text-accent">{Math.round((upload.progress || 0) * 100)}%</span>
          </div>
          <div className="mt-1 h-1 w-full overflow-hidden bg-border">
            <div
              className="h-full bg-accent transition-[width]"
              style={{ width: `${Math.round((upload.progress || 0) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {(error || upload?.error) && (
        <div className="mx-1 mb-1 border border-fail/60 bg-fail/10 px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest text-fail">
          ▲ {error || upload?.error}
        </div>
      )}
    </div>
  );
}
