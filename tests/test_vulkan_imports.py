"""Real cross-linked ELF fixtures, not substitute output from nm/grep."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("weak", ROOT / "buildscripts/scripts/weaken_undefined_imports.py")
weak = importlib.util.module_from_spec(spec)
spec.loader.exec_module(weak)
A, B = weak.VULKAN_1_1_MISSING_BEFORE_API_28


class VulkanImportsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clang = shutil.which("clang")
        if not cls.clang or not shutil.which("ld.lld") or not shutil.which("readelf"):
            raise RuntimeError("clang, ld.lld and readelf are required; no skipped ELF tests")
        cls.fixtures = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixtures.cleanup)
        cls.root = Path(cls.fixtures.name)
        cls.inputs = {}
        for abi, triple in {"arm64-v8a": "aarch64-linux-gnu", "armeabi-v7a": "armv7a-linux-gnueabi",
                            "x86": "i686-linux-gnu", "x86_64": "x86_64-linux-gnu"}.items():
            for names in [(), (A,), (B,), (A, B)]:
                source = cls.root / f"{abi}-{len(cls.inputs)}.c"
                source.write_text("\n".join(f"extern void {name}(void);" for name in names) +
                                  "\nvoid entry(void) {" + "".join(f"{name}();" for name in names) + "}\n")
                target = source.with_suffix(".so")
                subprocess.run([cls.clang, f"--target={triple}", "-fuse-ld=lld", "-fPIC", "-shared", "-nostdlib",
                                "-Wl,--build-id", str(source), "-o", str(target)], check=True, capture_output=True)
                cls.inputs[abi, names] = target.read_bytes()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "libmpv.so"
        self.file.write_bytes(self.inputs["arm64-v8a", (A, B)])

    def test_all_four_abis_both_targets_and_each_target_alone(self):
        for (abi, names), original in self.inputs.items():
            with self.subTest(abi=abi, names=names):
                result, receipt = weak.plan(original, abi=abi)
                self.assertEqual(set(receipt["patched"]), set(names))
                self.assertEqual(set(receipt["absent"]), {A, B} - set(names))
                self.assertEqual([i for i, pair in enumerate(zip(original, result)) if pair[0] != pair[1]],
                                 receipt["changedByteOffsets"])
                self.assertEqual(len(result), len(original))
                self.file.write_bytes(result)
                parsed = subprocess.run(["readelf", "--dyn-syms", "--wide", str(self.file)],
                                        check=True, capture_output=True, text=True)
                for name in names:
                    self.assertRegex(parsed.stdout, rf"WEAK\s+DEFAULT\s+UND\s+{name}")

    def test_already_weak_is_idempotent(self):
        receipt = weak.main(self.file)
        after = self.file.read_bytes()
        inode = self.file.stat().st_ino
        second = weak.main(self.file)
        self.assertEqual(self.file.read_bytes(), after)
        self.assertEqual(self.file.stat().st_ino, inode)
        self.assertEqual(second["patched"], [])
        self.assertEqual(second["alreadyWeak"], sorted([A, B]))
        self.assertEqual(second["beforeSha256"], receipt["afterSha256"])

    def test_valid_absence_does_not_write(self):
        self.file.write_bytes(self.inputs["arm64-v8a", ()])
        before = self.file.stat()
        receipt = weak.main(self.file)
        self.assertEqual(receipt["absent"], sorted([A, B]))
        self.assertEqual(self.file.stat().st_ino, before.st_ino)
        self.assertEqual(self.file.stat().st_mtime_ns, before.st_mtime_ns)

    def test_defined_target_is_never_weakened(self):
        data = bytearray(self.file.read_bytes())
        symbol = next(s for s in weak.inspect(data)["symbols"] if s["name"] == A)
        struct.pack_into("<H", data, symbol["infoOffset"] + 2, 1)
        result, receipt = weak.plan(bytes(data))
        self.assertEqual(result[symbol["infoOffset"]], data[symbol["infoOffset"]])
        self.assertEqual(receipt["patched"], [B])

    def assert_unchanged_failure(self, data, **kwargs):
        self.file.write_bytes(data)
        with self.assertRaises((weak.ElfError, OSError, struct.error)):
            weak.main(self.file, **kwargs)
        self.assertEqual(self.file.read_bytes(), data)

    def test_invalid_headers_fail_without_writing(self):
        original = self.file.read_bytes()
        for data in [b"", b"not ELF", original[:63], original[:4] + b"\x03" + original[5:],
                     original[:5] + b"\x02" + original[6:]]:
            with self.subTest(length=len(data)):
                self.assert_unchanged_failure(data)

    def test_malformed_section_table_fails_without_writing(self):
        original = self.file.read_bytes()
        for offset, fmt, value in [(0x28, "<Q", len(original) + 4096), (0x3a, "<H", 0), (0x3c, "<H", 0)]:
            with self.subTest(offset=offset):
                data = bytearray(original)
                struct.pack_into(fmt, data, offset, value)
                self.assert_unchanged_failure(bytes(data))

    def test_bad_string_offset_fails_before_mutation(self):
        data = bytearray(self.file.read_bytes())
        symbol = next(s for s in weak.inspect(data)["symbols"] if s["name"] == B)
        struct.pack_into("<I", data, symbol["infoOffset"] - 4, len(data) + 1)
        self.assert_unchanged_failure(bytes(data))

    def test_late_bad_binding_cannot_leave_partial_patch(self):
        data = bytearray(self.file.read_bytes())
        targets = [s for s in weak.inspect(data)["symbols"] if s["name"] in (A, B)]
        data[targets[-1]["infoOffset"]] &= 15  # Unexpected LOCAL undefined target.
        self.assert_unchanged_failure(bytes(data))

    def test_abi_mismatch_fails(self):
        self.assert_unchanged_failure(self.file.read_bytes(), abi="x86_64")

    def test_unknown_symbol_requests_are_rejected(self):
        self.assert_unchanged_failure(self.file.read_bytes(), symbols=("malloc",))

    def test_atomic_write_failure_preserves_original(self):
        data = self.file.read_bytes()
        with patch.object(weak.os, "replace", side_effect=OSError("injected rename failure")):
            self.assert_unchanged_failure(data)
        self.assertEqual(list(self.file.parent.iterdir()), [self.file])

    def test_separate_output_preserves_input_and_refuses_existing_destination(self):
        before = self.file.read_bytes()
        output = self.file.parent / "new.so"
        weak.main(self.file, output)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertNotEqual(output.read_bytes(), before)
        with self.assertRaisesRegex(weak.ElfError, "already exists"):
            weak.main(self.file, output)

    def test_symlink_and_hardlink_inputs_are_rejected(self):
        link = self.file.parent / "link.so"
        link.symlink_to(self.file)
        with self.assertRaises(weak.ElfError):
            weak.main(link)
        link.unlink()
        os.link(self.file, link)
        with self.assertRaises(weak.ElfError):
            weak.main(link)


if __name__ == "__main__":
    unittest.main()
