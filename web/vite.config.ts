import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// El proxy saca a CORS de la ecuación: el front pide siempre a rutas relativas
// (/api/...) y Vite reenvía al backend. También evita el problema de
// `credentials`, porque el backend responde Access-Control-Allow-Origin: *
// sin permitir credenciales.
const BACKEND = process.env.SONIA_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: BACKEND,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
        // El cierre con agentes tarda ~60 s y el relleno determinista suma más.
        // Sin esto, el proxy corta el stream a mitad de corrida.
        timeout: 0,
        proxyTimeout: 0,
      },
    },
  },
});
