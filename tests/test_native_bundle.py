"""Real four-ABI ELF/archive fixtures for complete native-package collection."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'buildscripts/scripts'))
import package_native_bundle as bundle


class NativeBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture.cleanup)
        cls.base = Path(cls.fixture.name)
        if not shutil.which('clang') or not shutil.which('ld.lld'):
            raise RuntimeError('real clang/LLD fixture tools are required')
        cls.binary = {}
        triples = {'arm64-v8a': 'aarch64-linux-gnu', 'armeabi-v7a': 'armv7a-linux-gnueabi',
                   'x86': 'i686-linux-gnu', 'x86_64': 'x86_64-linux-gnu'}
        source = cls.base / 'fixture.c'
        source.write_text('int native_fixture(void) { return 7; }\n')
        for abi, triple in triples.items():
            folder = cls.base / abi
            folder.mkdir()
            obj = folder / 'long_native_fixture_object_name.o'
            subprocess.run(['clang', '--target=' + triple, '-fPIC', '-c', str(source), '-o', str(obj)],
                           check=True, capture_output=True)
            library = folder / 'libfixture.so'
            subprocess.run(['clang', '--target=' + triple, '-fuse-ld=lld', '-nostdlib', '-shared',
                            '-Wl,--build-id', '-Wl,-soname,libfixture.so', str(obj), '-o', str(library)],
                           check=True, capture_output=True)
            archive = folder / 'libfixture.a'
            subprocess.run(['ar', 'rcs', str(archive), str(obj)], check=True, capture_output=True)
            cls.binary[abi] = (library.read_bytes(), archive.read_bytes())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'buildscripts'
        self.root.mkdir()
        self.output = self.root.parent / 'package'
        self.init_git(self.root, 'recipe')
        evidence = self.root / 'routing-native-evidence'
        evidence.mkdir()
        for name, text in {
            'exit-code.txt': '0\n', 'recipe-commit.txt': bundle.git(self.root, 'rev-parse', 'HEAD'),
            'recipe-tree.txt': bundle.git(self.root, 'rev-parse', 'HEAD^{tree}'),
            'ndk-source.properties': 'Pkg.Revision = 27.2.12479018\n',
            'compiler-version.txt': 'fixture clang\n',
            'toolchain-files.sha256': '1' * 64 + '  /fixture/clang\n',
        }.items():
            (evidence / name).write_text(text)
        vector, after = {}, {}
        for name in bundle.SOURCE_DEPS:
            source = self.root / 'deps' / name
            source.mkdir(parents=True)
            self.init_git(source, name)
            if name in bundle.current_native_sources.SOURCES:
                repository, branch, _ = bundle.current_native_sources.SOURCES[name]
                subprocess.run(['git', '-C', str(source), 'remote', 'set-url', 'origin', repository], check=True)
                record = {'repository': repository, 'branch': branch,
                          'commit': bundle.git(source, 'rev-parse', 'HEAD')}
                vector[name] = record
                after[name] = dict(record, tree=bundle.git(source, 'rev-parse', 'HEAD^{tree}'),
                                   trackedDiffSha256=hashlib.sha256(b'').hexdigest())
        (evidence / 'source-vector.json').write_text(json.dumps(vector))
        (evidence / 'source-after-build.json').write_text(json.dumps({'status': 'current-source-checked', 'components': after}))
        for abi, (_, _, suffix) in bundle.ABIS.items():
            native, static = self.binary[abi]
            output = self.root / 'routing-native-output' / abi
            output.mkdir(parents=True)
            receipt = {'abi': abi, 'members': {}}
            jar = output / f'default-{abi}.jar'
            with zipfile.ZipFile(jar, 'w') as archive:
                for name in bundle.package_native.NAMES:
                    key = f'lib/{abi}/{name}'
                    archive.writestr(key, native)
                    receipt['members'][key] = {'sha256': bundle.sha256(native)}
            receipt['jarSha256'] = bundle.sha256(jar.read_bytes())
            (output / 'packaging.json').write_text(json.dumps(receipt))
            prefix = self.root / 'prefix' / abi
            for header in ('mpv/client.h', 'libavformat/avformat.h', 'libplacebo/opengl.h'):
                path = prefix / 'include' / header
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('int native_fixture(void);\n')
            pc = prefix / 'lib/pkgconfig'
            pc.mkdir(parents=True)
            for name in ('mpv', 'libavformat', 'libplacebo'):
                (pc / (name + '.pc')).write_text(
                    'prefix=/usr/local\nlibdir=${prefix}/lib\nName: fixture\n'
                    'Description: native SDK test\nVersion: 1\n'
                    'Libs: -L${libdir} -lavformat\nCflags: -I${prefix}/include\n')
            for name in ('avformat', 'avcodec', 'avutil', 'placebo'):
                (prefix / 'lib' / ('lib' + name + '.a')).write_bytes(static)
            (prefix / 'lib/libmpv.so').write_bytes(native)
            (prefix / 'usr').symlink_to('.')
            (prefix / 'local').symlink_to('.')
            # An absolute internal link must become relative in the artifact.
            (prefix / 'lib/libalias.a').symlink_to(prefix / 'lib/libplacebo.a')
            config = self.root / 'deps/mpv' / ('_build' + suffix) / 'config.h'
            config.parent.mkdir()
            config.write_text(''.join('#define ' + macro + ' ' +
                ('0' if macro == 'HAVE_PL_DOVI_LINEAR_OPTIMIZE' else '1') + '\n'
                for macro in bundle.FEATURES))

    def init_git(self, folder, name):
        subprocess.run(['git', 'init', '-q', str(folder)], check=True, capture_output=True)
        (folder / 'source.txt').write_text(name)
        subprocess.run(['git', '-C', str(folder), 'add', 'source.txt'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(folder), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'],
                       check=True, capture_output=True)
        subprocess.run(['git', '-C', str(folder), 'remote', 'add', 'origin',
                        'https://example.invalid/' + name + '.git'], check=True, capture_output=True)

    def collect(self):
        return bundle.collect(self.root, self.output, android_api=26, profile='fixture')

    def test_complete_four_abi_sdk_and_runtime_remain_unreviewed(self):
        spec = self.collect()
        self.assertEqual(set(spec['architectures']), set(bundle.ABIS))
        self.assertEqual(spec['validation'], {'compiled': True, 'runtime': False, 'device': False})
        self.assertEqual(set(spec['identity']['sources']), set(bundle.SOURCE_DEPS))
        self.assertTrue((self.output / 'spec.json').is_file())
        self.assertFalse((self.output / 'root/spec.json').exists())
        for abi in bundle.ABIS:
            sdk = self.output / 'root' / spec['layout']['sdk_prefixes'][abi]
            self.assertEqual((sdk / 'lib/libmpv.so').read_bytes(), self.binary[abi][0])
            self.assertEqual((sdk / 'lib/libalias.a').readlink(), Path('libplacebo.a'))
            self.assertFalse((sdk / 'usr').is_symlink())
            self.assertEqual((sdk / 'usr/local/include').readlink(), Path('../../include'))
            self.assertTrue((sdk / 'usr/local/include/mpv/client.h').is_file())

    def test_wrong_abi_in_static_dependency_is_rejected_before_publication(self):
        (self.root / 'prefix/arm64-v8a/lib/libplacebo.a').write_bytes(self.binary['x86'][1])
        with self.assertRaisesRegex(ValueError, 'ABI differs'):
            self.collect()
        self.assertFalse(self.output.exists())

    def test_relocated_sdk_compiles_and_links_a_consumer_for_every_abi(self):
        self.collect()
        moved = self.root.parent / 'relocated-sdk-package'
        self.output.rename(moved)
        consumer = self.root.parent / 'consumer.c'
        consumer.write_text('#include <libavformat/avformat.h>\n'
                            'int use_sdk(void) { return native_fixture(); }\n')
        triples = {'arm64-v8a': 'aarch64-linux-gnu', 'armeabi-v7a': 'armv7a-linux-gnueabi',
                   'x86': 'i686-linux-gnu', 'x86_64': 'x86_64-linux-gnu'}
        for abi, triple in triples.items():
            with self.subTest(abi=abi):
                sdk = moved / 'root/sdk' / abi
                env = dict(os.environ, PKG_CONFIG_SYSROOT_DIR=str(sdk),
                           PKG_CONFIG_LIBDIR=str(sdk / 'lib/pkgconfig'))
                env.pop('PKG_CONFIG_PATH', None)
                flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', '--static',
                                                 'libavformat'], env=env, text=True)
                result = self.root.parent / (abi + '-consumer.so')
                subprocess.run(['clang', '--target=' + triple, '-fuse-ld=lld', '-nostdlib',
                                '-shared', '-fPIC', '-Wl,--no-undefined', str(consumer),
                                *shlex.split(flags), '-o', str(result)], check=True, capture_output=True)
                bundle.elf_header(result.read_bytes(), abi, str(result))

    def test_external_sdk_link_is_rejected_before_publication(self):
        (self.root / 'prefix/x86/lib/external.a').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'symlink escapes'):
            self.collect()
        self.assertFalse(self.output.exists())

    def test_pkgconfig_with_runner_prefix_is_not_a_relocatable_sdk(self):
        (self.root / 'prefix/x86/lib/pkgconfig/mpv.pc').write_text('prefix=/home/runner/work/native\n')
        with self.assertRaisesRegex(ValueError, 'non-relocatable'):
            self.collect()
        self.assertFalse(self.output.exists())

    def test_missing_development_header_is_rejected(self):
        (self.root / 'prefix/x86_64/include/mpv/client.h').unlink()
        with self.assertRaisesRegex(ValueError, 'SDK is incomplete'):
            self.collect()

    def test_different_fork_capability_between_abis_is_rejected(self):
        config = self.root / 'deps/mpv/_build-x86/config.h'
        config.write_text(config.read_text().replace('HAVE_PL_EXTERNAL_YUV 1', 'HAVE_PL_EXTERNAL_YUV 0'))
        with self.assertRaisesRegex(ValueError, 'capabilities differ'):
            self.collect()

    def test_modified_jar_is_rejected_even_when_elf_still_loadable(self):
        jar = self.root / 'routing-native-output/x86/default-x86.jar'
        with zipfile.ZipFile(jar, 'a') as archive:
            archive.writestr('extra.txt', 'different package')
        with self.assertRaisesRegex(ValueError, 'JAR identity'):
            self.collect()

    def test_source_change_after_build_is_rejected(self):
        (self.root / 'deps/mpv/source.txt').write_text('new unbuilt code')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.collect()

    def test_existing_output_is_not_overwritten(self):
        self.output.mkdir()
        old = self.output / 'keep'
        old.write_text('previous package')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.collect()
        self.assertEqual(old.read_text(), 'previous package')


if __name__ == '__main__':
    unittest.main()
