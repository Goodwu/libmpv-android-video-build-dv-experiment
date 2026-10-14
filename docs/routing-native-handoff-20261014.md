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

## Checkpoint 2: current-source build and isolated packaging

Checkpoint 1 is committed as 47075b670010b5bede97f4b38afd6ec1cb239074 on the original DV001 branch. Hosted contract run38580015394 completed/success. The previous full-build workflow run38580015359 failed at Android SDK license setup (10-second timeout), BEFORE NDK setup or compilation; it is not native acceptance.

This checkpoint replaces the current default bundle's destructive cleanup/reused staging with a fresh-checkout requirement and inherited fail-fast shell execution. Download, patch, native build and helper errors propagate to the caller with their original exit codes. Archive download AND-lists and process-substitution patch inventory failures no longer disappear. Existing source directories and old JARs are refused, never deleted. Helpers explicitly use the same recipe NDK. Packaging takes exactly libmpv, the selected helper APK member and the matching NDK libc++; no wildcard native copies or old ZIP updates. Every ELF, ABI, SONAME, BuildID, NEEDED and undefined-symbol tool must validate before publishing. Vulkan binding edits affect only a private copy, not original build outputs.

The four applicable native repositories are captured from their live registered refs once, then actual checkout HEAD/tree/origin/submodules and remote freshness are checked before and after compilation. depinfo consumes those captured values in every child recipe; missing capture cannot silently fall back to old pins. Actual mpv ninja commands/logs, source diffs, patch inventory, NDK/compiler identity and static archive hashes are retained as review inputs. These partial provenance receipts DO NOT yet satisfy the App's complete canonical source/link/sysroot/weak-runtime acceptance contract.

The native workflow now checks out the exact candidate, uses the hosted SDK directly with the recipe-selected NDK, installs host tools in a private Python environment, runs all contracts before compilation and builds without runtime sed-rewriting the recipe. Missing licenses fail explicitly. Artifacts use this repository's actual relative paths. No GitHub Release is created. Successful candidate JARs and companion evidence are explicitly unreviewed; partial prepared JARs are excluded from failure artifacts.

Local validation at this checkpoint: 50 unittest cases passed, zero skips, including 13 real ELF tests (16 ABI/target combinations), 12 real AArch64 package tests, 4 shell import-gate faults, 9 full-entrypoint stage/reuse/NDK faults, 9 source-vector tests (including actual local Git checkout/origin/tree records; only remote tips are mocked), and 3 download/patch/workflow contracts. Source/compiler and ELF fixtures are host tests, not an NDK product build. Full updated cloud native build is pending. Shell syntax checks also passed. The latest full test log is all-native-contracts.log in the ChatGPT working directory, not the inaccessible user's local workspace.

Current observed component refs before this checkpoint: FFmpeg9aba43cfbee182ade060cdccbe15340a0fbe3e83; mpv4f036f5cfa493e53dbe8fe2aa2cd5e356b2fc7b1 (newer than recipe's old c114); libplaceboea700489fbf27703d8c1f64874a1c6138f17ad28; helperb768ce102cfa9b5ddec618bb939d689d1b0899fa. These are observations; a new run captures current refs rather than using this text as pins.

Remaining: make the actual current-source native build pass, independently inspect real ELF/JAR/patch/link evidence and complete the App verifier manifest and weak-import runtime contract. Only then select a native input and build Android/Pink APKs, verify members/ABI/signature/parity and run devices. Public native routing stays at1095; Appd128d36 and its empty accepted-inputs ledger are unchanged. Dynamic HDR scope remains deferred, and no local WIP has been modified.
