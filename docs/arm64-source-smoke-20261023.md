# Android arm64 source and SDK verification — 2026-10-23

An isolated Linux build compiled the selected native sources for Android
`arm64-v8a`, API 26. It started from producer
`dd2db5faeac32838a71f689ae09d684dec0d9b18` and then applied the Vulkan metadata
adapter and SDK collector changes delivered with this report. Existing Linux
native build outputs were not reused.

## Inputs

| Input | Identity |
| --- | --- |
| FFmpeg | `9aba43cfbee182ade060cdccbe15340a0fbe3e83` |
| libplacebo | `ea700489fbf27703d8c1f64874a1c6138f17ad28` |
| mpv | `e0dc99d0467957ffc16c4afbb4e9f7c3f2a8667d` |
| Android NDK | `27.2.12479018` / r27c, Linux |
| Meson | `1.6.1` |
| Target | `aarch64-unknown-linux-android26` |

The NDK archive was fetched from Google's Android repository. Its size
(`663987688` bytes) and SHA-1
(`090e8083a715fdb1a3e402d0763c388abb03fb4e`) matched the official
`repository2-1.xml` entry before extraction. The separately computed archive
SHA-256 was
`59c2f6dc96743b5daf5d1626684640b20a6bd2b1d85b13156b90333741bad5cc`.

The existing downloader, source-vector checks and patch driver were used.
Both pre-build and post-build locked-source checks passed. The source build
selected only `build.sh --arch arm64`; it did not run the other three full ABI
builds.

## Problems reproduced and resolved

1. Meson 1.6's system Vulkan detector tries to execute target code to discover
   the header version. Cross compilation therefore reported an unknown version
   and rejected mpv's `>= 1.3.238` requirement. The new adapter reads the real
   compiler's macros and compiles/links a validation program before writing
   `vulkan.pc`. The selected NDK reports **1.3.275**. All four ABI compiler/loader
   probes passed. A 1.3.237 header fixture and a missing loader-symbol fixture
   were rejected without producing pkg-config metadata.
2. Installed FFmpeg pkg-config files retained build-prefix `-L` paths, while
   mpv recorded absolute NDK library paths. The collector now rebases installed
   SDK directories through its documented pkg-config sysroot contract and
   proves each NDK library replacement with that ABI compiler's lookup. Libtool
   `.la` files are excluded from the supported SDK interface.
3. dav1d's existing LTO build produces LLVM bitcode archive members. The
   collector now uses the same NDK's `llvm-dis` to compare their original target
   triples with the compiler target, preserving the LTO build and ABI gate.

## Observed results

The linked `libmpv.so` is a 21,812,992-byte AArch64 ELF shared object with SONAME
`libmpv.so`, build ID `ae994dd1ad52300707bd14ed81da5b8b3b46cb0c`, and SHA-256
`03f64951363d6f6984ed509a7ae434d3cdebf1ff575efbc08314e19558412661`.
All four load segments have `0x4000` alignment. The production Vulkan-import
gate accepted this core; neither of its two targeted imports was present, so
no binary mutation was needed.

The SDK collector validated **19 static archives, 1,480 archive members,
50 LLVM bitcode members and 71 ELF files**. All bitcode targets were
`aarch64-unknown-linux-android26`. It excluded two `.la` files and relocated
three `.pc` files. An x86 bitcode archive was correctly rejected for arm64.

The SDK was then moved outside the original build directory. A real NDK C
consumer used its pkg-config metadata to link mpv, FFmpeg and libplacebo, and
called a dav1d API to require its LTO objects. Compilation and linking passed;
every resulting `-I` and `-L` flag resolved inside the relocated SDK. The
consumer ELF SHA-256 was
`2892255dba24b938598717c42240d36ed4984ec039e3949561cb5b677102175b`.

The compiled core enabled Android Media NDK, Vulkan, external YUV,
`disable_dovi_linear_decode` and the initial DOVI HVCC capability. FFmpeg's
generated configuration enabled mbedTLS, HTTP, HTTPS and TLS protocols.

The repository's complete contract suite passed: **76 tests**. It includes
real four-ABI fixture linking, source/package boundary checks, and rejection
of comma-separated linker host paths in pkg-config metadata.

## Validation boundary

This verifies the arm64 native core, its development SDK and the compiler/link
interface. It does not verify the Android helper build, complete runtime JAR
assembly, the other three native source builds, an APK build, on-device loading
or playback. The generated verification evidence keeps runtime and device
acceptance false.
