#!/bin/sh
# The end-to-end journey (test_journey.py), on Linux: builds the app, starts Xvfb and
# tauri-driver, and runs pytest against them, with the app's folder in a new temporary
# directory. Needs Docker with Compose and Buildx, Xvfb, WebKitWebDriver (webkit2gtk-driver),
# tauri-driver (cargo install tauri-driver --locked), and Python with pytest and selenium.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cargo build --manifest-path "$root/app/Cargo.toml"

work=$(mktemp -d)
FA1_HOME="$work/fa1"
export FA1_HOME
# The webviews keep their storage under XDG_DATA_HOME, apart from FA1_HOME.
XDG_DATA_HOME="$work/data"
export XDG_DATA_HOME

Xvfb :91 -screen 0 1400x1000x24 >"$work/xvfb.log" 2>&1 &
xvfb=$!
DISPLAY=:91
export DISPLAY
# GTK prefers Wayland when the session has it. The app and its webviews go to Xvfb alone.
unset WAYLAND_DISPLAY
GDK_BACKEND=x11
export GDK_BACKEND
tauri-driver >"$work/tauri-driver.log" 2>&1 &
driver=$!
trap 'kill $driver $xvfb 2>/dev/null; rm -rf "$work"' EXIT INT TERM
sleep 2

python3 -m pytest -x -q "$root/tests/e2e" "$@"
