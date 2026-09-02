import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev proxies the API so the SPA and API share an origin (no CORS in dev, same as
// production where FastAPI serves the built dist/). Build emits static assets.
const API = process.env.MOSAERA_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    // Dev parity for the one directive that matters here. In production FastAPI serves dist/ and
    // sends the full policy (apps/api/mosaera_api/security_headers.py); in dev vite serves the
    // shell, so without this the PM chat would be exercised all day with the exfiltration leg
    // open. Only img-src: a full policy would need 'unsafe-inline' scripts and a ws: connect-src
    // for HMR, which would make the dev policy a misleading rehearsal of the real one.
    headers: { "Content-Security-Policy": "img-src 'self' data: blob:" },
    proxy: {
      "/api": { target: API, changeOrigin: true },
      "/healthz": { target: API, changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
  test: { environment: "jsdom", globals: true, setupFiles: "./src/test/setup.ts" },
});
