import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#07111b",
        panel: "#0d1c2b",
        panelAlt: "#13273b",
        electric: "#6ee7ff",
        accent: "#f97316",
        success: "#34d399",
        warning: "#fb7185",
        ink: "#dbeafe",
        muted: "#89a3ba",
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(110, 231, 255, 0.08), 0 24px 60px rgba(3, 15, 26, 0.55)",
      },
      fontFamily: {
        display: ["'Space Grotesk'", "sans-serif"],
        body: ["'IBM Plex Sans'", "sans-serif"],
      },
      backgroundImage: {
        grid: "radial-gradient(circle at 1px 1px, rgba(110,231,255,0.08) 1px, transparent 0)",
      },
    },
  },
  plugins: [],
} satisfies Config;

