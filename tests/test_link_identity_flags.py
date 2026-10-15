"""The recipe must request an explicit ELF build-id for member identity."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LinkIdentityFlagTests(unittest.TestCase):
    def test_build_sh_requests_a_build_id(self):
        # The member packaging gate rejects any ELF without exactly one GNU
        # build-id note, and the NDK lld default emits none (verified on
        # NDK r27c: a trivial -shared link has zero Build ID notes). The
        # recipe therefore must carry the explicit flag; losing it again
        # reproduces the "ELF identity missing/ambiguous" packaging
        # rejection after a full toolchain rebuild.
        source = (ROOT / 'buildscripts/build.sh').read_text()
        self.assertIn('-Wl,--build-id=sha1', source)
        ldflags_lines = [line for line in source.splitlines()
                         if 'export LDFLAGS=' in line]
        self.assertEqual(len(ldflags_lines), 1, ldflags_lines)
        self.assertIn('-Wl,--build-id=sha1', ldflags_lines[0])


if __name__ == '__main__':
    unittest.main()
