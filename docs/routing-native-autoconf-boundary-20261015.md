# Native Autoconf boundary / MK-ROUTING-20261011

Continue original PR1 and device/MK-ROUTING-20261011/DV001 from 8f1dd98; no competing branch, merge, Release or accepted-input changes.

## Observed failure

Run38584797265/job115924528885 failed after dav1d built, at libxml2 checking build system type. Artifact11905790334 was downloaded and independently SHA-256 checked: 8c90c20fd1fcd7e2378963fc37abe61f84d6d5df3cdf4af657833fd45f4ade52. No JAR was produced. Old 50-contract success is not native build success.

Global export SHELLOPTS carries errexit/pipefail into third-party Autoconf/config.guess probes. A real AC_CANONICAL_BUILD fixture reproduces exit1 at the same line when the options are exported and exit0/config.status when they are not. The actual production build.sh dispatcher reproduces two failures with the new tests before this patch; after the boundary patch all five pass locally, no skips. The two failures were canonical-build success and reaching an injected configure failure (before the patch the probe died too early to reach that injected failure).

## Narrow repair

Keep the bundle's repository-stage propagation unchanged. Invoke each target recipe with env -u SHELLOPTS bash -e -o pipefail for clean/build. This explicitly retains recipe failure checking, but normal third-party subprocesses do not inherit exported Bash probe-breaking flags. Existing ELF/member/source/NDK/packaging gates remain unchanged. Real dispatcher regressions cover successful Autoconf, real configure rejection, a failing recipe command, a failed pipeline and clean failure before build. The contract workflow installs its real Autoconf/config.guess fixtures; missing tools are errors, never skipped tests.

Next: independently validate current-head hosted contracts and a fresh native build. Current source vector must be captured again; do not pin the older mpv/FFmpeg inputs for the retry. A produced package remains PACKAGED_UNREVIEWED until complete source/link/manifest/ELF/runtime review; this patch is not JAR, APK or device acceptance. App currently integrates media-kit2276715; normal production YUV owner lifecycle is a distinct library blocker, not solved by this build-script fix. HDR10+/Vivid dynamic B1-B4 remain deferred.
