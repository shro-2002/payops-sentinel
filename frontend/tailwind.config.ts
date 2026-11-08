import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#070b14", 900: "#0b1220", 850: "#0f1729", 800: "#131d33", 700: "#1c2944", 600: "#2a3a5c" },
        line: "#22314f",
        fg: { DEFAULT: "#e6ecf5", muted: "#9fb0c8", faint: "#7487a3" },
        accent: { DEFAULT: "#38bdf8", strong: "#0ea5e9" },
        ok: "#34d399",
        warn: "#fbbf24",
        bad: "#f87171",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
