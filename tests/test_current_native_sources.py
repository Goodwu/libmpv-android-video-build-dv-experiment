from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'buildscripts/scripts'))
import current_native_sources as sources


class CurrentSourcesTests(unittest.TestCase):
    def vector(self):
        return {name: {'repository': url, 'branch': branch, 'commit': str(i) * 40}
                for i, (name, (url, branch, _)) in enumerate(sources.SOURCES.items(), 1)}

    def test_capture_reads_each_registered_live_branch_once(self):
        with patch.object(sources, 'remote_tip', side_effect=['1' * 40, '2' * 40, '3' * 40, '4' * 40]) as tip:
            self.assertEqual(sources.capture(), self.vector())
        self.assertEqual(tip.call_count, 4)

    def test_exports_contains_only_validated_named_sha_values(self):
        value = sources.exports(self.vector())
        self.assertEqual(len(value.splitlines()), 4)
        self.assertIn('export ROUTING_FFMPEG_SHA=' + '1' * 40, value)
        vector = self.vector()
        vector['mpv']['commit'] = '$(false)'
        with self.assertRaises(ValueError):
            sources.exports(vector)

    def test_other_repository_or_branch_cannot_substitute_current_sources(self):
        for field in ('repository', 'branch'):
            vector = self.vector()
            vector['ffmpeg'][field] = 'replacement'
            with self.assertRaises(ValueError):
                sources.validate(vector)

    def test_explicit_lock_accepts_isolated_branch_but_keeps_repository_and_sha_gates(self):
        vector = self.vector()
        vector['mpv']['branch'] = 'codex/piliplus-dovi-capabilities-20261023'
        with self.assertRaises(ValueError):
            sources.exports(vector)
        self.assertIn('export ROUTING_MPV_SHA=' + '2' * 40, sources.exports(vector, locked=True))
        for field, value in [('repository', 'https://example.invalid/replacement.git'),
                             ('commit', 'main'), ('branch', 'bad;command')]:
            changed = {name: dict(row) for name, row in vector.items()}
            changed['mpv'][field] = value
            with self.assertRaises(ValueError):
                sources.validate(changed, locked=True)

    def test_lock_cli_copies_validated_identity_without_resolving_remote_tips(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vector = self.vector()
            vector['mpv']['branch'] = 'codex/isolated'
            (root / 'input.json').write_text(json.dumps(vector))
            result = subprocess.run([sys.executable, str(ROOT / 'buildscripts/scripts/current_native_sources.py'),
                                     'lock', '--input', str(root / 'input.json'),
                                     '--output', str(root / 'locked.json')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((root / 'locked.json').read_text()), vector)

    def test_missing_ambiguous_or_wrong_remote_ref_is_rejected(self):
        for output in ('', '1' * 40 + '\trefs/heads/other', '1' * 40 + '\trefs/heads/main\n' + '2' * 40 + '\trefs/heads/main'):
            with patch.object(sources, 'command', return_value=output):
                with self.assertRaises(ValueError):
                    sources.remote_tip('repo', 'main')

    def test_git_failure_is_not_an_empty_successful_snapshot(self):
        with patch.object(sources.subprocess, 'run', return_value=subprocess.CompletedProcess([], 7, '', 'failure')):
            with self.assertRaisesRegex(ValueError, 'command failed'):
                sources.remote_tip('repo', 'main')

    def test_captured_exports_drive_all_actual_recipe_source_variables(self):
        result = subprocess.run(['/bin/bash', '-c', sources.exports(self.vector()) +
            '. "' + str(ROOT / 'buildscripts/include/depinfo.sh') + '"\n' +
            'printf "%s\\n" "$v_ffmpeg" "$v_mpv" "$v_libplacebo" "$v_media_kit_android_helper" "$sha_ffmpeg"'],
            capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(), ['1' * 40, '2' * 40, '3' * 40, '4' * 40, '1' * 40])

    def test_actual_git_checkouts_origins_trees_and_mutations_are_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            deps = Path(temp)
            vector = self.vector()
            for name, row in vector.items():
                root = deps / name
                root.mkdir()
                for argv in (['init', '-b', 'fixture'], ['config', 'user.name', 'Fixture'],
                             ['config', 'user.email', 'fixture@example.invalid']):
                    subprocess.run(['git', '-C', str(root), *argv], check=True, capture_output=True)
                (root / 'input.txt').write_text('original\n')
                for argv in (['add', '.'], ['commit', '-m', 'fixture'], ['remote', 'add', 'origin', row['repository']]):
                    subprocess.run(['git', '-C', str(root), *argv], check=True, capture_output=True)
                row['commit'] = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
            (deps / 'mpv/input.txt').write_text('modified fixture\n')
            tips = {row['repository']: row['commit'] for row in vector.values()}
            with patch.object(sources, 'remote_tip', side_effect=lambda url, branch: tips[url]):
                receipt = sources.check(vector, deps)
                self.assertEqual(receipt['status'], 'current-source-checked')
                self.assertEqual(set(receipt['components']), set(vector))
                self.assertIn('+modified fixture', receipt['components']['mpv']['trackedDiff'])
                with patch.object(sources, 'remote_tip', side_effect=AssertionError('locked build must not query a tip')):
                    locked = sources.check(vector, deps, locked=True)
                    self.assertEqual(locked['status'], 'locked-source-checked')
                    self.assertEqual(locked['components'], receipt['components'])
                subprocess.run(['git', '-C', str(deps / 'ffmpeg'), 'remote', 'set-url', 'origin', 'wrong'], check=True)
                with self.assertRaisesRegex(ValueError, 'origin differs'):
                    sources.check(vector, deps)

    def test_uninitialized_submodule_is_not_a_current_source_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'ffmpeg'
            root.mkdir()
            with patch.object(sources, 'command', side_effect=[str(root), '1' * 40,
                    sources.SOURCES['ffmpeg'][0], '-' + '5' * 40 + ' missing-submodule\n']):
                with patch.object(sources, 'remote_tip', return_value='1' * 40):
                    with self.assertRaisesRegex(ValueError, 'submodule'):
                        sources.check(self.vector(), Path(temp))

    def test_checkout_mismatch_and_remote_advance_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            deps = Path(temp)
            root = deps / 'ffmpeg'
            root.mkdir()
            with patch.object(sources, 'command', side_effect=[str(root), '9' * 40]):
                with self.assertRaisesRegex(ValueError, 'checkout does not match'):
                    sources.check(self.vector(), deps)
            with patch.object(sources, 'command', side_effect=[str(root), '1' * 40]):
                with patch.object(sources, 'remote_tip', return_value='9' * 40):
                    with self.assertRaisesRegex(ValueError, 'advanced'):
                        sources.check(self.vector(), deps)


if __name__ == '__main__':
    unittest.main()
