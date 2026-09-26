#!/bin/bash -e

. ../../include/depinfo.sh
. ../../include/path.sh

build=_build$ndk_suffix

if [ "$1" == "build" ]; then
	true
elif [ "$1" == "clean" ]; then
	rm -rf _build$ndk_suffix
	exit 0
else
	exit 255
fi

unset CC CXX # meson wants these unset

apply_required_patch() {
	local patch="../../patches/mpv/$1"
	if git apply --reverse --check "$patch"; then
		return 0
	fi
	if git apply --check "$patch"; then
		git apply "$patch"
		return 0
	fi
	printf >&2 'Required mpv patch is incompatible: %s\n' "$patch"
	exit 1
}

apply_required_patch mpv_lavc_set_java_vm.patch
apply_required_patch mpv_fence_leak-fix.patch
apply_required_patch mpv_aimagereader_max_images3.patch
apply_required_patch mpv_android_mediacodec_opaque_one_frame.patch
apply_required_patch mpv_aimagereader_bounded_acquire_retry.patch
apply_required_patch mpv_gles_load_uniform4f.patch

sed -i -e "s/meson.build_options()/''/" meson.build

meson setup $build --prefix=/usr/local --cross-file "$prefix_dir"/crossfile.txt \
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

ninja -C $build -j$cores
DESTDIR="$prefix_dir" ninja -C $build install

ln -sf "$prefix_dir"/lib/libmpv.so "$native_dir"
