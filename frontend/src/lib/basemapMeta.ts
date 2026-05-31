export interface BasemapMeta {
  staged: boolean;
  bytes: number;
  minzoom: number;
  maxzoom: number;
  bbox: number[];
  origin: { lat?: number; lng?: number };
  build_url: string;
  created_at: number;
}

export async function fetchBasemapMeta(apiBase: string): Promise<BasemapMeta> {
  try {
    const r = await fetch(`${apiBase}/map/basemap/meta`, { cache: "no-store" });
    if (!r.ok) return emptyMeta();
    return (await r.json()) as BasemapMeta;
  } catch {
    return emptyMeta();
  }
}

function emptyMeta(): BasemapMeta {
  return {
    staged: false,
    bytes: 0,
    minzoom: 0,
    maxzoom: 0,
    bbox: [],
    origin: {},
    build_url: "",
    created_at: 0,
  };
}
