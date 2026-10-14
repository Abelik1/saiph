// SPDX-License-Identifier: AGPL-3.0-or-later
import { defineConfig } from "vitest/config"
import react from "@vitejs/plugin-react"
import { fileURLToPath } from "node:url"

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"], globals: true, exclude: ["e2e/**", "node_modules/**"] },
})
