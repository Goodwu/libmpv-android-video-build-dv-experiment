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


class DependencySubmodulesTests(unittest.TestCase):
    """Exercise the actual download gate with real, recursively pinned Git trees."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'include').mkdir()
        (self.root / 'include/depinfo.sh').write_text('# isolated source fixture\n')
        config = self.root / 'gitconfig'
        config.write_text('')
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=str(config),
                        GIT_CONFIG_NOSYSTEM='1', GIT_ALLOW_PROTOCOL='file')
        leaf = self.repo('leaf')
        self.pinned_leaf = self.git(leaf, 'rev-parse', 'HEAD')
        middle = self.repo('dlg')
        self.git(middle, 'submodule', 'add', str(leaf), 'nested')
        self.git(middle, 'commit', '-qm', 'pin nested source')
        parent = self.repo('freetype')
        self.git(parent, 'submodule', 'add', str(middle), 'subprojects/dlg')
        self.git(parent, 'commit', '-qm', 'pin dlg')
        self.pinned_parent = self.git(parent, 'rev-parse', 'HEAD')
        # A newer branch tip must never replace the commit in the gitlink.
        (leaf / 'source.txt').write_text('new source tip\n')
        self.git(leaf, 'commit', '-qam', 'advance source tip')
        self.new_leaf = self.git(leaf, 'rev-parse', 'HEAD')
        self.checkout = self.root / 'checkout'
        self.git(self.root, 'clone', '-q', str(parent), str(self.checkout))
        self.nested = self.checkout / 'subprojects/dlg/nested'
        source = (ROOT / 'buildscripts/include/download-deps.sh').read_text()
        self.download_functions = source.split('mkdir -p deps\n', 1)[0]

    def git(self, folder, *args):
        return subprocess.check_output(['git', '-C', str(folder), '-c', 'user.name=Fixture',
            '-c', 'user.email=fixture@example.invalid', *args],
            env=self.env, text=True, stderr=subprocess.PIPE).strip()

    def repo(self, name):
        root = self.root / name
        root.mkdir()
        self.git(root, 'init', '-q')
        (root / 'source.txt').write_text('original source\n')
        self.git(root, 'add', 'source.txt')
        self.git(root, 'commit', '-qm', 'source fixture')
        return root

    def verify(self, **env):
        return subprocess.run(['/bin/bash', '-c', self.download_functions +
            '\nverify_sha "$1" "$2"\nprintf VERIFIED', 'fixture',
            str(self.checkout), self.pinned_parent], cwd=self.root,
            env=dict(self.env, **env), text=True, capture_output=True)

    def test_missing_recursive_sources_are_initialized_to_gitlinks_for_reused_checkouts(self):
        self.assertTrue(self.git(self.checkout, 'submodule', 'status', '--recursive').startswith('-'))
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.nested, 'rev-parse', 'HEAD'), self.pinned_leaf)
        self.git(self.nested.parent, 'submodule', 'deinit', '-f', '--all')
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.nested, 'rev-parse', 'HEAD'), self.pinned_leaf)
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), self.pinned_parent)

    def test_changed_recursive_source_is_rejected_without_resetting_it(self):
        self.assertEqual(self.verify().returncode, 0)
        self.git(self.nested, 'checkout', '--detach', self.new_leaf)
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Changed source submodule', result.stdout)
        self.assertNotIn('VERIFIED', result.stdout)
        self.assertEqual(self.git(self.nested, 'rev-parse', 'HEAD'), self.new_leaf)

    def test_submodule_fetch_failure_stops_source_preparation(self):
        result = self.verify(GIT_ALLOW_PROTOCOL='https')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('VERIFIED', result.stdout)
        self.assertTrue(self.git(self.checkout, 'submodule', 'status', '--recursive').startswith('-'))


if __name__ == '__main__':
    unittest.main()
