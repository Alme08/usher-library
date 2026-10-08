import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite configuration for the Usher Library frontend.
// The development server is exposed on port 5173 of the host so the
// provisional page is reachable from the browser (RF-10). The port
// matches the `FRONTEND_PORT` documented in the project README.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
  },
});
