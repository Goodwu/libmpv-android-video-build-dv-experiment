#!/usr/bin/env python3
"""Collect a four-ABI runtime and development SDK candidate after a source build.

The shared media-kit packager creates the final manifest from root/ and spec.json.
This producer never assigns runtime/device acceptance to a successful compiler.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile

import package_native
import current_native_sources

ABIS = {
    'arm64-v8a': (2, 183, '-arm64'),
    'armeabi-v7a': (1, 40, ''),
    'x86': (1, 3, '-x86'),
    'x86_64': (2, 62, '-x64'),
}
FEATURES = {
    'HAVE_PL_EXTERNAL_YUV': 'mpv.pl-external-yuv',
    'HAVE_PL_DOVI_LINEAR_OPTIMIZE': 'mpv.pl-dovi-linear-optimize',
    'HAVE_PL_DOVI_LINEAR_DISABLE': 'mpv.pl-dovi-linear-disable',
    'HAVE_LAVF_INITIAL_DOVI_HVCC': 'mpv.lavf-initial-dovi-hvcc',
}
SOURCE_DEPS = ('mbedtls', 'dav1d', 'libxml2', 'ffmpeg', 'freetype', 'fribidi',
               'harfbuzz', 'libass', 'lcms2', 'libplacebo', 'mpv',
               'media-kit-android-helper')
HEX40 = re.compile(r'[0-9a-f]{40}\Z')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(package_native.regular(path))


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True, timeout=60).stdout.strip()


def elf_header(data, abi, label):
    expected_class, expected_machine, _ = ABIS[abi]
    if len(data) < 20 or data[:4] != b'\x7fELF' or data[5:7] != b'\x01\x01':
        raise ValueError(f'not a supported little-endian ELF: {label}')
    if data[4] != expected_class or struct.unpack_from('<H', data, 18)[0] != expected_machine:
        raise ValueError(f'ELF ABI differs from {abi}: {label}')


def archive_objects(path, abi):
    """Validate actual archive members, including GNU/BSD extended names."""
    count = 0
    with path.open('rb') as stream:
        if stream.read(8) != b'!<arch>\n':
            raise ValueError(f'unsupported or thin static archive: {path}')
        total = path.stat().st_size
        while stream.tell() < total:
            header = stream.read(60)
            if len(header) != 60 or header[58:] != b'`\n':
                raise ValueError(f'invalid archive member header: {path}')
            name = header[:16].decode('ascii').strip()
            size = int(header[48:58].decode('ascii').strip())
            start = stream.tell()
            end = start + size
            if size < 0 or end > total:
                raise ValueError(f'truncated archive member: {path}')
            if name not in ('/', '//', '/SYM64/') and not name.startswith('__.SYMDEF'):
                if name.startswith('#1/'):
                    length = int(name[3:])
                    if not 0 <= length <= size:
                        raise ValueError(f'invalid BSD archive name: {path}')
                    name = stream.read(length).rstrip(b'\x00').decode('utf-8')
                if not name.startswith('__.SYMDEF'):
                    elf_header(stream.read(min(64, end - stream.tell())), abi,
                               f'{path.name}({name})')
                    count += 1
            stream.seek(end + size % 2)
        if stream.tell() != total or not count:
            raise ValueError(f'empty or misaligned static archive: {path}')
    return count


def copy_sdk(source, destination, abi, runtime_members, build_root):
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f'missing real SDK prefix: {source}')
    source = source.resolve()
    shutil.copytree(source, destination, symlinks=True)
    # The build prefix uses usr -> . and local -> . to flatten /usr/local.
    # Replace these recursive aliases with an acyclic virtual sysroot layout.
    for name in ('usr', 'local'):
        path = destination / name
        if path.is_symlink() and (source / name).resolve(strict=True) == source:
            path.unlink()
    # Rebase internal absolute links, and refuse anything outside this prefix.
    for path in sorted(destination.rglob('*')):
        if path.is_symlink():
            original = source / path.relative_to(destination)
            try:
                relative = original.resolve(strict=True).relative_to(source)
            except (OSError, RuntimeError, ValueError) as error:
                raise ValueError(f'SDK symlink escapes its prefix: {original}') from error
            path.unlink()
            path.symlink_to(os.path.relpath(destination / relative, path.parent))
    for virtual in (destination / 'usr', destination / 'usr/local'):
        virtual.mkdir(parents=True, exist_ok=True)
        for name in ('include', 'lib', 'bin', 'share'):
            target = destination / name
            if target.is_dir() and not (virtual / name).exists():
                (virtual / name).symlink_to(os.path.relpath(target, virtual))

    required = ('include/mpv/client.h', 'include/libavformat/avformat.h',
                'include/libplacebo/opengl.h', 'lib/pkgconfig/mpv.pc',
                'lib/pkgconfig/libavformat.pc', 'lib/pkgconfig/libplacebo.pc',
                'lib/libavformat.a', 'lib/libavcodec.a', 'lib/libavutil.a',
                'lib/libplacebo.a', 'lib/libmpv.so')
    for relative in required:
        if not (destination / relative).is_file():
            raise ValueError(f'development SDK is incomplete: {abi}/{relative}')

    # Link against exactly the runtime libmpv (including its recorded private
    # Vulkan import transformation), not the pre-packaging prefix binary.
    for name, data in runtime_members.items():
        path = destination / 'lib' / name
        resolved = path.resolve()
        if not resolved.is_relative_to(destination.resolve()):
            raise ValueError(f'SDK library resolves outside the package: {path}')
        resolved.write_bytes(data)

    counts = {'staticArchives': 0, 'archiveObjects': 0, 'elfFiles': 0}
    for path in sorted(destination.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix == '.a':
            counts['archiveObjects'] += archive_objects(path, abi)
            counts['staticArchives'] += 1
        else:
            with path.open('rb') as stream:
                header = stream.read(64)
            if header.startswith(b'\x7fELF'):
                elf_header(header, abi, str(path))
                counts['elfFiles'] += 1
        if path.suffix in ('.pc', '.la', '.cmake') or path.name == 'crossfile.txt':
            text = path.read_text()
            if str(build_root.resolve()) in text or str(source) in text:
                raise ValueError(f'SDK metadata retains a build-machine prefix: {path}')
            if path.suffix == '.pc':
                # /usr and /usr/local are virtual paths resolved by the SDK's
                # PKG_CONFIG_SYSROOT_DIR; arbitrary host absolute paths are not.
                absolute = re.findall(r'(?:^|[=\s]|-[IL])(/[^\s;]*)', text)
                if any(not (value == '/usr' or value.startswith('/usr/')) for value in absolute):
                    raise ValueError(f'non-relocatable pkg-config path: {path}')
    return counts


def read_runtime(root, abi):
    folder = root / 'routing-native-output' / abi
    jar = folder / f'default-{abi}.jar'
    receipt = read_json(folder / 'packaging.json')
    if receipt.get('abi') != abi or sha256(package_native.regular(jar)) != receipt.get('jarSha256'):
        raise ValueError(f'JAR identity differs from packaging receipt: {abi}')
    names = {f'lib/{abi}/{name}' for name in package_native.NAMES}
    if set(receipt.get('members', {})) != names:
        raise ValueError(f'packaging receipt has a different native member set: {abi}')
    result = {}
    with zipfile.ZipFile(jar) as archive:
        if len(archive.infolist()) != 3 or set(archive.namelist()) != names:
            raise ValueError(f'JAR must have exactly the three selected ABI members: {abi}')
        for name in sorted(names):
            data = archive.read(name)
            if sha256(data) != receipt['members'][name]['sha256']:
                raise ValueError(f'JAR member differs from packaging receipt: {name}')
            elf_header(data, abi, name)
            result[Path(name).name] = data
    return jar, result


def compiled_features(root, abi):
    config = root / 'deps/mpv' / ('_build' + ABIS[abi][2]) / 'config.h'
    text = package_native.regular(config).decode()
    result = {}
    for macro in FEATURES:
        values = re.findall(r'^#define\s+' + macro + r'\s+([01])\s*$', text, re.MULTILINE)
        if len(values) != 1:
            raise ValueError(f'missing or ambiguous compiled feature {macro}: {abi}')
        result[macro] = values[0] == '1'
    return result, sha256(text.encode())


def source_identity(root, evidence):
    vector = read_json(root / 'routing-native-evidence/source-vector.json')
    receipt = read_json(root / 'routing-native-evidence/source-after-build.json')
    if receipt.get('status') not in ('current-source-checked', 'locked-source-checked'):
        raise ValueError('missing successful source verification after the build')
    current_native_sources.validate(vector, locked=receipt['status'] == 'locked-source-checked')
    after = receipt['components']
    if set(after) != set(vector):
        raise ValueError('source verification does not cover the complete captured vector')
    records = {}
    (evidence / 'source-diffs').mkdir()
    for name in SOURCE_DEPS:
        source = root / 'deps' / name
        if Path(git(source, 'rev-parse', '--show-toplevel')).resolve() != source.resolve():
            raise ValueError(f'dependency is not its own source checkout: {name}')
        commit = git(source, 'rev-parse', 'HEAD')
        tree = git(source, 'rev-parse', 'HEAD^{tree}')
        repository = git(source, 'remote', 'get-url', 'origin')
        if not HEX40.fullmatch(commit) or not HEX40.fullmatch(tree):
            raise ValueError(f'invalid source identity: {name}')
        diff = subprocess.run(['git', '-C', str(source), 'diff', '--binary',
                               '--no-ext-diff', '--no-textconv', 'HEAD', '--'],
                              check=True, capture_output=True, timeout=60).stdout
        submodules = git(source, 'submodule', 'status', '--recursive')
        if any(line.startswith(('-', '+', 'U')) for line in submodules.splitlines()):
            raise ValueError(f'uninitialized or changed source submodule: {name}')
        records[name] = {'repository': repository, 'commit': commit, 'tree': tree,
                         'tracked_diff_sha256': sha256(diff), 'submodules': submodules}
        if name in vector:
            if commit != vector[name]['commit'] or repository != vector[name]['repository']:
                raise ValueError(f'source no longer matches the captured vector: {name}')
            if tree != after[name]['tree'] or sha256(diff) != after[name]['trackedDiffSha256']:
                raise ValueError(f'source changed after the completed build: {name}')
        (evidence / 'source-diffs' / (name + '.patch')).write_bytes(diff)
    return records


def collect(root, output, *, android_api, profile):
    root, output = Path(root).resolve(), Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('output already exists: a fresh package destination is required')
    evidence = root / 'routing-native-evidence'
    if (evidence / 'exit-code.txt').read_text().strip() != '0':
        raise ValueError('the native source build did not complete successfully')
    recipe_commit = (evidence / 'recipe-commit.txt').read_text().strip()
    recipe_tree = (evidence / 'recipe-tree.txt').read_text().strip()
    if git(root, 'rev-parse', 'HEAD') != recipe_commit or git(root, 'rev-parse', 'HEAD^{tree}') != recipe_tree:
        raise ValueError('recipe differs from the completed build')
    git(root, 'diff', '--exit-code')
    git(root, 'diff', '--cached', '--exit-code')
    if not 21 <= android_api <= 100:
        raise ValueError('invalid Android native API level')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-bundle-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'package'
        payload = stage / 'root'
        (payload / 'runtime').mkdir(parents=True)
        (payload / 'sdk').mkdir()
        shutil.copytree(evidence, payload / 'evidence', symlinks=True)
        if any(p.is_symlink() for p in (payload / 'evidence').rglob('*')):
            raise ValueError('producer evidence must not contain symlinks')
        sources = source_identity(root, payload / 'evidence')
        features, config_hashes, sdk_checks, jars, prefixes = {}, {}, {}, {}, {}
        for abi in ABIS:
            jar, members = read_runtime(root, abi)
            jars[abi] = f'runtime/{jar.name}'
            shutil.copyfile(jar, payload / jars[abi])
            prefixes[abi] = f'sdk/{abi}'
            sdk_checks[abi] = copy_sdk(root / 'prefix' / abi, payload / prefixes[abi],
                                       abi, members, root)
            features[abi], config_hashes[abi] = compiled_features(root, abi)
        baseline = features[next(iter(ABIS))]
        if any(value != baseline for value in features.values()):
            raise ValueError('custom compiled capabilities differ across Android ABIs')
        if (not baseline['HAVE_PL_EXTERNAL_YUV'] or not baseline['HAVE_LAVF_INITIAL_DOVI_HVCC']
                or not (baseline['HAVE_PL_DOVI_LINEAR_OPTIMIZE'] or baseline['HAVE_PL_DOVI_LINEAR_DISABLE'])):
            raise ValueError('this custom Android DV profile requires the fork APIs')
        (payload / 'evidence/sdk-checks.json').write_text(json.dumps(sdk_checks, indent=2, sort_keys=True) + '\n')
        (payload / 'evidence/compiled-features.json').write_text(json.dumps(features, indent=2, sort_keys=True) + '\n')
        ndk = (evidence / 'ndk-source.properties').read_text()
        revisions = re.findall(r'^Pkg.Revision\s*=\s*(\S+)\s*$', ndk, re.MULTILINE)
        if len(revisions) != 1:
            raise ValueError('NDK revision is missing or ambiguous')
        compiler_files = {}
        for line in (evidence / 'toolchain-files.sha256').read_text().splitlines():
            match = re.fullmatch(r'([0-9a-f]{64}) [ *](.+)', line)
            if not match or Path(match[2]).name in compiler_files:
                raise ValueError('invalid or ambiguous toolchain file identity')
            compiler_files[Path(match[2]).name] = match[1]
        spec = {
            'schema': 1, 'kind': 'media-kit-native-package', 'platform': 'android',
            'architectures': list(ABIS), 'profile': profile,
            'identity': {
                'origin': 'source', 'sources': sources,
                'recipe': {'repository': 'https://github.com/Goodwu/libmpv-android-video-build-dv-experiment.git',
                           'commit': recipe_commit, 'tree': recipe_tree},
                'toolchain': {'ndk': revisions[0], 'ndk_source_properties_sha256': sha256(ndk.encode()),
                              'compiler': (evidence / 'compiler-version.txt').read_text().strip(),
                              'compiler_files': compiler_files,
                              'shaderc_source': 'selected-ndk/sources/third_party/shaderc'},
                'options': {'artifact_types': ['runtime', 'development-sdk'], 'flavor': 'default',
                            'android_api': android_api, 'stl': 'c++_shared',
                            'mpv_config_sha256': config_hashes, 'sdk_libmpv': 'packaged-runtime'},
                'patches': {str(p.relative_to(root)): sha256(p.read_bytes())
                            for p in sorted((root / 'patches').rglob('*.patch'))},
            },
            'layout': {'jars': jars, 'sdk_prefixes': prefixes},
            'capabilities': sorted(FEATURES[key] for key, enabled in baseline.items() if enabled),
            'validation': {'compiled': True, 'runtime': False, 'device': False},
        }
        (stage / 'spec.json').write_text(json.dumps(spec, indent=2, sort_keys=True) + '\n')
        (stage / 'README.txt').write_text(
            'Unreviewed source-built candidate; run the shared media-kit packager:\n'
            'python tool/native_package/package.py create --root "$PWD/root" --spec "$PWD/spec.json"\n'
            'Use the resulting manifest hash to verify this package before consumption.\n'
            'runtime/ contains Android JARs; sdk/<abi>/ is a separate development sysroot.\n'
            'For pkg-config set PKG_CONFIG_SYSROOT_DIR=<absolute sdk/<abi>> and\n'
            'PKG_CONFIG_LIBDIR=<absolute sdk/<abi>/lib/pkgconfig>; unset PKG_CONFIG_PATH.\n'
            'Use the recorded NDK/API/STL and its cross compiler. Runtime/device testing is pending.\n')
        os.rename(stage, output)
    return spec


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--android-api', required=True, type=int)
    parser.add_argument('--profile', default='goodwu-android-dv')
    args = parser.parse_args()
    try:
        result = collect(args.build_root, args.output, android_api=args.android_api, profile=args.profile)
        print(json.dumps({'status': 'packaged-unreviewed', 'output': str(args.output),
                          'architectures': result['architectures']}))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        parser.exit(1, f'Native bundle rejected: {error}\n')
