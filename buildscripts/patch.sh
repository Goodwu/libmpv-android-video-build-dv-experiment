#!/usr/bin/env bash
set -eo pipefail
PATCHES=(patches/*)
ROOT=$(pwd)
for dep_path in "${PATCHES[@]}"; do
    if [ -d "$dep_path" ]; then
        # Capture git's exit independently; process substitution can hide it.
        patch_list=$(git ls-files -- "$dep_path/*")
        [ -z "$patch_list" ] && continue
        mapfile -t patches <<< "$patch_list"
        dep=${dep_path#patches/}
        cd "deps/$dep"
        echo "Patching $dep"
        for patch in "${patches[@]}"; do
            echo "Applying $patch"
            if git apply --reverse --check "$ROOT/$patch"; then
                echo "Already applied: $patch"
            elif git apply --check "$ROOT/$patch"; then
                git apply "$ROOT/$patch"
            else
                printf >&2 'Required patch is incompatible: %s\n' "$patch"
                exit 1
            fi
        done
        cd "$ROOT"
    fi
done
