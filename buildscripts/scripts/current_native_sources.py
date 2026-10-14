#!/usr/bin/env python3
"""Capture one current native source vector; detect drift before/after builds."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

SOURCES = {
    'ffmpeg': ('https://github.com/Goodwu/FFmpeg.git', 'routing/MK-ROUTING-20261011', 'ROUTING_FFMPEG_SHA'),
    'mpv': ('https://github.com/Goodwu/mpv.git', 'media-kit/android', 'ROUTING_MPV_SHA'),
    'libplacebo': ('https://github.com/Goodwu/libplacebo.git', 'optimize/dovi-linear-decode', 'ROUTING_LIBPLACEBO_SHA'),
    'media-kit-android-helper': ('https://github.com/Predidit/media-kit-android-helper.git', 'main', 'ROUTING_HELPER_SHA'),
}
HEX = re.compile(r'[0-9a-f]{40}\Z')


def command(argv):
    value = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    if value.returncode:
        raise ValueError(f'command failed ({value.returncode}): {argv}: {value.stderr}')
    return value.stdout


def remote_tip(url, branch):
    ref = 'refs/heads/' + branch
    rows = command(['git', 'ls-remote', '--exit-code', url, ref]).strip().splitlines()
    if len(rows) != 1:
        raise ValueError(f'missing or ambiguous remote ref: {url} {ref}')
    pair = rows[0].split()
    if len(pair) != 2 or not HEX.fullmatch(pair[0]) or pair[1] != ref:
        raise ValueError('remote response does not identify the requested branch')
    return pair[0]


def validate(vector):
    if not isinstance(vector, dict) or set(vector) != set(SOURCES):
        raise ValueError('source vector must contain exactly four registered components')
    for name, (url, branch, _) in SOURCES.items():
        row = vector[name]
        if not isinstance(row, dict) or set(row) != {'repository', 'branch', 'commit'} or row['repository'] != url or row['branch'] != branch or not isinstance(row['commit'], str) or not HEX.fullmatch(row['commit']):
            raise ValueError(f'invalid source identity for {name}')
    return vector


def capture():
    return {name: {'repository': url, 'branch': branch, 'commit': remote_tip(url, branch)}
            for name, (url, branch, _) in SOURCES.items()}


def exports(vector):
    validate(vector)
    return ''.join(f"export {variable}={vector[name]['commit']}\n" for name, (_, _, variable) in SOURCES.items())


def check(vector, deps):
    validate(vector)
    result = {}
    for name, (url, branch, _) in SOURCES.items():
        root = (Path(deps) / name).resolve(strict=True)
        actual_root = Path(command(['git', '-C', str(root), 'rev-parse', '--show-toplevel']).strip()).resolve()
        actual = command(['git', '-C', str(root), 'rev-parse', 'HEAD']).strip()
        if actual_root != root or actual != vector[name]['commit']:
            raise ValueError(f'checkout does not match captured current source: {name}')
        if remote_tip(url, branch) != actual:
            raise ValueError(f'remote source advanced during this build: {name}')
        origin = command(['git', '-C', str(root), 'remote', 'get-url', 'origin']).strip()
        if origin != url:
            raise ValueError(f'checkout origin differs from registered source: {name}')
        submodules = command(['git', '-C', str(root), 'submodule', 'status', '--recursive'])
        if any(line and not line.startswith(' ') for line in submodules.splitlines()):
            raise ValueError(f'uninitialized or changed submodule: {name}')
        tree = command(['git', '-C', str(root), 'rev-parse', 'HEAD^{tree}']).strip()
        if not HEX.fullmatch(tree):
            raise ValueError('invalid source tree')
        diff = command(['git', '-C', str(root), 'diff', '--binary', '--no-ext-diff', '--no-textconv', 'HEAD', '--'])
        result[name] = dict(vector[name], tree=tree, submodules=submodules, trackedDiff=diff,
                            trackedDiffSha256=hashlib.sha256(diff.encode()).hexdigest())
    return {'status': 'current-source-checked', 'components': result}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('capture', 'exports', 'check'))
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--deps', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'capture':
            value = capture()
        else:
            if args.input is None:
                raise ValueError('an explicit captured input is required')
            vector = json.loads(args.input.read_text())
            if args.action == 'exports':
                print(exports(vector), end='')
                raise SystemExit(0)
            if args.deps is None:
                raise ValueError('an explicit dependency checkout root is required')
            value = check(vector, args.deps)
        if args.output is None:
            raise ValueError('an explicit new evidence output is required')
        with args.output.open('x') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Current native sources rejected: {error}\n')
