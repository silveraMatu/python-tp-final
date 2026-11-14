import { defineConfig } from "vitest/config";

// Pruebas contra un backend real con datos de demostración (ver README).
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/integration/**/*.integration.test.ts"],
    testTimeout: 60_000,
    fileParallelism: false,
  },
});
