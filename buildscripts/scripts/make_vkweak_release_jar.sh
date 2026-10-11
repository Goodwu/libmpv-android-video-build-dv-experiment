#!/usr/bin/env bash
# Derive a "vkweak" arm64 JAR from an existing release JAR without a rebuild:
# identical bytes except the two Vulkan 1.1 imports in libmpv.so are weakened
# so the .so also loads on Android API 24-27 (see
# weaken_undefined_imports.py for the contract).
#
# usage: make_vkweak_release_jar.sh <input.jar> <output.jar>
set -euo pipefail

cd "$( dirname "${BASH_SOURCE[0]}" )"

if (( $# != 2 )); then
  echo "usage: $0 <input.jar> <output.jar>" >&2
  exit 64
fi

in_jar=$(readlink -f "$1")
# readlink -f on macOS fails for a not-yet-existing output path; use as given.
out_jar="$2"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir "$work/jar" "$work/newlib"

(cd "$work/jar" && unzip -q "$in_jar")

python3 weaken_undefined_imports.py \
  "$work/jar/lib/arm64-v8a/libmpv.so" "$work/newlib/libmpv.so"

cmp -l "$work/jar/lib/arm64-v8a/libmpv.so" "$work/newlib/libmpv.so" | wc -l

cp "$work/newlib/libmpv.so" "$work/jar/lib/arm64-v8a/libmpv.so"

# Start from the source JAR verbatim, then replace only the patched member,
# restoring the original member timestamp so the derivative JAR differs from
# its input solely in the patched libmpv.so bytes.
orig_ts=$(python3 - "$in_jar" <<'EOF'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    y, m, d, H, M, S = z.getinfo("lib/arm64-v8a/libmpv.so").date_time
    print(f"{y:04d}{m:02d}{d:02d}{H:02d}{M:02d}.{S:02d}")
EOF
)
cp "$in_jar" "$out_jar"
touch -t "$orig_ts" "$work/jar/lib/arm64-v8a/libmpv.so"
(cd "$work/jar" && zip -q -X "$out_jar" lib/arm64-v8a/libmpv.so)

python3 - "$in_jar" "$out_jar" <<'EOF'
import sys, zipfile

base_mpv = mpv = None
for path in sys.argv[1:]:
    with zipfile.ZipFile(path) as z:
        names = sorted(i.filename for i in z.infolist())
        infos = {i.filename: (i.date_time, i.file_size) for i in z.infolist()}
        data = z.read("lib/arm64-v8a/libmpv.so")
    if path == sys.argv[1]:
        base_names, base_infos, base_mpv = names, infos, data
    else:
        out_names, out_infos, mpv = names, infos, data
assert base_names == out_names, (base_names, out_names)
for n in base_names:
    assert base_infos[n] == out_infos[n], (n, base_infos[n], out_infos[n])
diff = sum(1 for a, b in zip(base_mpv, mpv) if a != b)
assert diff <= 4, diff
print(f"OK: {len(base_names)} entries, timestamps preserved, libmpv.so byte diff = {diff}")
EOF

shasum -a 256 "$out_jar"
