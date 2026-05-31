"""On-device tactical reasoning via Ollama-hosted vision LLM.

The user's prior hackathon used Gemini Live for situational reasoning. This
module is the offline equivalent: we point at a local Ollama server and run a
small multimodal model (default Gemma 3 4B with vision) on the latest video
frame + current YOLO detections, getting back a short tactical assessment
the operator can act on.

All inference is local — Ollama defaults to 127.0.0.1:11434, model weights
live in ~/.ollama/models. No cloud calls at runtime.
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx


@dataclass
class IntelSummary:
    """One inference result + everything the dashboard needs to render it."""

    text: str                                   # the model's assessment
    threat_level: str = "unknown"               # "low" | "med" | "high" | "unknown"
    labels_seen: list[str] = field(default_factory=list)  # the YOLO labels we sent
    t: float = 0.0                              # unix seconds, when produced
    model: str = ""
    latency_ms: float = 0.0


# Threat-level keyword heuristics. Cheap, deterministic; the model's own
# "threat_level" field is what we actually trust when present.
_HIGH_KW = (
    "weapon", "armed", "gun", "rifle", "knife", "bomb", "ied",
    "grenade", "explosive", "engage", "hostile",
)
_MED_KW = ("approach", "suspicious", "unknown payload", "perimeter", "vehicle")


def _heuristic_threat_level(text: str, labels: list[str]) -> str:
    blob = (text + " " + " ".join(labels)).lower()
    if any(k in blob for k in _HIGH_KW):
        return "high"
    if any(k in blob for k in _MED_KW):
        return "med"
    return "low"


def _build_prompt(labels: list[str], with_vision: bool) -> str:
    """The actual reasoning prompt. Concise + structured output so the
    dashboard can format it cleanly."""
    label_line = (
        f"Detected objects in this frame: {', '.join(sorted(set(labels)))}."
        if labels
        else "No objects detected by the perception system in this frame."
    )
    look_phrase = "Look at the image and consider those detections — " if with_vision else ""
    return (
        "You are a tactical reconnaissance AI assistant for a drone recon "
        "operator. "
        f"{label_line} {look_phrase}"
        "Give the operator a SHORT situational assessment (one sentence, "
        "under 25 words). Be specific about what's happening and any "
        "immediate threats. Then on the next line output exactly "
        "'LEVEL: low' or 'LEVEL: med' or 'LEVEL: high' to summarise the "
        "threat level."
    )


class IntelReasoner:
    """Async client around the Ollama generate API. One reasoner per process;
    call summarise() with the latest JPEG + detection labels. Cheap to
    construct, expensive per call (~1–4 s on M-series for Gemma 3 4B).
    """

    def __init__(
        self,
        model: str = "gemma3:4b",
        base_url: str = "http://localhost:11434",
        # Vision-encoder pass through Gemma 3 4B is ~2 min on M3 CPU/Metal;
        # text-only inference over the YOLO label list is ~2–5 s. Default to
        # text-only so the dashboard card refreshes at a sane rate. Operators
        # can set INTEL_VISION=1 to enable the slower image-aware path.
        with_vision: bool = False,
        request_timeout_s: float = 180.0,
    ) -> None:
        self._model = model
        self._url = base_url.rstrip("/") + "/api/generate"
        self._timeout = request_timeout_s
        self._with_vision = with_vision

    async def summarise(
        self, jpeg_bytes: Optional[bytes], labels: list[str]
    ) -> IntelSummary:
        """Run one inference. In text-only mode jpeg_bytes is ignored and may
        be None — the reasoner just looks at the YOLO label list. Raises
        httpx.HTTPError on connection/timeout — the caller decides whether
        to retry or surface as error state."""
        prompt = _build_prompt(labels, self._with_vision)
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                # Keep output short and deterministic for the dashboard card.
                "temperature": 0.2,
                "num_predict": 96,
            },
        }
        if self._with_vision and jpeg_bytes:
            payload["images"] = [base64.b64encode(jpeg_bytes).decode("ascii")]
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            res = await client.post(self._url, json=payload)
            res.raise_for_status()
            body = res.json()
        elapsed_ms = (time.monotonic() - t0) * 1000.0

        text = (body.get("response") or "").strip()
        # The prompt asks for "LEVEL: x" on the last line — extract if present.
        threat_level = _heuristic_threat_level(text, labels)
        for line in reversed(text.splitlines()):
            ll = line.strip().lower()
            if ll.startswith("level:"):
                lvl = ll.split(":", 1)[1].strip()
                if lvl in ("low", "med", "high"):
                    threat_level = lvl
                # Strip the explicit LEVEL line from the user-facing text.
                text = text.replace(line, "").strip()
                break

        return IntelSummary(
            text=text or "No assessment.",
            threat_level=threat_level,
            labels_seen=sorted(set(labels)),
            t=time.time(),
            model=self._model,
            latency_ms=elapsed_ms,
        )


_CHAT_SYSTEM = (
    "You are SkyGuardian's offline tactical reconnaissance assistant. "
    "You answer questions from a drone operator using ONLY the situational "
    "context provided in the user message (latest YOLO detections, recent "
    "intel summary, threat level). If the answer isn't in the provided "
    "context, say you cannot confirm from the current feed. Keep responses "
    "to 1–3 sentences, plain English, no markdown."
)


class IntelChat:
    """Lightweight chat wrapper around Ollama's /api/chat. Reuses the same
    local model the periodic summariser uses, so there is no extra model
    download and inference latency matches the summary card (~1–3 s)."""

    def __init__(
        self,
        model: str = "gemma3:4b",
        base_url: str = "http://localhost:11434",
        request_timeout_s: float = 60.0,
    ) -> None:
        self._model = model
        self._url = base_url.rstrip("/") + "/api/chat"
        self._timeout = request_timeout_s

    async def reply(
        self,
        history: list[dict],
        context: str,
    ) -> str:
        """Send `history` (list of {role, content}) plus a synthesised
        `context` block to the model and return the assistant's reply text."""
        # Prepend the system prompt + the current intel context as the first
        # user message so the model always sees the situational ground truth.
        messages: list[dict] = [{"role": "system", "content": _CHAT_SYSTEM}]
        if context.strip():
            messages.append(
                {"role": "system", "content": f"CURRENT INTEL CONTEXT:\n{context.strip()}"}
            )
        for m in history:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        if not any(m.get("role") == "user" for m in messages):
            return "Ask me anything about what the drone is seeing."

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 180},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            res = await client.post(self._url, json=payload)
            res.raise_for_status()
            body = res.json()
        msg = body.get("message") or {}
        return (msg.get("content") or "").strip() or "(no response)"


async def ollama_alive(base_url: str = "http://localhost:11434") -> bool:
    """Best-effort liveness probe for the local Ollama server."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(base_url.rstrip("/") + "/api/tags")
            return res.status_code == 200
    except Exception:
        return False
