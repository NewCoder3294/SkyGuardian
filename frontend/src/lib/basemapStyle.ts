import type { StyleSpecification } from "maplibre-gl";

const PAPER = "#f1f1f0";
const INK = "#202020";
const INK_2 = "#5a5a5a";
const LINE = "#cfcfcf";
const WATER = "#e3e3e1";
const BUILDING = "#dcdcda";

/** Monochrome Protomaps-schema basemap. All URLs are local (offline). */
export function buildBasemapStyle(apiBase: string): StyleSpecification {
  return {
    version: 8,
    glyphs: `${apiBase}/map/fonts/{fontstack}/{range}.pbf`,
    sources: {
      basemap: {
        type: "vector",
        url: `pmtiles://${apiBase}/map/basemap.pmtiles`,
        attribution: "© OpenStreetMap",
      },
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": PAPER } },
      { id: "earth", type: "fill", source: "basemap", "source-layer": "earth", paint: { "fill-color": PAPER } },
      { id: "landuse", type: "fill", source: "basemap", "source-layer": "landuse", paint: { "fill-color": "#ececeb", "fill-opacity": 0.6 } },
      { id: "water", type: "fill", source: "basemap", "source-layer": "water", paint: { "fill-color": WATER } },
      { id: "buildings", type: "fill", source: "basemap", "source-layer": "buildings", paint: { "fill-color": BUILDING, "fill-outline-color": LINE } },
      { id: "roads-casing", type: "line", source: "basemap", "source-layer": "roads", paint: { "line-color": LINE, "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1, 16, 6] } },
      { id: "roads", type: "line", source: "basemap", "source-layer": "roads", paint: { "line-color": INK_2, "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.4, 16, 3] } },
      { id: "boundaries", type: "line", source: "basemap", "source-layer": "boundaries", paint: { "line-color": INK_2, "line-dasharray": [2, 2], "line-width": 0.7 } },
      {
        id: "places", type: "symbol", source: "basemap", "source-layer": "places",
        layout: { "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"], "text-size": 11, "text-letter-spacing": 0.08, "text-transform": "uppercase" },
        paint: { "text-color": INK, "text-halo-color": PAPER, "text-halo-width": 1.2 },
      },
      {
        id: "road-labels", type: "symbol", source: "basemap", "source-layer": "roads",
        layout: { "symbol-placement": "line", "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"], "text-size": 10 },
        paint: { "text-color": INK_2, "text-halo-color": PAPER, "text-halo-width": 1 },
      },
    ],
  };
}
