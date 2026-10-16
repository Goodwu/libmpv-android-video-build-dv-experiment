"""Exercise exact-member packaging with real AArch64 ELF and ZIP fixtures."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'buildscripts/scripts'))
import package_native as package


class NativePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cc = shutil.which('clang')
        if not cc or not shutil.which('ld.lld'):
            raise RuntimeError('real clang/LLD fixture tools are required')
        cls.readelf, cls.nm = shutil.which('readelf'), shutil.which('nm')
        if not cls.readelf or not cls.nm:
            raise RuntimeError('real readelf and nm tools are required')
        flags = [cc, '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-fPIC', '-shared', '-nostdlib', '-Wl,--build-id']
        dep = cls.root / 'dep.c'
        dep.write_text('void dependency(void) {}\n')
        subprocess.run(flags + [str(dep), '-Wl,-soname,libfixture.so', '-o', str(cls.root / 'libfixture.so')],
                       check=True, capture_output=True)
        cls.inputs = {}
        for name in package.NAMES:
            src = cls.root / (name + '.c')
            src.write_text('extern void dependency(void); void entry(void) { dependency(); }\n')
            dest = cls.root / name
            subprocess.run(flags + [str(src), '-L' + str(cls.root), '-lfixture', '-Wl,-soname,' + name,
                                    '-o', str(dest)], check=True, capture_output=True)
            cls.inputs[name] = dest.read_bytes()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.path = Path(self.work.name)
        for name, data in self.inputs.items():
            (self.path / name).write_bytes(data)
        self.apk = self.path / 'helper.apk'
        self.helper_name = 'lib/arm64-v8a/libmediakitandroidhelper.so'
        with zipfile.ZipFile(self.apk, 'w') as archive:
            archive.writestr(self.helper_name, self.inputs['libmediakitandroidhelper.so'])
            archive.writestr('irrelevant.txt', 'not a native member')
        self.output = self.path / 'output'

    def package(self, **kwargs):
        return package.package(self.path / 'libmpv.so', self.apk, self.path / 'libc++_shared.so', self.output,
                               abi='arm64-v8a', readelf=kwargs.get('readelf', self.readelf), nm=kwargs.get('nm', self.nm))

    def test_exact_three_members_receipts_and_unchanged_inputs(self):
        value = self.package()
        self.assertEqual(value['status'], 'packaged-unreviewed')
        self.assertFalse(value['nativeVerified'])
        self.assertFalse(value['deviceVerified'])
        with zipfile.ZipFile(self.output / 'default-arm64-v8a.jar') as archive:
            self.assertEqual(len(archive.infolist()), 3)
            self.assertEqual(set(archive.namelist()), set(value['members']))
        for name, data in self.inputs.items():
            self.assertEqual((self.path / name).read_bytes(), data)
        self.assertTrue((self.output / 'packaging.json').is_file())

    def test_reproducible_packaging_from_equal_inputs(self):
        first = self.package()['jarSha256']
        self.output = self.path / 'another'
        self.assertEqual(first, self.package()['jarSha256'])

    def test_existing_destination_is_not_updated_or_deleted(self):
        self.output.mkdir()
        old = self.output / 'old.so'
        old.write_bytes(b'untouched')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.package()
        self.assertEqual(old.read_bytes(), b'untouched')

    def test_missing_native_member_never_publishes_jar(self):
        (self.path / 'libc++_shared.so').unlink()
        with self.assertRaises(ValueError):
            self.package()
        self.assertFalse(self.output.exists())

    def test_helper_duplicate_member_is_rejected(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.apk, 'a') as archive:
                archive.writestr(self.helper_name, self.inputs['libmediakitandroidhelper.so'])
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            self.package()
        self.assertFalse(self.output.exists())

    def test_wrong_helper_abi_or_missing_member_is_rejected(self):
        with zipfile.ZipFile(self.apk, 'w') as archive:
            archive.writestr(self.helper_name.replace('arm64-v8a', 'x86_64'), self.inputs['libmediakitandroidhelper.so'])
        with self.assertRaises(ValueError):
            self.package()
        self.assertFalse(self.output.exists())

    def test_malformed_input_cannot_be_an_import_noop(self):
        (self.path / 'libmpv.so').write_bytes(b'not ELF')
        with self.assertRaises(ValueError):
            self.package()
        self.assertFalse(self.output.exists())

    def test_missing_readelf_fails_instead_of_assuming_no_imports(self):
        with self.assertRaises(OSError):
            self.package(readelf=self.path / 'missing')
        self.assertFalse(self.output.exists())

    def test_nm_nonzero_exit_is_not_no_imports(self):
        real_run = package.subprocess.run
        def run(argv, **kwargs):
            if argv[0] == self.nm:
                return subprocess.CompletedProcess(argv, 17, '', 'injected nm failure')
            return real_run(argv, **kwargs)
        with patch.object(package.subprocess, 'run', side_effect=run):
            with self.assertRaisesRegex(ValueError, 'ELF tool failed'):
                self.package()
        self.assertFalse(self.output.exists())

    def test_readelf_error_output_even_with_zero_exit_is_rejected(self):
        with patch.object(package.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', 'parse warning')):
            with self.assertRaises(ValueError):
                self.package()
        self.assertFalse(self.output.exists())

    def test_wrong_soname_is_rejected(self):
        (self.path / 'libmpv.so').write_bytes(self.inputs['libc++_shared.so'])
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.package()
        self.assertFalse(self.output.exists())

    def test_failed_publication_cleans_only_its_new_directory(self):
        with patch.object(package.os, 'link', side_effect=OSError('injected publish failure')):
            with self.assertRaises(OSError):
                self.package()
        self.assertFalse(self.output.exists())
        self.assertTrue(self.apk.is_file())


if __name__ == '__main__':
    unittest.main()
