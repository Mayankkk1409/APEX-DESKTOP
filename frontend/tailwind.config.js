/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#07070a",
        panel: "#101014",
        line: "#2a2418",
        gold: "#c4a56a",
        champagne: "#cebf9c",
        bronze: "#a78d5d",
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
