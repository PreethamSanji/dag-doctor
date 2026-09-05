import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dashboard talks to `triage serve`. Proxying in dev keeps the frontend
// origin-relative, so the built bundle works behind any host without config.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/metrics": "http://127.0.0.1:8000",
    },
  },
});
