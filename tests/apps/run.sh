#!/bin/sh
# The review app's tests (test_reviews.py), without Docker: a setup folder, its bundle, a
# working copy and the review app's repository on real git, with Robinauts' and neorc's own
# checks. Needs git, uv, and a checkout of Robinauts at the commit compose/compose.yaml pins:
#
#     tests/apps/run.sh <a checkout of Robinauts>
set -eu

if [ "$#" -lt 1 ]; then
    printf 'usage: %s <a checkout of Robinauts> [pytest arguments]\n' "$0" >&2
    exit 2
fi

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
checkout=$1
shift
exec uv run --project "$checkout/backend" --locked --no-dev --with pytest \
    python -m pytest -q "$root/tests/apps" "$@"
