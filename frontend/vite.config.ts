// SPDX-License-Identifier: AGPL-3.0-or-later
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
export default defineConfig({
  base: "./",
  build: { rolldownOptions: { input: { main: fileURLToPath(new URL("./index.html", import.meta.url)), screen: fileURLToPath(new URL("./screen.html", import.meta.url)) } } },
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
});
