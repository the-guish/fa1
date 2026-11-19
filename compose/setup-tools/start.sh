#!/bin/sh
# Starts one of the designer's two tool servers: `files` or `git`.
#
# The working copy is /work/setup, a clone of the setup folder. The app publishes the setup
# folder's HEAD as a bundle at /etc/fa1/setup/main.bundle, at each start and refresh. The git
# server brings the working copy's `main` to it as it starts. The designer's branches and its
# files not yet committed stay as they are.
set -eu

work=/work/setup
bundle=/etc/fa1/setup/main.bundle

# No program the working copy's own settings name runs here.
quiet() {
    git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c gc.auto=0 \
        -c maintenance.auto=false "$@"
}

sync_main() {
    if [ ! -f "$bundle" ]; then
        echo "no bundle at $bundle: the setup folder has no commit yet" >&2
        return 0
    fi
    if [ ! -d "$work/.git" ]; then
        quiet init --quiet --initial-branch main "$work"
    fi
    cd "$work"
    if ! quiet fetch --quiet --no-tags "$bundle" HEAD; then
        echo "the bundle at $bundle could not be fetched: main stays where it is" >&2
        return 0
    fi
    if ! git rev-parse --verify --quiet HEAD >/dev/null; then
        # A new working copy.
        quiet checkout --quiet -B main FETCH_HEAD
        return 0
    fi
    if [ "$(git symbolic-ref --quiet --short HEAD || true)" = main ]; then
        if quiet merge --quiet --ff-only FETCH_HEAD 2>/dev/null; then
            return 0
        fi
        # main holds commits or files of the designer's own. They move to a branch of their
        # own, as they are, and main follows the setup folder.
        kept="kept/$(date -u +%Y%m%d-%H%M%S)"
        quiet checkout --quiet -b "$kept"
        echo "main held changes of its own: they are on the branch $kept" >&2
    fi
    quiet branch --quiet --force main FETCH_HEAD
}

# supergateway logs each message at its default level. The designer's files stay out of the log.
case "${1:-}" in
files)
    echo "the working copy's files, on port 8938" >&2
    exec supergateway --stdio "mcp-server-filesystem /work" --logLevel none \
        --outputTransport streamableHttp --host 0.0.0.0 --port 8938 --stateful
    ;;
git)
    sync_main
    echo "the working copy's git, on port 8939" >&2
    exec supergateway --stdio "/opt/git-server/bin/mcp-server-git --repository $work" \
        --logLevel none --outputTransport streamableHttp --host 0.0.0.0 --port 8939 --stateful
    ;;
*)
    echo "usage: start.sh files|git" >&2
    exit 2
    ;;
esac
