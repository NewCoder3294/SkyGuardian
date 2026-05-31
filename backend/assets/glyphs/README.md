# Offline label glyphs (MapLibre glyph PBFs)

These are prebuilt MapLibre/Mapbox **glyph range PBFs** used to render basemap
labels fully offline. The SkyGuardian basemap style references the font stack
`Noto Sans Regular`, and the backend serves these files at runtime via:

```
GET /map/fonts/{fontstack}/{rng}.pbf
```

(implemented in `backend/app/server.py`; resolved under `backend/assets/glyphs/`
with path-traversal confinement). No network access is required at runtime —
consistent with the offline-first hard constraint.

## Font

- **Noto Sans** (Regular weight), by Google.
- License: **SIL Open Font License 1.1 (OFL)**. Noto fonts are redistributable
  under the OFL, which permits bundling the rasterized glyph PBFs here.

## Source of these PBFs

- Repository: [`openmaptiles/fonts`](https://github.com/openmaptiles/fonts)
- Release: **v2.0**, prebuilt asset **`noto-sans.zip`**
  (`https://github.com/openmaptiles/fonts/releases/download/v2.0/noto-sans.zip`)
- Only the `Noto Sans Regular/` directory was extracted. It contains the full
  set of **256 range files** (`0-255.pbf`, `256-511.pbf`, …, covering the
  Unicode BMP in 256-codepoint windows). Each file is a real protobuf
  (`glyphs.proto`) message, not an LFS pointer or HTML error page.

## How to regenerate

Use the openmaptiles fonts toolchain:

```bash
# Option A — grab the prebuilt release asset (what was used here)
curl -sL -o noto-sans.zip \
  https://github.com/openmaptiles/fonts/releases/download/v2.0/noto-sans.zip
unzip -o noto-sans.zip "Noto Sans Regular/*" -d /tmp/glyphs
cp -R "/tmp/glyphs/Noto Sans Regular" backend/assets/glyphs/

# Option B — build from source
git clone --depth 1 https://github.com/openmaptiles/fonts
cd fonts
npm ci
node ./generate.js
# output lands in ./fonts/<font stack>/ ; copy the "Noto Sans Regular" dir
```

Verify the files are genuine protobufs (non-empty, not HTML/LFS):

```bash
file "backend/assets/glyphs/Noto Sans Regular/0-255.pbf"   # -> data (binary)
wc -c  "backend/assets/glyphs/Noto Sans Regular/0-255.pbf" # -> > 100 bytes
```
