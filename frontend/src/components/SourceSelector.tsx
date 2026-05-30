"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface SourceState {
  kind: "rtmp" | "file" | "device" | "none";
  label: string;
  streaming: boolean;
  rtmp_default: string;
}

interface Props {
  /** http origin of the backend (derived from the WS URL upstream). */
  apiBase: string;
}

/**
 * Toolbar that lets the operator pick the leader video source — live RTMP or
 * a pre-recorded clip uploaded from the local machine. Both paths run through
 * the exact same perception pipeline (YOLO + depth + SLAM); the source swap
 * is server-side via SwitchableSource so neither perception nor the dashboard
 * needs to know which one is feeding pixels.
 */
export function SourceSelector({ apiBase }: Props) {
  const [state, setState] = useState<SourceState | null>(null);
  const [busy, setBusy] = useState<"" | "rtmp" | "upload">("");
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/video/source`, { cache: "no-store" });
      if (res.ok) setState(await res.json());
    } catch {
      // Ignore; we'll retry on the interval.
    }
  }, [apiBase]);

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, 2000);
    return () => window.clearInterval(t);
  }, [refresh]);

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
  const labelText = state
    ? state.kind === "rtmp"
      ? "RTMP"
      : state.kind === "file"
      ? `File · ${state.label || "uploaded"}`
      : state.kind === "device"
      ? `Device · ${state.label}`
      : "No source"
    : "…";

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
          state?.streaming ? "bg-ok" : "bg-fail"
        }`}
        aria-hidden
      />

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
          } ${busy !== "" ? "cursor-not-allowed opacity-50" : ""}`}
        >
          {busy === "upload" ? "uploading…" : "Upload video"}
          <input
            ref={fileRef}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={onFilePicked}
            disabled={busy !== ""}
          />
        </label>
      </div>

      {error && (
        <div className="basis-full font-mono text-[10px] uppercase tracking-widest text-fail">
          ▲ {error}
        </div>
      )}
    </div>
  );
}
