#!/bin/bash -e

PATCHES=(patches/*)
ROOT=$(pwd)

for dep_path in "${PATCHES[@]}"; do
    if [ -d "$dep_path" ]; then
        mapfile -t patches < <(git ls-files -- "$dep_path/*")
        [ "${#patches[@]}" -eq 0 ] && continue
        dep=$(echo $dep_path |cut -d/ -f 2)
        cd deps/$dep
        echo Patching $dep
        for patch in "${patches[@]}"; do
            echo Applying $patch
            if git apply --reverse --check "$ROOT/$patch"; then
                echo Already applied: $patch
            elif git apply --check "$ROOT/$patch"; then
                git apply "$ROOT/$patch"
            else
                printf >&2 'Required patch is incompatible: %s\n' "$patch"
                exit 1
            fi
        done
        cd $ROOT
    fi
done

exit 0
