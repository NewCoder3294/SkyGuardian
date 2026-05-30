"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Operator chat surface over the local Ollama model. Posts to /intel/chat
 * with the running message history; the backend appends the current intel
 * summary as context so the LLM grounds its answers in THIS feed (not
 * generic world knowledge).
 *
 * Fully offline — no client-side network calls leave the laptop.
 */

interface Props {
  apiBase: string;
}

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
}

const SUGGESTIONS = [
  "What threats are visible right now?",
  "Summarise the last minute of activity.",
  "Are there any vehicles in frame?",
];

export function IntelChat({ apiBase }: Props) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  // Keep newest message in view.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, pending]);

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || pending) return;
    const nextHistory: ChatMsg[] = [...messages, { role: "user", content: trimmed }];
    setMessages(nextHistory);
    setInput("");
    setPending(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/intel/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: nextHistory }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as { reply: string; ok: boolean };
      setMessages([
        ...nextHistory,
        { role: "assistant", content: body.reply || "(no response)" },
      ]);
      if (!body.ok) setError("LLM responded with an error state.");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setPending(false);
    }
  };

  return (
    <section className="tac-corners border border-border bg-surface">
      <header className="flex items-center justify-between border-b border-border bg-surface-elevated px-5 py-3">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.35em] text-text-muted">
          Intel Chat
        </h2>
        <span className="font-mono text-[9px] uppercase tracking-[0.3em] text-text-dim">
          offline · gemma 3 · 4b
        </span>
      </header>

      <div
        ref={listRef}
        className="max-h-72 min-h-[10rem] space-y-2 overflow-y-auto px-5 py-4"
      >
        {messages.length === 0 && !pending && (
          <div className="space-y-3">
            <p className="font-mono text-[11px] uppercase tracking-widest text-text-dim">
              Ask the on-device model about the current feed. Try:
            </p>
            <ul className="space-y-1">
              {SUGGESTIONS.map((s) => (
                <li key={s}>
                  <button
                    type="button"
                    onClick={() => send(s)}
                    className="border border-border-strong bg-surface-elevated px-3 py-1 text-left font-mono text-[11px] text-text-muted transition hover:border-accent/60 hover:text-accent"
                  >
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {messages.map((m, i) => (
          <ChatBubble key={i} msg={m} />
        ))}

        {pending && (
          <div className="font-mono text-[11px] uppercase tracking-widest text-text-dim">
            ▌ thinking…
          </div>
        )}
        {error && (
          <div className="font-mono text-[11px] uppercase tracking-widest text-fail">
            {error}
          </div>
        )}
      </div>

      <form
        className="flex items-stretch gap-2 border-t border-border bg-surface-elevated px-3 py-3"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about the feed…"
          disabled={pending}
          className="flex-1 border border-border bg-surface px-3 py-2 font-mono text-[12px] text-text placeholder:text-text-dim focus:border-accent/60 focus:outline-none disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={pending || !input.trim()}
          className="border border-cta bg-cta px-4 py-2 font-mono text-[11px] uppercase tracking-[0.25em] text-bg transition hover:bg-cta-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </section>
  );
}

function ChatBubble({ msg }: { msg: ChatMsg }) {
  const isUser = msg.role === "user";
  return (
    <div
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[85%] border px-3 py-2 font-mono text-[12px] leading-snug ${
          isUser
            ? "border-cta/60 bg-cta/10 text-text"
            : "border-border-strong bg-surface-elevated text-text"
        }`}
      >
        <div className="mb-0.5 text-[9px] uppercase tracking-[0.3em] text-text-dim">
          {isUser ? "Operator" : "SkyGuardian"}
        </div>
        <div className="whitespace-pre-wrap">{msg.content}</div>
      </div>
    </div>
  );
}
