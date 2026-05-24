import type { Config } from "tailwindcss";
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#000000",
        panel: "#0a0a0a",
        panelAlt: "#111111",
        electric: "#ffffff",
        accent: "#ffffff",
        success: "#ffffff",
        warning: "#ff4444",
        ink: "#ffffff",
        muted: "rgba(255,255,255,0.45)",
      },
      fontFamily: {
        display: ["'Roboto Mono'", "monospace"],
        body: ["'Roboto Mono'", "monospace"],
        mono: ["'Roboto Mono'", "monospace"],
      },
      backgroundImage: {
        grid: "radial-gradient(circle at 1px 1px, rgba(255,255,255,0.04) 1px, transparent 0)",
      },
    },
  },
  plugins: [],
} satisfies Config;
