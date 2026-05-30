# docs — Design & Subsystem Docs

Index of the design and per-subsystem docs for SkyGuardian. The root
[`README.md`](../README.md) (status + repo layout + run) and
[`CLAUDE.md`](../CLAUDE.md) (the spec + hard constraints) are the **source of
truth**; the files here go deep on one subsystem each.

## Subsystem docs

| Doc | Covers | State |
|---|---|---|
| [`SLAM.md`](./SLAM.md) | GPS-less monocular mapping — Mavic feed → metric local map via VO + AprilTag scale anchor; swappable `MonocularVO` / `ORBSLAM3Runner` backends; honest limitations | ✅ built, tested |
| [`VIDEO.md`](./VIDEO.md) | Laptop video relay — `/video/{tello,mavic}` MJPEG re-stream; env-selected sources (`tello` / `url:` / `mock` / disabled), real by default | ✅ built, tested |
| [`VOICE.md`](./VOICE.md) | On-device voice + vision (Gemma 3n via Cactus) — mic → transcript → closed intent vocab, live-frame Q&A; `cactus.xcframework` embedded (build 4), needs the model download | 🟡 framework embedded |
| [`MOBILE.md`](./MOBILE.md) | iOS app build / TestFlight / device test — XcodeGen + ASC API ship lane, and the single-network Tello-feed walkthrough | ✅ built, tested |

## Specs

- [`superpowers/specs/2026-05-29-recon-companion-design.md`](./superpowers/specs/2026-05-29-recon-companion-design.md)
  — approved design: the recon + soldier-companion pivot, clean-reimplement reuse
  strategy, six-subsystem decomposition around the spine, contracts, and sequencing.

## See also

- [`../mobile/README.md`](../mobile/README.md) — iOS app source/layout.
- Hard constraints (offline-first · no GPS · recon only, no engagement · single
  plain Tello in AP mode) live in [`../CLAUDE.md`](../CLAUDE.md).
