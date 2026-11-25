import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import pkg from "./package.json";

// In development the API runs on 127.0.0.1:8000; in production nginx proxies /api.
export default defineConfig({
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  preview: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
