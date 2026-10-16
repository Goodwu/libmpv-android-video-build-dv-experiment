"""Run the actual workflow driver block with disposable success/failure recipes."""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BundleLogCaptureTests(unittest.TestCase):
    def driver(self):
        workflow = (ROOT / '.github/workflows/build.yaml').read_text()
        start = workflow.index('      - name: Build and package one fresh current-source vector\n')
        block = workflow[start:workflow.index('\n      - name:', start + 1)]
        return textwrap.dedent(block.split('        run: |\n', 1)[1])

    def execute(self, recipe, *, break_log=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scripts = root / 'buildscripts'
            scripts.mkdir()
            (scripts / 'bundle_default.sh').write_text(recipe)
            setup = root / 'native-setup'
            setup.mkdir()
            log = setup / 'bundle.log'
            if break_log:
                log.mkdir()
            env = dict(os.environ, RUNNER_TEMP=str(root))
            env.pop('SHELLOPTS', None)
            result = subprocess.run(['bash', '-c', self.driver()], cwd=root,
                                    env=env, capture_output=True, text=True,
                                    timeout=10)
            return result, None if break_log else log.read_text()

    def test_real_driver_preserves_packaging_failure_exit_and_stderr(self):
        result, log = self.execute('printf "dependencies completed\\n"\n'
                                   'printf "actual packaging gate failed\\n" >&2\nexit 47\n')
        self.assertEqual(result.returncode, 47, result.stdout + result.stderr)
        self.assertIn('dependencies completed', log)
        self.assertIn('actual packaging gate failed', log)

    def test_successful_driver_captures_both_streams(self):
        result, log = self.execute('printf "packaged unreviewed\\n"\n'
                                   'printf "diagnostic\\n" >&2\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('packaged unreviewed', log)
        self.assertIn('diagnostic', log)

    def test_log_write_failure_is_not_reported_as_success(self):
        result, _ = self.execute('printf "packaged unreviewed\\n"\n', break_log=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
