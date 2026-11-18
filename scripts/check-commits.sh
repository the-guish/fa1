#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright The Robinauts Authors
#
# Copied from Robinauts' scripts/check-dco.sh and extended. Every commit of a
# branch follows AGENTS.md, "Commits and pull requests":
#
# - It is signed off by the person who put it there: its author, or whoever
#   committed someone else's work.
# - It mentions no AI. Its message, author and committer hold none of the
#   strings in $forbidden, in any case.
#
# Takes a commit range, and defaults to the commits this branch adds to main --
# never the whole history, part of which predates these rules.
#
#     scripts/check-commits.sh                     the commits of this branch
#     scripts/check-commits.sh <base>..<head>      the commits of a pull request
set -eu

# One fixed string per line, matched without regard to case.
forbidden='Co-Authored-By: Claude
@anthropic.com'

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"

range=${1:-}
asked_for=yes
if [ -z "$range" ]; then
    asked_for=no
    base=$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main)
    range="$base..HEAD"
fi

# Merge commits carry no contribution of their own; GitHub's own DCO check
# skips them too.
commits=$(git rev-list --no-merges "$range")
in_range=$(git rev-list --count "$range")

if [ "$in_range" -eq 0 ]; then
    if [ "$asked_for" = no ]; then
        # On main, or on a branch that has added nothing yet. There is
        # genuinely nothing to check, and nothing wrong with that.
        printf 'This branch adds no commit to main; nothing to check.\n'
        exit 0
    fi
    printf '%s contains no commits. There is nothing to check here, which is\n' "$range"
    printf 'not the same as a branch whose commits pass: check the range.\n'
    exit 1
fi

checked=0
failed=0
for commit in $commits; do
    checked=$((checked + 1))
    # Each git call is a command of its own: in a pipeline its failure would
    # be swallowed and read as a pass or a fail, for the wrong reason.
    author=$(git show -s --format='%an <%ae>' "$commit")
    committer=$(git show -s --format='%cn <%ce>' "$commit")
    subject=$(git show -s --format='%h %s' "$commit")
    message=$(git show -s --format='%B' "$commit")
    trailers=$(git show -s --format='%(trailers:key=Signed-off-by,valueonly,unfold)' "$commit")
    signed=$(printf '%s\n' "$trailers" | tr '[:upper:]' '[:lower:]')
    problems=''

    # The DCO is certified by whoever puts the commit here: its author, or the
    # person who took someone else's work over and committed it.
    matched=no
    for who in "$author" "$committer"; do
        wanted=$(printf '%s' "$who" | tr '[:upper:]' '[:lower:]')
        if printf '%s\n' "$signed" | grep -qxF "$wanted"; then
            matched=yes
            break
        fi
    done
    if [ "$matched" = no ]; then
        problem="no trailer \"Signed-off-by: $author\""
        if [ "$committer" != "$author" ]; then
            problem="$problem or \"Signed-off-by: $committer\""
        fi
        problems="$problems     $problem; commit with git commit -s
"
    fi

    # The author and the committer count: GitHub lists an author as a
    # contributor, whatever the message says.
    text=$(printf 'author %s\ncommitter %s\n%s\n' "$author" "$committer" "$message")
    hits=$(printf '%s\n' "$forbidden" | while IFS= read -r string; do
        printf '%s\n' "$text" | grep -iF -- "$string" || true
    done)
    if [ -n "$hits" ]; then
        problems="$problems     mentions an AI; move the attribution to the pull request description:
$(printf '%s\n' "$hits" | sort -u | sed 's/^/       /')
"
    fi

    if [ -n "$problems" ]; then
        failed=$((failed + 1))
        printf 'FAIL %s\n%s' "$subject" "$problems"
    fi
done

if [ "$failed" -ne 0 ]; then
    printf '\n%d of %d commit(s) in %s break the commit rules.\n' \
        "$failed" "$checked" "$range"
    exit 1
fi
if [ "$checked" -eq 0 ]; then
    printf '%s holds %d commit(s), all of them merges, and a merge adds\n' "$range" "$in_range"
    printf 'nothing of its own. Nothing to check.\n'
    exit 0
fi
printf 'All %d commit(s) in %s are signed off and mention no AI.\n' "$checked" "$range"
