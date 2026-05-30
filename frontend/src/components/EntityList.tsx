"use client";

import type { Entity } from "@/lib/contracts";

const GLYPH: Record<Entity["type"], string> = {
  soldier: "●",
  drone: "▲",
  poi: "◇",
  hazard: "✕",
  object: "·",
};

export function EntityList({ entities }: { entities: Entity[] }) {
  const sorted = [...entities].sort((a, b) => a.type.localeCompare(b.type));
  return (
    <div className="h-full overflow-auto border-l border-border bg-surface">
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-surface px-3 py-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.3em] text-text-dim">
          Entities
        </span>
        <span className="font-mono text-[10px] tabular-nums text-text-muted">
          {entities.length.toString().padStart(2, "0")}
        </span>
      </div>
      {entities.length === 0 ? (
        <div className="px-3 py-8 text-center font-mono text-[10px] uppercase tracking-widest text-text-dim">
          No entities
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {sorted.map((e) => (
            <li key={e.id} className="px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-baseline gap-2 font-mono text-[11px] text-text">
                  <span className="text-base leading-none">{GLYPH[e.type]}</span>
                  <span className="uppercase tracking-wider">{e.label ?? e.id}</span>
                </span>
                <span
                  className={`font-mono text-[9px] uppercase tracking-widest ${
                    e.status === "active"
                      ? "text-text"
                      : e.status === "stale"
                      ? "text-text-muted"
                      : "text-text-dim"
                  }`}
                >
                  {e.status}
                </span>
              </div>
              <div className="mt-1 grid grid-cols-3 gap-2 font-mono text-[10px] tabular-nums text-text-dim">
                <span>x{format(e.position.x)}</span>
                <span>y{format(e.position.y)}</span>
                <span>z{format(e.position.z)}</span>
              </div>
              <div className="font-mono text-[9px] uppercase tracking-widest text-text-dim">
                {e.source} · {(e.confidence * 100).toFixed(0)}%
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function format(v: number): string {
  const s = v.toFixed(1);
  return v >= 0 ? `+${s}` : s;
}
