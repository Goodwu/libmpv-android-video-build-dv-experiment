# Android native source builds and reusable packages

The native producer builds all four Android ABIs from a single source vector.
The app can reuse its complete runtime package without rebuilding FFmpeg,
libplacebo and mpv for a Dart-only change. A development SDK is a separate part
of the package: it contains the matching headers, static dependencies,
pkg-config files and runtime libraries. An older runtime JAR alone is not this
SDK.

## Source selection

The existing command still requires fresh `deps`, `prefix`, evidence and output
directories, captures the registered live branches once, and checks their tips
before and after the build:

```sh
bash buildscripts/bundle_default.sh
```

To build reviewed commits, including an isolated mpv fix, pass an explicit
four-component source lock:

```sh
bash buildscripts/bundle_default.sh --source-lock /absolute/path/android-sources.json
```

The JSON has exactly the four keys `ffmpeg`, `mpv`, `libplacebo` and
`media-kit-android-helper`. Each value has `repository`, `branch` and `commit`.
Repositories must be the registered URLs from
`buildscripts/scripts/current_native_sources.py`; commits must be full 40-digit
Git object IDs. The branch is a provenance label in locked mode, while the
exact commit controls checkout. No fallback to a branch tip or a legacy recipe
pin is permitted.

Locked mode still downloads and compiles into a fresh build tree. It checks the
actual checkout, origin, tree, submodules and modifications before and after
compilation, but deliberately does not require the selected commit to remain a
moving branch's latest tip. Its evidence says `locked-source-checked`, not
`current-source-checked`. This explicit mode does not authorize reuse of an old
prefix or JAR as the result of a new source build.

## Collect a complete package

After a successful bundle build, run:

```sh
export ENCODERS_GPL=${ENCODERS_GPL:-}
. buildscripts/include/depinfo.sh
python3 buildscripts/scripts/package_native_bundle.py \
  --build-root buildscripts --output buildscripts/routing-native-package \
  --android-api "$v_android_api"
```

The new destination contains:

| Path | Purpose |
| --- | --- |
| `root/runtime/default-<abi>.jar` | Exactly libmpv, the Android helper and libc++ for that ABI |
| `root/sdk/<abi>/include` | Matching installed development headers |
| `root/sdk/<abi>/lib` | Static dependencies, pkg-config metadata, and runtime libraries |
| `root/evidence` | Source/patch/compiler/link/ELF records, SDK ABI checks and compiled capabilities |
| `spec.json` | Metadata for the shared media-kit manifest creator; kept outside the payload root |

The collector verifies the JAR against its packaging receipt, checks the ELF
architecture of every SDK binary and every static archive member, and requires
the custom compiled capabilities to agree across all four ABIs. Missing
development headers or libraries, changed build inputs, mixed ABI archives,
external links and build-machine paths in pkg-config metadata fail the
collection step.

The historical `usr -> .` and `local -> .` build aliases become a real
`usr/local` directory with nonrecursive links to the SDK's include/lib
directories. Absolute internal library links become relative links. The SDK's
libmpv is replaced by the exact packaged runtime libmpv, including the existing
recorded Vulkan import transformation; the original source-build receipts stay
in evidence.

The workflow uploads `routing-native-package.tar.gz` so GitHub artifact ZIP
handling cannot discard or expand these links. The older individual JAR
artifacts remain available. No Release is created.

## Create and verify the shared manifest

Use an explicitly selected media-kit checkout containing
`tool/native_package/package.py`. From the package directory:

```sh
python3 /absolute/media-kit/tool/native_package/package.py create \
  --root "$PWD/root" --spec "$PWD/spec.json"
```

The command produces `root/manifest.json` and prints its SHA-256 and the build
identity SHA-256. Record those digests in the app's native input lock. The
manifest includes the complete payload inventory, all four JAR mappings and
all four `sdk_prefixes`. The build identity records actual dependency commits,
source modifications, recipe, toolchain, API level, build configuration and
patches.

Before reuse, authenticate the downloaded archive against its separately
recorded SHA-256, extract it safely, and run the shared verifier with the
recorded manifest digest:

```sh
python3 /absolute/media-kit/tool/native_package/package.py verify \
  --root /absolute/native-package/root \
  --manifest-sha256 <recorded-manifest-sha256> --platform android \
  --expected-identity <recorded-build-identity-sha256>
```

The app consumer selects all JARs from that verified manifest; it should not
combine an arm64 fork JAR with unrelated upstream JARs for the remaining ABIs.
Ordinary application builds do not require the SDK portion. A lower-level
native compilation can use a verified SDK prefix with the recorded NDK,
Android API and STL:

```sh
export PKG_CONFIG_SYSROOT_DIR=/absolute/native-package/root/sdk/arm64-v8a
export PKG_CONFIG_LIBDIR="$PKG_CONFIG_SYSROOT_DIR/lib/pkgconfig"
unset PKG_CONFIG_PATH
```

Set the corresponding NDK cross compiler and target API as well; the prefix
does not supply a host compiler or replace the Android NDK. The recipe's native
API level remains 26. This change does not establish support for running the
native libraries on Android API 24 or 25.

The fresh source entrypoint does not import SDKs automatically. A future
dependency-SDK rebuild mode must separately record the parent SDK identity,
rebuild the changed mpv/dependencies, and publish a new identity. Copying a
prefix into the fresh source job or substituting headers around an existing
libmpv is not an accepted reuse mode.

## Validation boundary

The collected candidate records `compiled=true`, `runtime=false`,
`device=false`. Hash checks, real host ELF fixtures and a green compiler do not
approve the Android bridge lifecycle, DV/HDR playback or device stability.
The compiled capabilities come from the actual four `config.h` files; app-side
runtime probing and device validation remain separate gates.

The FFmpeg HLS patch was rebased onto the actual routing source
`9aba43cfbee182ade060cdccbe15340a0fbe3e83`. Its added/deleted C statements were
preserved; only patch context and offsets changed. Validation included strict
forward/reverse applicability and compilation of the patched `libavformat/hls.o`.
The producer's strict patch-failure handling was not relaxed.
