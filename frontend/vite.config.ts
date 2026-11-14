/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// CSP para el hosting (se aplica en `vite preview`; en producción replicarla en el servidor web,
// ver README). En desarrollo no se aplica porque Vite necesita scripts en línea para el HMR.
function contentSecurityPolicy(apiUrl: string): string {
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' blob:",
    "frame-src 'self' blob:",
    "object-src 'self' blob:",
    `connect-src 'self' ${apiUrl}`,
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiUrl = env.VITE_API_URL || "http://localhost:8000";
  return {
    plugins: [react()],
    server: { port: 5173 },
    preview: {
      port: 5173,
      headers: {
        "Content-Security-Policy": contentSecurityPolicy(apiUrl),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test-setup.ts"],
      css: false,
      exclude: ["node_modules", "dist", "**/*.integration.test.ts"],
    },
  };
});
