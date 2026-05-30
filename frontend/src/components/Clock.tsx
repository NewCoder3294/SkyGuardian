"use client";

import { useEffect, useState } from "react";

/** Monospaced HH:MM:SS that ticks each second. Renders blank during SSR to
 *  avoid hydration mismatch with the client clock. */
export function Clock() {
  const [now, setNow] = useState<string>("");

  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const hh = d.getHours().toString().padStart(2, "0");
      const mm = d.getMinutes().toString().padStart(2, "0");
      const ss = d.getSeconds().toString().padStart(2, "0");
      setNow(`${hh}:${mm}:${ss}`);
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <span className="font-mono text-sm tabular-nums tracking-widest text-accent">
      {now || "--:--:--"}
    </span>
  );
}
