#!/bin/bash -e

. ../../include/depinfo.sh
. ../../include/path.sh

build=_build$ndk_suffix

if [ "$1" == "build" ]; then
	true
elif [ "$1" == "clean" ]; then
	rm -rf $build
	exit 0
else
	exit 255
fi

unset CC CXX

external_yuv_patch=../../patches/libplacebo/libplacebo_external_yuv_sampler.patch
if git apply --reverse --check "$external_yuv_patch"; then
	true
elif git apply --check "$external_yuv_patch"; then
	git apply "$external_yuv_patch"
else
	printf >&2 'Required libplacebo patch is incompatible: %s\n' "$external_yuv_patch"
	exit 1
fi

meson setup $build --prefix=/usr/local --cross-file "$prefix_dir"/crossfile.txt \
	-Dvulkan=enabled -Ddemos=false -Dshaderc=enabled -Dlcms=enabled

ninja -C $build -j$cores
DESTDIR="$prefix_dir" ninja -C $build install

# add missing library for static linking
# this isn't "-lstdc++" due to a meson bug: https://github.com/mesonbuild/meson/issues/11300
${SED:-sed} '/^Libs:/ s|$| -lc++|' "$prefix_dir/lib/pkgconfig/libplacebo.pc" -i
