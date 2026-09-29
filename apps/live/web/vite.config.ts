import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        app: resolve(__dirname, "index.html"),
        watch: resolve(__dirname, "watch.html"),
      },
    },
  },
});
