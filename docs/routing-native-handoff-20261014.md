# MK-ROUTING-20261011 / native producer continuation

Continue the existing DV001 PR1 branch from 1095a43acb4d0973b8bca59c5da4e300657bdb29. No new competing branch, no merge or Release. Registration: native PR1 comment6170328571. The user's latest HDR10+/Vivid scope remains static PQ/HLG; dynamic C1/C2 and B1-B4 are deferred. App d128d36 + library d07b46b source validation is already complete; do not reimplement it.

## Checkpoint 1: import gate

Replaced the partial in-place ELF64 patcher with a bounded ELF32/64 parser for the four Android ABI layouts. Parse the entire symbol table before any write; modify only GLOBAL undefined targets, leave definitions untouched, permit a verified absent-target no-op, verify the result in memory, then commit it atomically. Unexpected bindings, ABI mismatch, malformed string/section tables, links and failed writes fail closed. Runtime weak-import safety is NOT approved by this tool.

The default bundle calls the parser for every ABI directly. There is no nm/grep predicate and no skip-environment bypass. Thus a malformed input cannot become a successful no-import result. Existing bundle build/staging/provenance problems are NOT declared solved by this checkpoint.

Local execution: `/usr/bin/python3 -S -m unittest discover -s tests -p test_vulkan_imports.py -v` and the corresponding test_bundle_import_gate.py suite. Actual results: 13 ELF tests and 4 shell-boundary tests passed, exit 0 in two invocations. Sixteen Clang/LLD real ELF fixture combinations cover four ABIs and both/either/neither target. Independent readelf checks inspect patched dynamic symbols. Four additional tests execute the production shell gate with controlled command failure/missing tool/later ABI failure/all-ABI success, including the obsolete skip environment value. These are host fixtures, not NDK/product/device tests. Initial local tool invocation timed out after printing OK; only subsequent exit-0 invocations are counted.

## Remaining producer work

1. Propagate failures through download/patch/build/helper, replace reused dirs and wildcard .so copies with fresh staging and exactly three members; bind libc++ to the same NDK and helper to the current source/build.
2. Capture current applicable FFmpeg/mpv/libplacebo/helper refs once and check freshness before/after native build. Record ordered patches, toolchain identity and actual linker inputs. Correct the original workflow's fixed upstream repository output paths and runtime recipe edits.
3. Produce and review the real JAR plus companion evidence under the App verifier's contract. Only then select a native manifest. Do not populate acceptance from fixture success or old JARs.
4. Build/verify current Android and Pink APKs, ABI/signature/member parity, then test on devices. Other platform native producers remain separate.

The original public native routing ref and App accepted-input ledger remain unchanged at this checkpoint. The user's local checkout/WIP is not accessible through the failed Codex connection and has not been modified. Read current PR comments and remote HEAD before every successor write.
