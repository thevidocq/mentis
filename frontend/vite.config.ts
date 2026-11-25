import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API runs on 127.0.0.1:8000; in production nginx proxies /api.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  preview: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
