import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Builds into app/static, which the FastAPI server serves. The built files are committed so the
// Databricks App deploys without a Node build step.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../app/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://localhost:8000" } },
});
