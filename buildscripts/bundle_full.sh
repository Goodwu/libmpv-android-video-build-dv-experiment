# --------------------------------------------------
set -e

if [ -d deps ]; then
  sudo rm -r deps
fi
if [ -d prefix ]; then
  sudo rm -r prefix
fi

./download.sh
./patch.sh

# --------------------------------------------------

rm -f scripts/ffmpeg.sh
cp flavors/full.sh scripts/ffmpeg.sh

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

cd temp

zip -r ../full-arm64-v8a.jar lib/arm64-v8a
zip -r ../full-armeabi-v7a.jar lib/armeabi-v7a
zip -r ../full-x86.jar lib/x86
zip -r ../full-x86_64.jar lib/x86_64

cd ../

pwd

md5sum *.jar