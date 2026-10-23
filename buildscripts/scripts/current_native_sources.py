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


def validate(vector, *, locked=False):
    if not isinstance(vector, dict) or set(vector) != set(SOURCES):
        raise ValueError('source vector must contain exactly four registered components')
    for name, (url, branch, _) in SOURCES.items():
        row = vector[name]
        if not isinstance(row, dict) or set(row) != {'repository', 'branch', 'commit'} or row['repository'] != url or not isinstance(row['commit'], str) or not HEX.fullmatch(row['commit']):
            raise ValueError(f'invalid source identity for {name}')
        label = row['branch']
        if (not isinstance(label, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', label)
                or '..' in label or '//' in label or label.endswith(('/', '.'))
                or (not locked and label != branch)):
            raise ValueError(f'invalid source branch for {name}')
    return vector


def capture():
    return {name: {'repository': url, 'branch': branch, 'commit': remote_tip(url, branch)}
            for name, (url, branch, _) in SOURCES.items()}


def exports(vector, *, locked=False):
    validate(vector, locked=locked)
    return ''.join(f"export {variable}={vector[name]['commit']}\n" for name, (_, _, variable) in SOURCES.items())


def check(vector, deps, *, locked=False):
    validate(vector, locked=locked)
    result = {}
    for name, (url, branch, _) in SOURCES.items():
        root = (Path(deps) / name).resolve(strict=True)
        actual_root = Path(command(['git', '-C', str(root), 'rev-parse', '--show-toplevel']).strip()).resolve()
        actual = command(['git', '-C', str(root), 'rev-parse', 'HEAD']).strip()
        if actual_root != root or actual != vector[name]['commit']:
            raise ValueError(f'checkout does not match captured current source: {name}')
        if not locked and remote_tip(url, branch) != actual:
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
    return {'status': 'locked-source-checked' if locked else 'current-source-checked', 'components': result}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('capture', 'lock', 'exports', 'check'))
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--deps', type=Path)
    parser.add_argument('--locked', action='store_true',
                        help='verify an explicit locked source vector instead of current remote tips')
    args = parser.parse_args()
    try:
        if args.action == 'capture':
            if args.locked:
                raise ValueError('capture always records current refs; use lock for explicit inputs')
            value = capture()
        else:
            if args.input is None:
                raise ValueError('an explicit captured input is required')
            vector = json.loads(args.input.read_text())
            if args.action == 'lock':
                value = validate(vector, locked=True)
            elif args.action == 'exports':
                print(exports(vector, locked=args.locked), end='')
                raise SystemExit(0)
            else:
                if args.deps is None:
                    raise ValueError('an explicit dependency checkout root is required')
                value = check(vector, args.deps, locked=args.locked)
        if args.output is None:
            raise ValueError('an explicit new evidence output is required')
        with args.output.open('x') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Current native sources rejected: {error}\n')
