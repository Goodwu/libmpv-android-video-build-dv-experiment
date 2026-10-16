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

# The external YUV sampler / r32f format support is integrated upstream on
# optimize/dovi-linear-decode since the branch rewrite (980742df, ea700489);
# the old tree-wide patch was archived in patches-archived/ (DV001). The two
# still-needed fixes (fix_gles_shader_compile_error, fix_shaderc_vulkan_dismatch)
# are applied by patch.sh from patches/libplacebo/.

meson setup $build --prefix=/usr/local --cross-file "$prefix_dir"/crossfile.txt \
	-Dvulkan=enabled -Ddemos=false -Dshaderc=enabled -Dlcms=enabled

ninja -C $build -j$cores
DESTDIR="$prefix_dir" ninja -C $build install

# add missing library for static linking
# this isn't "-lstdc++" due to a meson bug: https://github.com/mesonbuild/meson/issues/11300
${SED:-sed} '/^Libs:/ s|$| -lc++|' "$prefix_dir/lib/pkgconfig/libplacebo.pc" -i
