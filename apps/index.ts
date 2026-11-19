// FA1's applications on the rail of the App tab, below Robinauts and neorc, in this order
// (docs/specs/apps.md). Robinauts' build reads this file in the place of its own
// frontend/src/extra/index.ts.
import type { ShellApp } from "@oneberth/ui";

import { reviews } from "./reviews/ui";

export const EXTRA_APPS: readonly ShellApp[] = [reviews];
