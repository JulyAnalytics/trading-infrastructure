import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API calls to the FastAPI service on :8100 so the app
// works without CORS config in the browser during development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8100",
      "/health": "http://127.0.0.1:8100",
    },
  },
});
