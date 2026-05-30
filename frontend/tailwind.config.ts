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
        // Hard tactical corners. Containers are square; only true LED dots
        // keep `full`. Nothing softer than a 2px tick anywhere else.
        none: "0",
        sm: "0px",
        DEFAULT: "1px",
        md: "1px",
        lg: "2px",
        full: "9999px",
      },
      boxShadow: {
        // Etched hairline rings, no neon bloom.
        "glow-cyan": "0 0 0 1px oklch(0.74 0.105 142 / 0.55)",
        "glow-blue": "0 0 0 1px oklch(0.77 0.125 82 / 0.5)",
        "card": "0 1px 0 oklch(0.46 0.03 138 / 0.25) inset, 0 6px 18px oklch(0.10 0.01 140 / 0.55)",
      },
    },
  },
  plugins: [],
};

export default config;
