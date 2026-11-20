// FA1's interface: oneberth's shell with Robinauts' two applications and FA1's own
// (docs/specs/apps.md). This file is the rail's list of applications, in order. backend.py is
// the backend's.
import { applyRememberedTheme, Shell, type ShellApp } from "@oneberth/ui";
import { neorcWithForms, robinautsApp } from "@robinauts/ui";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// The page's base before any application's stylesheet, as Robinauts' own page loads it.
import "@robinauts/ui/styles.css";
import { Fallback } from "./Fallback";
import { reviews } from "./reviews";

const apps: readonly ShellApp[] = [robinautsApp(), neorcWithForms(), reviews];

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html has no #root to mount on");
}

// Before the first paint, so a browser set to dark by hand shows no light frame first.
applyRememberedTheme();
createRoot(root).render(
  <StrictMode>
    <Fallback>
      <Shell apps={apps} title="FA1" />
    </Fallback>
  </StrictMode>,
);
