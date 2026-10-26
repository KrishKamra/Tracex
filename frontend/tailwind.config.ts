import type { Config } from "tailwindcss";

// Design tokens mirror tracex-workspace.html: colors are CSS variables holding
// space-separated RGB channels, so opacity modifiers (bg-mint/10) keep working.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        panel: token("panel"),
        card: token("card"),
        line: token("line"),
        ink: token("ink"),
        sub: token("sub"),
        muted: token("muted"),
        mint: token("mint"),
        trace: token("trace"),
        violet: token("violet"),
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Inter", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", '"JetBrains Mono"', "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
