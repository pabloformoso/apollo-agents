import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "happy-dom",
    globals: false,
    setupFiles: ["./lib/__tests__/setup.ts"],
    exclude: ["**/node_modules/**", "**/dist/**", "e2e/**"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
      // §11.3 seam 2 — the pen module has ONE home, in the algorave spike, and
      // both the spike's page and this app import it from there.
      "@algorave/pen": path.resolve(
        __dirname,
        "../../scripts/algorave-spike/patterns/pen.js",
      ),
    },
  },
});
