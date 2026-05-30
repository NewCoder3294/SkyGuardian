# `reasoning/` — On-device tactical reasoning (offline "Gemini Live")

The OFFLINE equivalent of the prior hackathon's Gemini Live: a small multimodal
LLM, served by a **local** Ollama instance, that periodically assesses the
latest Mavic frame + YOLO detections and answers operator questions. No cloud,
no internet — Ollama runs on the brain itself. See
[`../../../CLAUDE.md`](../../../CLAUDE.md).

This package is pure inference glue: it owns no hardware, no world-model state,
and no sockets. It is wired into [`../server.py`](../server.py), which owns the
loop, the cached summary, and the HTTP endpoints (see "How `server.py` wires it"
below).

## Responsibility
- Turn `(latest JPEG, current YOLO labels)` into a short tactical assessment +
  a threat level the dashboard can render.
- Answer operator chat questions grounded in that same situational context.
- Degrade cleanly when the local Ollama server is down — every entry point is
  best-effort and the server keeps running without it.

## Dependency: local Ollama (fully offline)
All inference goes to a local Ollama HTTP server (default
`http://localhost:11434`, i.e. `127.0.0.1:11434`). Model weights live under
`~/.ollama/models`. Nothing in this package reaches the network beyond
`localhost`. If Ollama is unreachable, reasoning is simply disabled — no
crashes, no fallback to a cloud API. Only dependency is `httpx`.

## Modules

### `intel.py`
Everything in the package lives here.

#### `IntelSummary` (dataclass)
One inference result plus the render metadata the dashboard needs:
`text` (the assessment), `threat_level` (`"low"` | `"med"` | `"high"` |
`"unknown"`), `labels_seen` (the YOLO labels that were sent), `t` (unix
seconds), `model`, `latency_ms`.

#### `IntelReasoner` — the periodic summariser
Async client over Ollama's `/api/generate`. One reasoner per process; cheap to
construct, expensive per call.

```
IntelReasoner(model="gemma3:4b", base_url="http://localhost:11434",
              with_vision=False, request_timeout_s=180.0)
```

- `await summarise(jpeg_bytes, labels) -> IntelSummary` runs one inference.
  - In text-only mode (default) `jpeg_bytes` is ignored and may be `None` — the
    model reasons over the YOLO label list alone. Fast (~2–5 s on Apple Silicon
    for Gemma 3 4B).
  - With `with_vision=True` and a non-`None` `jpeg`, the frame is base64-encoded
    into the request `images` so the model sees the picture. Roughly **30×
    slower** (~2 min through the Gemma 3 4B vision encoder on M-series), which is
    why vision is off by default.
- Output is constrained for the dashboard card: `temperature 0.2`,
  `num_predict 96`, `stream: false`. The prompt asks for one sentence (<25 words)
  followed by an explicit `LEVEL: low|med|high` line.
- `threat_level` is taken from that `LEVEL:` line when the model emits it;
  otherwise it falls back to a cheap deterministic keyword heuristic
  (`_heuristic_threat_level`) over the assessment text + labels (high-severity
  weapon/hostile terms → `high`, approach/perimeter/vehicle terms → `med`, else
  `low`). The explicit `LEVEL:` line is stripped from the user-facing `text`.
- Raises `httpx.HTTPError` on connection/timeout; the caller decides whether to
  retry or surface error state.

#### `IntelChat` — operator Q&A
Lightweight wrapper over Ollama's `/api/chat`, reusing the same local model as
the summariser (no extra download, latency matches the card).

```
IntelChat(model="gemma3:4b", base_url="http://localhost:11434",
          request_timeout_s=60.0)
```

- `await reply(history, context) -> str`. `history` is a list of
  `{role, content}` (`user`/`assistant`); `context` is a synthesised situational
  block (latest summary, threat level, recently observed labels).
- A fixed system prompt (`_CHAT_SYSTEM`) constrains the model to answer **only**
  from the provided context — if the answer isn't in the feed it says it cannot
  confirm. The `context` block is injected as a leading system message so the
  model always sees ground truth before the conversation.
- `temperature 0.3`, `num_predict 180`, `stream: false`. Returns a friendly
  prompt if no user turn is present.

#### `ollama_alive(base_url="http://localhost:11434") -> bool`
Best-effort async liveness probe — `GET /api/tags` with a 2 s timeout, returns
`False` on any exception. The server polls this before each inference tick.

## How `server.py` wires it
[`../server.py`](../server.py) owns all stateful integration:

- **Config (env):**
  - `INTEL_MODEL` — Ollama model tag, default `gemma3:4b`. Set to `off` to
    disable reasoning entirely even when Ollama is up (`_INTEL_ENABLED` is
    `False`, so neither the loop, the reasoner, nor the chat client are created).
  - `INTEL_VISION` — `1` enables the slower image-aware path; default `0`
    (text-only).
  - `INTEL_INTERVAL_S` — loop cadence in seconds, default `5`.
- **Construction:** a single `IntelReasoner` and `IntelChat` are built at import
  time (both `None` when disabled), alongside an `_intel_state` dict
  (`available` = Ollama reachable, `running` = inference in flight, `last_error`)
  and a cached `_intel_summary`.
- **Loop (`_intel_loop`):** scheduled as an asyncio task from the startup hook
  when enabled (cancelled on shutdown alongside the broadcast task). Each tick it
  probes `ollama_alive`, skips if Ollama is down or an inference is already
  running, pulls the latest boxes from perception (`perception.latest_boxes()`,
  runs even when the box list is empty so the operator sees "area clear"), reads
  the Mavic JPEG only in vision mode, then calls `summarise(...)` and caches the
  result. Errors are recorded in `_intel_state["last_error"]`, never raised out
  of the loop.
- **Endpoints:**
  - `GET /intel/summary` — the latest cached `IntelSummary` plus
    `available` / `running` / `last_error` / `model`.
  - `POST /intel/chat` — operator chatbot. Body is `{messages: [{role, content}]}`
    (max 20, each 1–4000 chars). Builds the context block from the latest summary
    + observed labels and calls `IntelChat.reply`. Returns
    `{reply, ok, model}` (or `ok: false` with a message when reasoning is
    disabled or the local LLM is offline).

The frontend renders these via `IntelSummaryCard` and `IntelChat`
(see [`../../../frontend/src/components/`](../../../frontend/src/components/)).

## Notes
- Fully local: the only outbound calls are to `localhost:11434`. Bring Ollama up
  with the configured model pulled (`ollama pull gemma3:4b`) before expecting
  intel; otherwise `available` stays `false` and the dashboard shows reasoning as
  offline.
- Vision mode is a deliberate, expensive opt-in — don't enable `INTEL_VISION` if
  the dashboard card needs to refresh at the default cadence.
- No live-LLM tests in [`../../tests/`](../../tests/); correctness here depends on
  the Ollama HTTP contract.
