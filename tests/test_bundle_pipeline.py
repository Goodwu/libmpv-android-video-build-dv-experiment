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
            'mkdir -p deps/media-kit-android-helper/app\n'
            'printf "android {\\n}\\n" > deps/media-kit-android-helper/app/build.gradle\n'
            'printf "#!/bin/bash\\nexit 37\\n" > deps/media-kit-android-helper/gradlew\n'
            'printf "download\\n" >> stages')
        self.executable(self.bs / 'patch.sh', 'printf "patch\\n" >> stages')
        self.executable(self.bs / 'build.sh', 'printf "build\\n" >> stages')

    def executable(self, path, body):
        path.write_text('#!/bin/bash\n' + body + '\n')
        path.chmod(0o755)

    def run_bundle(self):
        return subprocess.run(['/bin/bash', str(self.bs / 'bundle_default.sh')], env=self.env,
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

    def test_capture_failure_never_falls_back_to_recipe_defaults(self):
        (self.bs / 'scripts/current_native_sources.py').write_text('raise SystemExit(41)\n')
        self.assert_failed(41)
        self.assertFalse((self.bs / 'stages').exists())

    def test_existing_build_directories_are_preserved_and_rejected(self):
        for name in ('deps', 'prefix', 'temp', 'routing-native-output'):
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
