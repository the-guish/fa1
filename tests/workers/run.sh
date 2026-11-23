#!/bin/sh
# The checks of FA1's Cursor worker (docs/specs/cursor-worker.md, "Tests"). They run against
# Robinauts at the commit compose/compose.yaml pins, as the worker's image is built from it:
#
# 1. outside Docker: the worker's pure functions, and its engine on a stand-in for Cursor's CLI
#    (stand_in/cursor-agent), in Robinauts' environment with the worker beside it;
# 2. with Docker: the worker's image is built, and a server holds a conversation with the
#    worker in its container, on the same stand-in.
#
#     tests/workers/run.sh                 fetches Robinauts at the pinned commit
#     tests/workers/run.sh <a checkout>    reads Robinauts from that checkout
#
# FA1_WORKERS_NO_DOCKER=1 leaves the second part out. Needs git and uv, and Docker with Buildx
# for the second part. No test reaches Cursor.
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

if [ -z "${FA1_WORKERS_NO_DOCKER:-}" ]; then
    FA1_CURSOR_WORKER_IMAGE=test-fa1-cursor-worker
    export FA1_CURSOR_WORKER_IMAGE
    docker build --quiet --build-context "robinauts=$robinauts" \
        --tag "$FA1_CURSOR_WORKER_IMAGE" "$root/workers/cursor" >/dev/null
fi

# Robinauts' environment as its own image installs it, with what its extra workers share and
# FA1's worker beside it, and pytest.
UV_PROJECT_ENVIRONMENT="$work/venv" PYTHONDONTWRITEBYTECODE=1 \
    uv run --quiet --project "$robinauts/backend" --locked --no-dev --with pytest \
    --with-editable "$root/workers/cursor" \
    env PYTHONPATH="$robinauts/extra-workers/worker-common/src" \
    python -m pytest -q -p no:cacheprovider "$root/tests/workers"
