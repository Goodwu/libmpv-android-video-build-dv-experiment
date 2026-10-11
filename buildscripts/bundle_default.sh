# --------------------------------------------------

if [ ! -f "deps" ]; then
  sudo rm -r deps
fi
if [ ! -f "prefix" ]; then
  sudo rm -r prefix
fi

./download.sh
./patch.sh

# --------------------------------------------------

if [ ! -f "scripts/ffmpeg" ]; then
  rm scripts/ffmpeg.sh
fi
cp flavors/default.sh scripts/ffmpeg.sh

# --------------------------------------------------

./build.sh

# --------------------------------------------------

cd deps/media-kit-android-helper

sudo chmod +x gradlew
./gradlew assembleRelease

unzip -o app/build/outputs/apk/release/app-release.apk -d app/build/outputs/apk/release

cp app/build/outputs/apk/release/lib/arm64-v8a/libmediakitandroidhelper.so      ../../prefix/arm64-v8a/usr/local/lib
cp app/build/outputs/apk/release/lib/armeabi-v7a/libmediakitandroidhelper.so    ../../prefix/armeabi-v7a/usr/local/lib
cp app/build/outputs/apk/release/lib/x86/libmediakitandroidhelper.so            ../../prefix/x86/usr/local/lib
cp app/build/outputs/apk/release/lib/x86_64/libmediakitandroidhelper.so         ../../prefix/x86_64/usr/local/lib

cd ../..

mkdir -p temp/lib/arm64-v8a
mkdir -p temp/lib/armeabi-v7a
mkdir -p temp/lib/x86
mkdir -p temp/lib/x86_64

cp prefix/arm64-v8a/usr/local/lib/*.so temp/lib/arm64-v8a/
cp prefix/armeabi-v7a/usr/local/lib/*.so temp/lib/armeabi-v7a/
cp prefix/x86/usr/local/lib/*.so temp/lib/x86/
cp prefix/x86_64/usr/local/lib/*.so temp/lib/x86_64/

# Weaken the Vulkan 1.1 imports libplacebo hard-requires, so the bundled
# libmpv.so also loads on Android API 24-27 (minSdk 24) where the system
# libvulkan.so only exports Vulkan 1.0. Contract: the app's Android playback
# topology never creates a Vulkan context; see
# scripts/weaken_undefined_imports.py. Opt out only for a vulkan-VO debug
# build, and raise the effective minSdk to API 28+ there.
if [ "${PILIPLUSX_SKIP_VULKAN_WEAKEN:-0}" != "1" ]; then
  for abi in arm64-v8a armeabi-v7a x86 x86_64; do
    python3 scripts/weaken_undefined_imports.py "temp/lib/$abi/libmpv.so"
  done
fi

cd temp

FIXED_TIME="2025-01-01 00:00:00"

find "lib" -type d -exec touch -d "$FIXED_TIME" {} +
find "lib/arm64-v8a" -type f -name "*.so" -exec touch -d "$FIXED_TIME" {} +
find "lib/armeabi-v7a" -type f -name "*.so" -exec touch -d "$FIXED_TIME" {} +
find "lib/x86" -type f -name "*.so" -exec touch -d "$FIXED_TIME" {} +
find "lib/x86_64" -type f -name "*.so" -exec touch -d "$FIXED_TIME" {} +

md5sum lib/arm64-v8a/*.so
md5sum lib/armeabi-v7a/*.so
md5sum lib/x86/*.so
md5sum lib/x86_64/*.so

find lib/arm64-v8a -type f | sort | zip -r -X ../default-arm64-v8a.jar -@
find lib/armeabi-v7a -type f | sort | zip -r -X ../default-armeabi-v7a.jar -@
find lib/x86 -type f | sort | zip -r -X ../default-x86.jar -@
find lib/x86_64 -type f | sort | zip -r -X ../default-x86_64.jar -@

cd ../

pwd

md5sum *.jar