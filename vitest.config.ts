import { defineConfig } from "vitest/config";

export default defineConfig({
  root: "src",
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./test/setup.ts"],
    include: ["test/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["../backend/**", "../src-tauri/**", "../dist/**"],
  },
});
