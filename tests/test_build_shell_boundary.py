"""Exercise the real dispatcher, strict recipes and normal Autoconf probes."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BuildShellBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bs = self.root / 'buildscripts'
        self.dep = self.bs / 'deps/probe'
        self.dep.mkdir(parents=True)
        (self.bs / 'include').mkdir()
        (self.bs / 'scripts').mkdir()
        (self.bs / 'include/depinfo.sh').write_text('dep_probe=()\n')
        shutil.copyfile(ROOT / 'buildscripts/build.sh', self.bs / 'build.sh')
        self.recipe = self.bs / 'scripts/probe.sh'

    def run_build(self, *options):
        env = dict(os.environ)
        env.pop('SHELLOPTS', None)
        return subprocess.run([
            'bash', '-c', 'set -eo pipefail; export SHELLOPTS; exec bash "$@"',
            'boundary-test', str(self.bs / 'build.sh'), '--arch', 'arm64',
            '--no-deps', *options, 'probe',
        ], env=env, capture_output=True, text=True, timeout=30)

    def autoconf_fixture(self, *, reject=False):
        self.assertIsNotNone(shutil.which('autoconf'), 'real Autoconf is required')
        for name in ('config.guess', 'config.sub'):
            source = Path('/usr/share/misc') / name
            self.assertTrue(source.is_file(), f'autotools-dev input missing: {source}')
            shutil.copyfile(source, self.dep / name)
        body = ('AC_INIT([routing-shell-boundary], [1.0])\n'
                'AC_CONFIG_SRCDIR([configure.ac])\nAC_CANONICAL_BUILD\n')
        if reject:
            body += 'AC_MSG_ERROR([injected configure failure])\n'
        (self.dep / 'configure.ac').write_text(body + 'AC_OUTPUT\n')
        subprocess.run(['autoconf'], cwd=self.dep, check=True,
                       capture_output=True, timeout=30)
        self.recipe.write_text('#!/bin/bash\nmkdir _build\ncd _build\n'
                               '../configure\nprintf "done\\n" > completed\n')

    def test_autoconf_probe_succeeds_without_inherited_errexit(self):
        self.autoconf_fixture()
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.dep / '_build/config.status').is_file())
        self.assertEqual((self.dep / '_build/completed').read_text(), 'done\n')

    def test_failed_autoconf_stops_recipe_before_success_marker(self):
        self.autoconf_fixture(reject=True)
        result = self.run_build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('injected configure failure', result.stdout + result.stderr)
        self.assertFalse((self.dep / '_build/completed').exists())

    def test_recipe_failure_is_not_hidden_by_popd_or_later_success(self):
        self.recipe.write_text('#!/bin/bash\nfalse\ntouch bad-success\n')
        result = self.run_build()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse((self.dep / 'bad-success').exists())

    def test_recipe_pipeline_failure_stays_fatal(self):
        self.recipe.write_text('#!/bin/bash\nfalse | cat\ntouch bad-success\n')
        result = self.run_build()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse((self.dep / 'bad-success').exists())

    def test_clean_failure_prevents_build(self):
        self.recipe.write_text('#!/bin/bash\nif [ "$1" = clean ]; then\n'
                               '  exit 47\nfi\ntouch bad-success\n')
        result = self.run_build('--clean')
        self.assertEqual(result.returncode, 47, result.stdout + result.stderr)
        self.assertFalse((self.dep / 'bad-success').exists())


if __name__ == '__main__':
    unittest.main()
