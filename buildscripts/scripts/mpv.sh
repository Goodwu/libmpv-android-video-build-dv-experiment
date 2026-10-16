#!/usr/bin/env bash
set -eo pipefail

. ../../include/depinfo.sh
. ../../include/path.sh

build=_build$ndk_suffix

if [ "$1" == "build" ]; then
	true
elif [ "$1" == "clean" ]; then
	rm -rf "_build$ndk_suffix"
	exit 0
else
	exit 255
fi

unset CC CXX # meson wants these unset

sed -i -e "s/meson.build_options()/''/" meson.build

meson setup "$build" --prefix=/usr/local --cross-file "$prefix_dir"/crossfile.txt \
	--strip \
	--prefer-static \
	--default-library shared \
	-Dgpl=false \
	-Dlibmpv=true \
	-Dbuild-date=false \
	-Dlua=disabled \
	-Dcplayer=false \
	-Diconv=disabled \
	-Dvulkan=enabled \
	-Dmanpage-build=disabled

# Preserve the actual compiler/linker commands in the producer log.
ninja -v -C "$build" -j"$cores"
DESTDIR="$prefix_dir" ninja -v -C "$build" install

ln -sf "$prefix_dir"/lib/libmpv.so "$native_dir"
