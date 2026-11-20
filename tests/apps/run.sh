#!/bin/sh
# The checks of FA1's applications and its host of them, outside Docker (docs/specs/apps.md,
# "Tests"). They run against Robinauts at the commit compose/compose.yaml pins, as the image of
# `control` is built from it:
#
# 1. the interface: vendor.sh, `npm ci` from the lock, and the build with its type check;
# 2. the backend: test_reviews.py, on real git, in Robinauts' environment as the image installs
#    it, with pytest beside it.
#
#     tests/apps/run.sh                 fetches Robinauts at the pinned commit
#     tests/apps/run.sh <a checkout>    reads Robinauts from that checkout
#
# FA1_APPS_BACKEND_ONLY=1 leaves the interface out, on a computer without Node.js.
#
# Needs git, uv, and Node.js 24 with its npm. It writes apps/vendor, apps/node_modules and
# apps/dist, which git ignores.
set -eu

if [ "$#" -gt 1 ]; then
    printf 'usage: %s [a checkout of Robinauts]\n' "$0" >&2
    exit 2
fi

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
trap 'rm -rf "$work"; exit 130' INT
trap 'rm -rf "$work"; exit 143' TERM

if [ "$#" -eq 1 ]; then
    robinauts=$(CDPATH= cd -- "$1" && pwd)
else
    pinned=$(sed -n 's/^x-robinauts: &robinauts \(.*\)$/\1/p' "$root/compose/compose.yaml")
    url=${pinned%%#*}
    commit=${pinned#*#}
    if [ -z "$pinned" ] || [ "$url" = "$pinned" ] || [ -z "$commit" ]; then
        printf 'compose/compose.yaml pins no commit of Robinauts\n' >&2
        exit 1
    fi
    robinauts="$work/robinauts"
    git init --quiet "$robinauts"
    git -C "$robinauts" fetch --quiet --depth 1 "$url" "$commit"
    git -C "$robinauts" checkout --quiet --detach FETCH_HEAD
fi

# The interface, as the image's first two stages build it.
if [ -z "${FA1_APPS_BACKEND_ONLY:-}" ]; then
    sh "$root/apps/vendor.sh" "$robinauts"
    (cd "$root/apps" && npm ci --no-audit --no-fund && npm run build)
fi

# The backend, in the environment the image's last stage installs, with pytest beside it.
UV_PROJECT_ENVIRONMENT="$work/venv" PYTHONDONTWRITEBYTECODE=1 \
    uv run --quiet --project "$robinauts/backend" --locked --no-dev --with pytest \
    python -m pytest -q -p no:cacheprovider "$root/tests/apps"
