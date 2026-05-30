import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Dark tactical HUD palette
        bg: "var(--bg)",
        surface: "var(--surface)",
        "surface-elevated": "var(--surface-elevated)",
        border: "var(--border)",
        "border-strong": "var(--border-strong)",
        text: "var(--text)",
        "text-muted": "var(--text-muted)",
        "text-dim": "var(--text-dim)",
        invert: "var(--invert)",
        ok: "var(--ok)",
        warn: "var(--warn)",
        fail: "var(--fail)",
        accent: "var(--accent)",
        "accent-dim": "var(--accent-dim)",
        cta: "var(--cta)",
        "cta-hover": "var(--cta-hover)",
        "cta-active": "var(--cta-active)",
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
      borderRadius: {
        none: "0",
        sm: "4px",
        DEFAULT: "6px",
        md: "8px",
        lg: "12px",
        full: "9999px",
      },
      boxShadow: {
        "glow-cyan": "0 0 0 1px rgba(34,211,238,0.35), 0 0 24px rgba(34,211,238,0.12)",
        "glow-blue": "0 0 0 1px rgba(59,130,246,0.4), 0 0 24px rgba(59,130,246,0.18)",
        "card": "0 4px 14px rgba(0,0,0,0.45), 0 1px 0 rgba(255,255,255,0.03) inset",
      },
    },
  },
  plugins: [],
};

export default config;
