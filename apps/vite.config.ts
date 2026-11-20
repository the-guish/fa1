// FA1's interface is built as Robinauts builds its own: the control plane serves it under
// /ui/, so the page names its script and its stylesheet relatively.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  plugins: [react()],
});
