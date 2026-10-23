"""Run the production shell entry with isolated stage-failure fixtures."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BundlePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bs = self.root / 'buildscripts'
        self.bs.mkdir()
        for sub in ('scripts', 'include', 'flavors'):
            (self.bs / sub).mkdir()
        shutil.copyfile(ROOT / 'buildscripts/bundle_default.sh', self.bs / 'bundle_default.sh')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.executable(self.bin / 'git', 'exit 0')
        self.executable(self.bin / 'python3', 'exec /usr/bin/python3 -S "$@"')
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'])
        (self.bs / 'include/depinfo.sh').write_text('v_ndk=27.2.12479018\n')
        ndk = self.bs / 'sdk/android-sdk-linux/ndk/27.2.12479018'
        tools = ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin'
        tools.mkdir(parents=True)
        (ndk / 'source.properties').write_text('Pkg.Revision = 27.2.12479018\n')
        for name in ('clang', 'llvm-nm', 'llvm-readelf'):
            self.executable(tools / name, 'exit 0')
        (self.bs / 'scripts/current_native_sources.py').write_text(
            'import pathlib,sys\n'
            'if "--output" in sys.argv: pathlib.Path(sys.argv[sys.argv.index("--output")+1]).write_text("{}")\n')
        (self.bs / 'flavors/default.sh').write_text('fixture flavor\n')
        self.executable(self.bs / 'include/download-deps.sh',
            'mkdir -p deps/media-kit-android-helper/app/src/main/cpp\n'
            'printf "android {\\n}\\n" > deps/media-kit-android-helper/app/build.gradle\n'
            'printf "add_link_options(\"LINKER:--build-id=none\")\\n" > '
            'deps/media-kit-android-helper/app/src/main/cpp/CMakeLists.txt\n'
            'printf "#!/bin/bash\\nexit 37\\n" > deps/media-kit-android-helper/gradlew\n'
            'printf "download\\n" >> stages')
        self.executable(self.bs / 'patch.sh', 'printf "patch\\n" >> stages')
        self.executable(self.bs / 'build.sh', 'printf "build\\n" >> stages')

    def executable(self, path, body):
        path.write_text('#!/bin/bash\n' + body + '\n')
        path.chmod(0o755)

    def run_bundle(self, *args):
        return subprocess.run(['/bin/bash', str(self.bs / 'bundle_default.sh'), *args], env=self.env,
                              capture_output=True, text=True, timeout=15)

    def assert_failed(self, code):
        result = self.run_bundle()
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertFalse((self.bs / 'routing-native-output').exists())
        self.assertEqual((self.bs / 'routing-native-evidence/exit-code.txt').read_text().strip(), str(code))

    def test_download_failure_stops_before_patch(self):
        self.executable(self.bs / 'include/download-deps.sh', 'exit 31')
        self.assert_failed(31)
        self.assertFalse((self.bs / 'stages').exists())

    def test_failure_inside_child_shell_is_not_hidden_by_later_success(self):
        self.executable(self.bs / 'include/child.sh', 'false\nprintf "bad-success\\n" >> stages')
        self.executable(self.bs / 'include/download-deps.sh', 'bash include/child.sh\nprintf "bad-parent\\n" >> stages')
        self.assert_failed(1)
        self.assertFalse((self.bs / 'stages').exists())

    def test_patch_failure_stops_before_build(self):
        self.executable(self.bs / 'patch.sh', 'exit 32')
        self.assert_failed(32)
        self.assertEqual((self.bs / 'stages').read_text(), 'download\n')

    def test_build_failure_stops_before_helper_and_packaging(self):
        self.executable(self.bs / 'build.sh', 'exit 33')
        self.assert_failed(33)
        self.assertEqual((self.bs / 'stages').read_text(), 'download\npatch\n')

    def test_helper_failure_stops_before_packaging(self):
        self.assert_failed(37)
        self.assertFalse((self.bs / 'routing-native-evidence/prepared').exists())

    def test_helper_cmake_build_id_override_applies_before_build(self):
        # The member packaging gate requires one GNU build-id per ELF while
        # upstream suppresses it; the driver must flip the suppression
        # before the helper build runs.
        self.run_bundle()
        cmake = (self.bs / 'deps/media-kit-android-helper/app/src/main/cpp/CMakeLists.txt').read_text()
        self.assertIn('--build-id=sha1', cmake)
        self.assertNotIn('--build-id=none', cmake)

    def test_capture_failure_never_falls_back_to_recipe_defaults(self):
        (self.bs / 'scripts/current_native_sources.py').write_text('raise SystemExit(41)\n')
        self.assert_failed(41)
        self.assertFalse((self.bs / 'stages').exists())

    def test_existing_build_directories_are_preserved_and_rejected(self):
        for name in ('deps', 'prefix', 'temp', 'routing-native-output', 'routing-native-package'):
            with self.subTest(name=name):
                folder = self.bs / name
                folder.mkdir()
                old = folder / 'old.so'
                old.write_bytes(b'preserve')
                result = self.run_bundle()
                self.assertEqual(result.returncode, 2)
                self.assertEqual(old.read_bytes(), b'preserve')
                old.unlink()
                folder.rmdir()

    def test_explicit_source_lock_selects_locked_mode_without_hiding_stage_failure(self):
        lock = self.root / 'locked.json'
        lock.write_text('{}')
        self.executable(self.bs / 'include/download-deps.sh', 'exit 31')
        result = self.run_bundle('--source-lock', str(lock))
        self.assertEqual(result.returncode, 31, result.stdout + result.stderr)
        self.assertEqual((self.bs / 'routing-native-evidence/source-mode.txt').read_text(), 'locked-source\n')
        self.assertFalse((self.bs / 'routing-native-output').exists())

    def test_source_lock_does_not_allow_a_reused_prefix(self):
        lock = self.root / 'locked.json'
        lock.write_text('{}')
        prefix = self.bs / 'prefix'
        prefix.mkdir()
        (prefix / 'old.a').write_bytes(b'keep')
        result = self.run_bundle('--source-lock', str(lock))
        self.assertEqual(result.returncode, 2)
        self.assertEqual((prefix / 'old.a').read_bytes(), b'keep')

    def test_missing_source_lock_fails_before_creating_evidence(self):
        result = self.run_bundle('--source-lock', str(self.root / 'missing.json'))
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.bs / 'routing-native-evidence').exists())

    def test_wrong_ndk_version_fails_before_dependency_download(self):
        props = self.bs / 'sdk/android-sdk-linux/ndk/27.2.12479018/source.properties'
        props.write_text('Pkg.Revision = 26.0.0\n')
        self.assert_failed(1)
        self.assertFalse((self.bs / 'stages').exists())

    def test_old_jar_is_preserved_and_rejected(self):
        old = self.bs / 'default-arm64-v8a.jar'
        old.write_bytes(b'preserve old jar')
        result = self.run_bundle()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(old.read_bytes(), b'preserve old jar')


if __name__ == '__main__':
    unittest.main()
