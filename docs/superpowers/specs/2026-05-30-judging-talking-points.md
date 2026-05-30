# SkyGuardian — Judge-Facing Talking Points

**Date:** 2026-05-30 · **Track:** Autonomous Navigation

Purpose: turn every known gap into an owned, honest answer. Defense judges probe; the winning posture is "we know exactly what this does and doesn't do, and why." Lead with what's real; never overclaim.

---

## Lead with the strengths (what we actually shipped)

- **Fully offline situational-awareness loop:** manned Mavic feed → on-device YOLO detection + monocular SLAM → live local-frame world model → web dashboard + phone, with zero cloud calls at runtime. No internet, no GPS.
- **Genuine autonomy on the companion drone:** a closed-loop **autonomous approach-and-standoff** behavior (Tello flies to a detected target and holds a safe radius) plus AprilTag **follow-me**, both arbitrated by a **software arming interlock** so only one controller commands the drone at a time. Convergence is proven in a deterministic simulation.
- **On-device LLM voice control:** push-to-talk, on-device speech recognition (hard-gated to never use cloud STT), transcript resolved by an on-device Gemma model with a deterministic keyword fallback so voice never fails.
- **On-demand vision reasoning:** the operator can trigger a real image-aware Gemma assessment of the current frame.
- **Safety-first engineering:** arming interlock is fail-closed and disarmed-by-default; STOP commands a land, RECALL flies home; the voice intent parser uses phrase-boundary matching so incidental speech can't actuate the drone; track/approach require on-screen confirmation.

---

## The gaps, and how to answer them

### Map metric accuracy (#2) — "How accurate is the positioning?"
**Reality:** Scale comes from a single AprilTag anchor plus a relative monocular-VO frame (no loop closure); detection range uses a depth heuristic / ground-plane assumption. Absolute positions are approximate.
**Owned answer:** "It's a *relative* local frame, anchored by a known-size AprilTag, designed to run fully offline at ~5 FPS on a laptop with no GPS. We optimized for 'where is it, roughly, relative to the launch point and to me' — which is what a dismounted operator actually needs — not survey-grade coordinates. The anchor gives metric scale near the landmark; accuracy degrades with distance and we surface that rather than pretending otherwise." The UI labels positions as approximate.

### Vision reasoning default (#3) — "Is the LLM actually looking at the image?"
**Reality:** The live intel card runs **text-only** by default (reasoning over the YOLO label list) because a per-frame vision pass is ~2 min on an M-series CPU; the threat level is keyword-heuristic with the LLM able to override.
**Owned answer:** "Per-frame vision is too slow to be live, so the continuous card reasons over the detection list in real time. When the operator wants the model to *actually look*, there's an on-demand 'deep look' (`POST /intel/deep-look`) that runs a real image-aware Gemma pass on the current frame. So it's an explicit, deliberate two-tier design: fast label-based situational awareness continuously, true vision on demand." (We can show a captured deep-look assessment.)

### Autonomy scope (#5) — "What's actually autonomous?"
**Reality:** The Mavic is human-piloted (video-in only — no Mavic flight code, and we don't claim any). Flight autonomy lives on the Tello: AprilTag follow-me and the new autonomous approach-and-standoff.
**Owned answer:** "Two layers of autonomy. First, **autonomous perception**: detection, mapping, and the world model run with zero human input. Second, **autonomous flight on the companion drone**: it follows the soldier via AprilTag, and on command autonomously navigates to a detected target and holds standoff — closed-loop visual servoing with a fail-closed safety interlock, geofenced standoff, and abort-on-loss. The Mavic stays human-piloted by design; we don't claim autonomous flight we don't have." Live target detection on the Tello frame is the next hardware-integration step; the control loop is validated in sim.

### Voice control (#6) — "Is that a real LLM or keyword matching?"
**Reality:** On-device speech recognition produces the transcript; an on-device Gemma function-caller (Cactus) resolves it, with a deterministic keyword matcher as fallback.
**Owned answer:** "Both, by design. The on-device LLM does the function-calling, and a deterministic keyword matcher backs it so a recognized command always executes even if the model is unsure — you do not want a flying drone's safety commands gated on a probabilistic model. STOP/land/abort resolve deterministically; richer phrasing goes through the LLM."

### Networking (#7) — "What about the dual-radio setup?"
**Reality:** The laptop being simultaneously on the Tello AP and reachable by the phone is operationally fragile; documented fallback is "everyone on the Tello AP."
**Owned answer:** "We have a recorded end-to-end run from the exact demo setup as insurance, and a documented single-network fallback. The architecture binds the map server to 0.0.0.0 and both clients subscribe to the same world model, so it degrades gracefully to one network."

---

## Hard rules for the room
- Never claim metre-accurate positioning, autonomous Mavic flight, always-on vision, or pure-LLM voice. Each is a notch above what ships — own the notch.
- If asked something we can't confirm from the current feed/build, say so. Honesty about limits reads as competence to a defense judge.
