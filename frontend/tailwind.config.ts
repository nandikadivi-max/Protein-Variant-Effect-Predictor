import type { Config } from "tailwindcss";

// Scientific & minimalistic direction: light neutral background,
// monospace for sequences/mutations, restrained accent palette.
// Change these tokens, not ad-hoc classes, if the direction evolves.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        surface: "#FAFAF9",
        "surface-raised": "#FFFFFF",
        border: "#E7E5E4",
        ink: "#1C1917",
        muted: "#78716C",
        damaging: "#B91C1C",
        tolerated: "#1D4ED8",
        neutral: "#57534E",
      },
    },
  },
  plugins: [],
};

export default config;
