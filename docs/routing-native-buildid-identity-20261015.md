# Native ELF build-id identity diagnosis / 2026-10-15

Task MK-ROUTING-20261011 (W4). CI run 38713753519 (recipe 72b78358152c8904438557215637a0da65f3e0a9)
failed at the member packaging gate: `Native package rejected: ELF identity missing/ambiguous for libmpv.so`.

## Root cause (empirically verified)

`scripts/package_native.py` `facts()` requires exactly one GNU build-id note
(`readelf --notes` -> `Build ID:`) plus a unique SONAME and deduplicated
NEEDED list. All four conditions were collected from the actual CI evidence
(handoff ZIP `_temp/native-setup/bundle.log`, artifact 11963780995) and
reproduced locally against same-generation build outputs
(mpv d24c59905b + FFmpeg b4d2ea4, arm64-v8a):

- SONAME `libmpv.so`: exactly one — OK.
- NEEDED: 8 entries, no duplicates — OK.
- Build ID: **zero** — REJECT. The NDK r27c `clang -> lld` driver emits no
  GNU build-id note by default. A trivial `-shared` link with NDK
  27.2.12479073/…2479018 toolchain yields `BuildID = 0`; so does the entire
  warm mpv build tree (`deps/mpv/_build-arm64/libmpv.so`, pre-strip, and
  `prefix/.../libmpv.so`). The NDK-prebuilt `libc++_shared.so` carries one
  because Google's own build passes the flag explicitly.

The library was not corrupt; the identity evidence was never generated.

## Fix

`buildscripts/build.sh` now exports
`LDFLAGS="… -Wl,--build-id=sha1"` so every member link carries exactly one
build-id. This strengthens ELF identity; no packaging check was relaxed.

## Local verification (no clean rebuild yet)

The exact recorded libmpv.so link command was replayed from the warm arm64
build tree with only two deltas (output redirected to /tmp, flag added);
after the packaging gate's own Vulkan weakening step, the full `facts()`
check passes: sonames=['libmpv.so'], build_ids=1, needed=8 no duplicates,
no strong Vulkan imports, the two API<28 imports weakened. Raw tool
sessions: /tmp/wui (link-cmd.txt, link-cmd-fixed.sh, staged-libmpv.so).

Still required for W4 closure: a clean four-ABI build from this recipe on
the original DEVICE line, packaged JAR member/ABI evidence, and only then
the accepted-inputs ledger update. The host test suite on macOS shows four
pre-existing environment failures (host cc lacks aarch64-linux-gnu lld
target; /usr/share/misc/config.guess missing) identical to the unmodified
tree; CI Ubuntu provides those inputs.
