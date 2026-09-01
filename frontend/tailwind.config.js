/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "var(--color-ink)",
        panel: "var(--color-panel)",
        line: "var(--color-line)",
        gold: "var(--color-gold)",
        champagne: "var(--color-text)",
        bronze: "var(--color-bronze)",
        faint: "var(--color-faint)",
        subtle: "var(--color-subtle)",
        muted: "var(--color-muted)",
        surface: "var(--apex-surface)",
        "chart-bg": "var(--apex-chart-bg)",
        "chart-panel": "var(--apex-chart-panel)",
        bull: "var(--apex-bull)",
        bear: "var(--apex-bear)",
      },
      fontFamily: {
        display: ["Newsreader", "Georgia", "serif"],
        sans: ["IBM Plex Sans", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        glow: "0 0 40px rgba(196, 165, 106, 0.18)",
      },
    },
  },
  plugins: [],
};
