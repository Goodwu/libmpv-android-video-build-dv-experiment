"""Execute the actual bundle gate with fault-injected command boundaries."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BundleImportGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        script = (ROOT / 'buildscripts/bundle_default.sh').read_text()
        self.gate = script.split('# BEGIN VALIDATED VULKAN IMPORT GATE', 1)[1].split(
            '# END VALIDATED VULKAN IMPORT GATE', 1)[0]
        self.env = dict(os.environ, PATH=str(self.root), PILIPLUSX_SKIP_VULKAN_WEAKEN='1')
        realpath = self.root / 'realpath'
        realpath.write_text('#!/bin/bash\nprintf "%s\\n" "$1"\n')
        realpath.chmod(0o755)

    def run_gate(self):
        return subprocess.run(['/bin/bash', '-c', self.gate + '\nprintf ZIP_REACHED'],
                              env=self.env, cwd=self.root, capture_output=True, text=True)

    def tool(self, body):
        tool = self.root / 'python3'
        tool.write_text('#!/bin/bash\n' + body)
        tool.chmod(0o755)

    def test_missing_parser_tool_cannot_become_no_imports_or_be_bypassed(self):
        result = self.run_gate()
        self.assertEqual(result.returncode, 127)
        self.assertNotIn('ZIP_REACHED', result.stdout)

    def test_failed_parser_preserves_original_exit_and_stops_before_zip(self):
        self.tool('exit 29\n')
        result = self.run_gate()
        self.assertEqual(result.returncode, 29)
        self.assertNotIn('ZIP_REACHED', result.stdout)

    def test_each_abi_is_checked_and_a_later_failure_stops_remaining_abis(self):
        self.tool('printf "%s\\n" "$*" >> calls\ncase "$*" in *armeabi-v7a*) exit 23;; esac\n')
        result = self.run_gate()
        self.assertEqual(result.returncode, 23)
        calls = (self.root / 'calls').read_text().splitlines()
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].endswith('--abi arm64-v8a'))
        self.assertTrue(calls[1].endswith('--abi armeabi-v7a'))
        self.assertNotIn('ZIP_REACHED', result.stdout)

    def test_success_checks_all_four_abis_before_zip(self):
        self.tool('printf "%s\\n" "$*" >> calls\n')
        result = self.run_gate()
        self.assertEqual(result.returncode, 0)
        calls = (self.root / 'calls').read_text().splitlines()
        self.assertEqual([line.split()[-1] for line in calls], ['arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'])
        self.assertEqual(result.stdout, 'ZIP_REACHED')


if __name__ == '__main__':
    unittest.main()
