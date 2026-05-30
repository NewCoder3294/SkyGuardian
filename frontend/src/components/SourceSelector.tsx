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

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface px-3 py-2">
      <span className="font-mono text-[9px] uppercase tracking-[0.3em] text-text-dim">
        Source
      </span>
      <span className="font-mono text-[11px] font-semibold text-text">
        {labelText}
      </span>
      <span
        className={`inline-block h-2 w-2 rounded-full ${
          state?.streaming || upload?.state === "ready" ? "bg-ok" : "bg-fail"
        }`}
        aria-hidden
      />

      {upload?.state === "ready" && state?.kind === "file" && (
        <span className="font-mono text-[10px] uppercase tracking-widest text-text-dim">
          · {upload.frame_count} frames · {upload.detection_count} detections
        </span>
      )}

      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          onClick={switchToRtmp}
          disabled={busy !== "" || kind === "rtmp"}
          className={`border px-3 py-1 font-mono text-[10px] uppercase tracking-[0.3em] transition ${
            kind === "rtmp"
              ? "border-text bg-text text-bg"
              : "border-border-strong text-text hover:border-text"
          } ${busy !== "" ? "cursor-not-allowed opacity-50" : ""}`}
        >
          {busy === "rtmp" ? "switching…" : "RTMP"}
        </button>

        <label
          className={`cursor-pointer border px-3 py-1 font-mono text-[10px] uppercase tracking-[0.3em] transition ${
            kind === "file"
              ? "border-text bg-text text-bg"
              : "border-border-strong text-text hover:border-text"
          } ${busy !== "" || showProcessing ? "cursor-not-allowed opacity-50" : ""}`}
        >
          {busy === "upload" ? "uploading…" : "Upload video"}
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
          <div className="flex items-baseline justify-between font-mono text-[10px] uppercase tracking-widest text-text-dim">
            <span>
              {upload.state === "uploading" ? "uploading" : "processing"} ·{" "}
              {upload.name}
            </span>
            <span>{Math.round((upload.progress || 0) * 100)}%</span>
          </div>
          <div className="mt-1 h-1 w-full overflow-hidden bg-border">
            <div
              className="h-full bg-text transition-[width]"
              style={{ width: `${Math.round((upload.progress || 0) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {(error || upload?.error) && (
        <div className="basis-full font-mono text-[10px] uppercase tracking-widest text-fail">
          ▲ {error || upload?.error}
        </div>
      )}
    </div>
  );
}
