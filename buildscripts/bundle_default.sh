#!/usr/bin/env bash
set -eo pipefail
export SHELLOPTS
cd "$(dirname "${BASH_SOURCE[0]}")"
ROOT="$PWD"
EVIDENCE="$ROOT/routing-native-evidence"
OUTPUT="$ROOT/routing-native-output"
# Never delete a user's build tree or reuse an old prefix/JAR as a new result.
for path in deps prefix temp routing-native-evidence routing-native-output; do
  if [ -e "$path" ] || [ -L "$path" ]; then
    printf >&2 'Fresh checkout required; refusing existing build path: %s\n' "$path"
    exit 2
  fi
done
if compgen -G 'default-*.jar' > /dev/null; then
  printf >&2 'Fresh checkout required; historical default JARs are present\n'
  exit 2
fi
git diff --exit-code
git diff --cached --exit-code
mkdir "$EVIDENCE"
trap 'rc=$?; printf "%s\n" "$rc" > "$EVIDENCE/exit-code.txt"' EXIT
git rev-parse HEAD > "$EVIDENCE/recipe-commit.txt"
git rev-parse 'HEAD^{tree}' > "$EVIDENCE/recipe-tree.txt"

python3 scripts/current_native_sources.py capture --output "$EVIDENCE/source-vector.json"
python3 scripts/current_native_sources.py exports --input "$EVIDENCE/source-vector.json" > "$EVIDENCE/source.env"
. "$EVIDENCE/source.env"
. include/depinfo.sh
NDK="$ROOT/sdk/android-sdk-linux/ndk/$v_ndk"
TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64"
# SDK setup belongs to the caller/CI, not a sed-rewritten recipe or global pip.
test -f "$NDK/source.properties"
grep -Fxq "Pkg.Revision = $v_ndk" "$NDK/source.properties"
test -x "$TOOLCHAIN/bin/llvm-readelf"
test -x "$TOOLCHAIN/bin/llvm-nm"
cp "$NDK/source.properties" "$EVIDENCE/ndk-source.properties"
"$TOOLCHAIN/bin/clang" --version > "$EVIDENCE/compiler-version.txt"
sha256sum "$TOOLCHAIN/bin/clang" "$NDK/source.properties" > "$EVIDENCE/toolchain-files.sha256"

bash -e -o pipefail include/download-deps.sh 2>&1 | tee "$EVIDENCE/download.log"
bash -e -o pipefail patch.sh 2>&1 | tee "$EVIDENCE/patch.log"
git ls-files -z -- patches | xargs -0 -r sha256sum > "$EVIDENCE/recipe-patches.sha256"
cp flavors/default.sh scripts/ffmpeg.sh
sha256sum flavors/default.sh scripts/ffmpeg.sh > "$EVIDENCE/ffmpeg-flavor.sha256"
python3 scripts/current_native_sources.py check --input "$EVIDENCE/source-vector.json" --deps deps --output "$EVIDENCE/source-before-build.json"
bash -e -o pipefail build.sh 2>&1 | tee "$EVIDENCE/native-build.log"

# Explicit, source-recorded helper NDK selection, rather than AGP's default NDK.
python3 - "$v_ndk" <<'PY'
from pathlib import Path
import re
import sys
version = sys.argv[1]
if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
    raise SystemExit('invalid selected NDK version')
path = Path('deps/media-kit-android-helper/app/build.gradle')
source = path.read_text()
if source.count('android {') != 1 or 'ndkVersion' in source or 'ndkPath' in source:
    raise SystemExit('helper Android DSL changed; explicit NDK binding needs review')
path.write_text(source.replace('android {', 'android {\n    ndkVersion "' + version + '"', 1))
cmake = Path('deps/media-kit-android-helper/app/src/main/cpp/CMakeLists.txt')
cmake_source = cmake.read_text()
# The member packaging gate requires exactly one GNU build-id note per ELF;
# upstream suppresses it (`--build-id=none`), so the driver-side override
# requests an explicit identity for the helper member as well.
if cmake_source.count('--build-id=none') != 1:
    raise SystemExit('helper CMake build-id suppression changed; override needs review')
cmake.write_text(cmake_source.replace('--build-id=none', '--build-id=sha1', 1))
PY
git -C deps/media-kit-android-helper diff --binary --no-ext-diff --no-textconv HEAD -- > "$EVIDENCE/helper-ndk-override.patch"
(
  cd deps/media-kit-android-helper
  bash -e -o pipefail gradlew --no-daemon assembleRelease
) 2>&1 | tee "$EVIDENCE/helper-build.log"

mkdir "$EVIDENCE/prepared"
# BEGIN VALIDATED VULKAN IMPORT GATE
# The packager validates the actual ELF inputs and tools for every ABI,
# mutates only a private copy, and emits exactly three members plus evidence.
for abi in arm64-v8a armeabi-v7a x86 x86_64; do
  case "$abi" in
    arm64-v8a) triple=aarch64-linux-android; suffix=-arm64 ;;
    armeabi-v7a) triple=arm-linux-androideabi; suffix= ;;
    x86) triple=i686-linux-android; suffix=-x86 ;;
    x86_64) triple=x86_64-linux-android; suffix=-x64 ;;
  esac
  mpv_path=$(realpath "prefix/$abi/usr/local/lib/libmpv.so") || exit "$?"
  python3 scripts/package_native.py \
    --mpv "$mpv_path" \
    --helper-apk deps/media-kit-android-helper/app/build/outputs/apk/release/app-release.apk \
    --libcxx "$TOOLCHAIN/sysroot/usr/lib/$triple/libc++_shared.so" \
    --output "$EVIDENCE/prepared/$abi" \
    --readelf "$TOOLCHAIN/bin/llvm-readelf" --nm "$TOOLCHAIN/bin/llvm-nm" --abi "$abi" || exit "$?"
done
# END VALIDATED VULKAN IMPORT GATE

# Preserve real link invocations and input hashes; these are not approval alone.
for suffix in -arm64 '' -x86 -x64; do
  build="deps/mpv/_build$suffix"
  ninja -C "$build" -t commands > "$EVIDENCE/mpv-link-commands${suffix:-armv7}.txt"
  cp "$build/.ninja_log" "$EVIDENCE/mpv-ninja-log${suffix:-armv7}.txt"
done
find prefix -type f -name '*.a' -print0 | sort -z | xargs -0 -r sha256sum > "$EVIDENCE/static-link-inputs.sha256"
python3 scripts/current_native_sources.py check --input "$EVIDENCE/source-vector.json" --deps deps --output "$EVIDENCE/source-after-build.json"
test "$(git rev-parse HEAD)" = "$(cat "$EVIDENCE/recipe-commit.txt")"
test ! -e "$OUTPUT"
mv "$EVIDENCE/prepared" "$OUTPUT"
printf '%s\n' 'PACKAGED_UNREVIEWED: source/ELF evidence is not CORE acceptance or device validation.'
