"""Execute failure boundaries in the actual download and patch entrypoints."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RecipeEntrypointsTests(unittest.TestCase):
    def test_each_archive_download_failure_stops_before_extract_or_next_command(self):
        source = (ROOT / 'buildscripts/include/download-deps.sh').read_text()
        for name, end in [('libogg', 'libvorbis'), ('libvorbis', 'libvpx')]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                wget = root / 'fetch'
                wget.write_text('#!/bin/bash\nexit 39\n')
                wget.chmod(0o755)
                block = source.split('# ' + name + '\n', 1)[1].split('# ' + end + '\n', 1)[0]
                result = subprocess.run(['/bin/bash', '-c', 'set -eo pipefail\n' +
                    f'WGET="{wget}"\nv_libogg=fixture\nv_libvorbis=fixture\n' + block + '\nprintf BAD'],
                    cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 39)
                self.assertNotIn('BAD', result.stdout)
                self.assertEqual(list(root.iterdir()), [wget])

    def test_patch_inventory_failure_is_not_hidden_by_process_substitution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'patches/mpv').mkdir(parents=True)
            git = root / 'git'
            git.write_text('#!/bin/bash\nexit 27\n')
            git.chmod(0o755)
            result = subprocess.run(['/bin/bash', str(ROOT / 'buildscripts/patch.sh')], cwd=root,
                env=dict(os.environ, PATH=str(root)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 27)

    def test_workflow_uses_exact_source_and_no_runtime_recipe_rewrites_or_release(self):
        source = (ROOT / '.github/workflows/build.yaml').read_text()
        self.assertIn('ref: ${{ github.event.pull_request.head.sha || github.sha }}', source)
        self.assertIn('contents: read', source)
        self.assertIn('"ndk;$v_ndk"', source)
        self.assertIn('"build-tools;$v_sdk_build_tools"', source)
        for old in ('container:', 'setup-android@', 'sed -i', 'action-gh-release', 'inputs.release',
                    '/home/runner/work/libmpv-android-video-build/'):
            self.assertNotIn(old, source)
        self.assertIn('!buildscripts/routing-native-evidence/prepared/**', source)
        self.assertIn('nativeVerified=false', source)


if __name__ == '__main__':
    unittest.main()
