#!/bin/sh
# Puts Robinauts' interface and its two peers in vendor/, as node packages, from a checkout of
# Robinauts at the pinned commit (docs/specs/apps.md, "The interface"). The image's build runs
# it. A developer runs it before `npm ci`:
#
#     apps/vendor.sh <a checkout of Robinauts>
#
# Robinauts' own script packs the three, and this one unpacks each into its folder. Needs git,
# Node.js and npm.
set -eu

if [ "$#" -ne 1 ]; then
    printf 'usage: %s <a checkout of Robinauts>\n' "$0" >&2
    exit 2
fi

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
packed=$(mktemp -d)
trap 'rm -rf "$packed"' EXIT

"$1/scripts/robinauts-ui-pack.sh" "$packed" >/dev/null
rm -rf "$here/vendor"
for name in robinauts-ui neorc-ui oneberth-ui; do
    mkdir -p "$here/vendor/$name"
    tar -xzf "$packed/$name-0.0.0.tgz" -C "$here/vendor/$name" --strip-components 1
done
