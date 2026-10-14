import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  publicDir: mode === "public" ? "public-demo" : "public",
  server: { proxy: { "/api": "http://localhost:10000" } },
  preview: { proxy: { "/api": "http://localhost:10000" } },
}));
