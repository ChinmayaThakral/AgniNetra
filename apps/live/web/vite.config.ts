import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  // Relative URLs, so the built app works under any path as well as at a domain root.
  base: "./",
  build: {
    rollupOptions: {
      input: {
        app: resolve(__dirname, "index.html"),
        watch: resolve(__dirname, "watch.html"),
        privacy: resolve(__dirname, "privacy.html"),
      },
    },
  },
});
