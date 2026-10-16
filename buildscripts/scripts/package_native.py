#!/usr/bin/env python3
"""Package exactly three current build outputs; emit evidence, never approval."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import zipfile

import weaken_undefined_imports as elf

NAMES = ('libmpv.so', 'libmediakitandroidhelper.so', 'libc++_shared.so')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= elf.MAX_FILE:
        raise ValueError(f'missing, symbolic or oversized input: {path}')
    return path.read_bytes()


def tool(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    if result.returncode or result.stderr.strip():
        raise ValueError(f'ELF tool failed ({result.returncode}): {argv}: {result.stderr}')
    return result.stdout


def facts(path, abi, readelf, nm):
    data = regular(path)
    parsed = elf.inspect(data, abi)
    # Both tools must execute successfully; their failures never mean no imports.
    headers = tool([str(readelf), '--file-header', '--dynamic', '--notes', '--wide', str(path)])
    dynamic = tool([str(readelf), '--dyn-syms', '--wide', str(path)])
    undefined = tool([str(nm), '-D', '--undefined-only', str(path)])
    sonames = re.findall(r'\(SONAME\).*?\[([^\]]+)\]', headers)
    build_ids = re.findall(r'Build ID:\s*([0-9a-f]+)', headers)
    needed = re.findall(r'\(NEEDED\).*?\[([^\]]+)\]', headers)
    if sonames != [path.name] or len(build_ids) != 1 or not needed or len(set(needed)) != len(needed):
        raise ValueError(f'ELF identity missing/ambiguous for {path.name}')
    targets = set(elf.VULKAN_1_1_MISSING_BEFORE_API_28)
    strong = [s['name'] for s in parsed['symbols'] if s['name'] in targets and s['section'] == 0 and s['binding'] != 2]
    if strong:
        raise ValueError(f'strong Vulkan imports remain: {strong}')
    weak = sorted({s['name'] for s in parsed['symbols'] if s['name'] in targets and s['section'] == 0 and s['binding'] == 2})
    return ({'sha256': digest(data), 'buildId': build_ids[0], 'soname': sonames[0], 'needed': needed,
             'elfClass': parsed['elfClass'], 'machine': parsed['machine']},
            {'readelf': headers + dynamic, 'nm': undefined, 'weakVulkanImports': weak})


def package(mpv, helper_apk, libcxx, output, *, abi, readelf, nm):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('output already exists: a fresh destination is required')
    mpv, helper_apk, libcxx = map(Path, (mpv, helper_apk, libcxx))
    inputs = {NAMES[0]: regular(mpv), NAMES[2]: regular(libcxx)}
    apk_bytes = regular(helper_apk)
    wanted = f'lib/{abi}/{NAMES[1]}'
    with zipfile.ZipFile(helper_apk) as archive:
        matches = [item for item in archive.infolist() if item.filename == wanted]
        if len(matches) != 1:
            raise ValueError('helper APK must contain exactly one selected helper member')
        item = matches[0]
        if item.is_dir() or item.orig_filename != item.filename or stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1 or not 0 < item.file_size <= elf.MAX_FILE:
            raise ValueError('invalid helper APK member')
        inputs[NAMES[1]] = archive.read(item)  # CRC errors propagate.
    receipt = {'schemaVersion': 1, 'status': 'packaged-unreviewed', 'abi': abi,
               'nativeVerified': False, 'deviceVerified': False, 'members': {}, 'tools': {},
               'inputs': {NAMES[0]: {'path': str(mpv), 'sha256': digest(inputs[NAMES[0]])},
                          NAMES[1]: {'apk': str(helper_apk), 'apkSha256': digest(apk_bytes), 'member': wanted,
                                     'sha256': digest(inputs[NAMES[1]])},
                          NAMES[2]: {'path': str(libcxx), 'sha256': digest(inputs[NAMES[2]])}}}
    with tempfile.TemporaryDirectory(prefix='.native-package-', dir=output.parent) as temp:
        stage = Path(temp)
        members = stage / 'members'
        members.mkdir()
        for name in NAMES:
            (members / name).write_bytes(inputs[name])
        receipt['vulkanMutation'] = elf.main(members / NAMES[0], abi=abi)
        for name in NAMES:
            key = f'lib/{abi}/{name}'
            receipt['members'][key], receipt['tools'][key] = facts(members / name, abi, readelf, nm)
        ready = stage / 'ready'
        ready.mkdir()
        jar = ready / f'default-{abi}.jar'
        with zipfile.ZipFile(jar, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name in NAMES:
                info = zipfile.ZipInfo(f'lib/{abi}/{name}', (2025, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, (members / name).read_bytes())
        with zipfile.ZipFile(jar) as archive:
            if set(archive.namelist()) != set(receipt['members']) or len(archive.infolist()) != 3:
                raise ValueError('packaged JAR member set changed')
            for name, expected in receipt['members'].items():
                if digest(archive.read(name)) != expected['sha256']:
                    raise ValueError('packaged JAR bytes changed')
        if regular(mpv) != inputs[NAMES[0]] or regular(libcxx) != inputs[NAMES[2]] or regular(helper_apk) != apk_bytes:
            raise ValueError('build input changed while packaging')
        receipt['jarSha256'] = digest(jar.read_bytes())
        (ready / 'packaging.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        # Reserve a fresh output; no zip update or old native member reuse.
        output.mkdir()
        try:
            for file in ready.iterdir():
                os.link(file, output / file.name)
        except BaseException:
            for name in (jar.name, 'packaging.json'):
                (output / name).unlink(missing_ok=True)
            output.rmdir()
            raise
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('mpv', 'helper-apk', 'libcxx', 'output', 'readelf', 'nm'):
        parser.add_argument('--' + argument, required=True, type=Path)
    parser.add_argument('--abi', required=True, choices=elf.ABIS)
    args = parser.parse_args()
    try:
        receipt = package(args.mpv, args.helper_apk, args.libcxx, args.output,
                          abi=args.abi, readelf=args.readelf, nm=args.nm)
        print(json.dumps({'status': receipt['status'], 'jarSha256': receipt['jarSha256']}))
    except (OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        parser.exit(1, f'Native package rejected: {error}\n')
