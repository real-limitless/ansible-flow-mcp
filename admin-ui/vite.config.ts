import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const outDir = process.env.ADMIN_UI_OUTDIR
  ? resolve(process.env.ADMIN_UI_OUTDIR)
  : resolve(import.meta.dirname, "../src/ansible_flow_mcp/admin/static")

// Compiled into the Python package and served at /admin/.
export default defineConfig({
  base: "/admin/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/v1": "http://127.0.0.1:8789",
      "/health": "http://127.0.0.1:8789",
    },
  },
  build: {
    outDir,
    emptyOutDir: true,
    cssCodeSplit: false,
    assetsDir: "assets",
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: (assetInfo) => {
          const name = assetInfo.names?.[0] ?? ""
          if (name.endsWith(".css")) return "styles.css"
          return "assets/[name][extname]"
        },
      },
    },
  },
})
