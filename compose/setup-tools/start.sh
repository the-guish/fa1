#!/bin/sh
# Starts one of the designer's two tool servers: `files` or `git`.
#
# The working copy is /work/setup, a clone of the person's setup folder, which is mounted
# read-only at /setup. The git server brings the working copy's `main` to the folder's commit
# as it starts, and again each time that commit changes. The designer's branch, its commits and
# its files not yet committed stay as they are.
set -eu

# The tests set both.
work=${FA1_SETUP_WORK:-/work/setup}
setup=${FA1_SETUP_FOLDER:-/setup}

# No program the working copy's own settings name runs here.
quiet() {
    git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c gc.auto=0 \
        -c maintenance.auto=false "$@"
}

# The commit the setup folder is at, "" for none.
setup_head() {
    quiet -C "$setup" rev-parse --verify --quiet 'HEAD^{commit}' 2>/dev/null || true
}

# The setup folder's commit that main last followed. Its history is the person's, and a commit
# of main outside it and outside the folder's new commit is the designer's.
followed=refs/fa1/followed

# Brings main to the setup folder's commit. Commits the designer left on main move to a branch
# `kept/<time>`, and the designer's checked-out branch stays checked out. Fails, and changes
# nothing, while files not yet committed on main are in the way.
sync_main() {
    if [ -z "$(setup_head)" ]; then
        echo "the setup folder at $setup has no commit yet" >&2
        return 1
    fi
    if [ ! -d "$work/.git" ]; then
        quiet init --quiet --initial-branch main "$work" || return 1
    fi
    cd "$work" || return 1
    if ! quiet fetch --quiet --no-tags "$setup" HEAD; then
        echo "the setup folder at $setup could not be fetched: main stays where it is" >&2
        return 1
    fi
    target=$(git rev-parse --verify --quiet 'FETCH_HEAD^{commit}') || return 1
    old=$(git rev-parse --verify --quiet 'refs/heads/main^{commit}' || true)
    own=""
    if [ -n "$old" ]; then
        known=$(git rev-parse --verify --quiet "$followed^{commit}" || true)
        own=$(git rev-list -n 1 "$old" --not "$target" $known) || return 1
    fi
    current=$(git symbolic-ref --quiet --short HEAD || true)
    if [ "$current" = main ] || ! git rev-parse --verify --quiet HEAD >/dev/null; then
        # Files not yet committed come along when they do not conflict with the new commit.
        if ! quiet checkout --quiet -B main "$target"; then
            echo "main could not follow the setup folder: files not yet committed are in the way" >&2
            return 1
        fi
    else
        quiet branch --quiet --force main "$target" || return 1
    fi
    if [ -n "$own" ]; then
        kept="kept/$(date -u +%Y%m%d-%H%M%S)"
        quiet branch --quiet "$kept" "$old" || return 1
        echo "main held commits of its own: they are on the branch $kept" >&2
    fi
    quiet update-ref "$followed" "$target"
}

# Follows the setup folder while the server runs: an approval, the person's own commit, or a
# history the person rewrote moves main to the folder's commit, as at the start. A sync that
# fails tries again every 30 seconds.
follow_main() {
    wait=0
    while sleep 2; do
        now=$(setup_head)
        synced=$(git -C "$work" rev-parse --verify --quiet "$followed" 2>/dev/null || true)
        if [ -z "$now" ] || [ "$now" = "$synced" ]; then
            continue
        fi
        if [ "$wait" -gt 0 ]; then
            wait=$((wait - 1))
            continue
        fi
        (sync_main) || wait=14
    done
}

# supergateway logs each message at its default level. The designer's files stay out of the log.
case "${1:-}" in
files)
    echo "the working copy's files, on port 8938" >&2
    exec supergateway --stdio "mcp-server-filesystem /work" --logLevel none \
        --outputTransport streamableHttp --host 0.0.0.0 --port 8938 --stateful
    ;;
git)
    (sync_main) || true
    follow_main &
    echo "the working copy's git, on port 8939" >&2
    exec supergateway --stdio "/opt/git-server/bin/python -I /usr/local/lib/fa1-git-server.py --repository $work" \
        --logLevel none --outputTransport streamableHttp --host 0.0.0.0 --port 8939 --stateful
    ;;
sync)
    # Brings main to the setup folder's commit once.
    sync_main
    ;;
*)
    echo "usage: start.sh files|git|sync" >&2
    exit 2
    ;;
esac
