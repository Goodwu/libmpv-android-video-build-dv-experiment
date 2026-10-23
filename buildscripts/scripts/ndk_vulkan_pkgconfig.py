#!/usr/bin/env python3
"""Describe the selected NDK's Vulkan headers without running target code.

Meson 1.6's system Vulkan dependency runs a target executable to obtain its
version, so an Android cross build reports "unknown".  Read the same compiler's
header macros, then compile and link a check before publishing pkg-config data.
This checks build inputs; it does not assert a device's Vulkan capabilities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

MINIMUM = (1, 3, 238)


def run(compiler, arguments, source):
    result = subprocess.run([compiler, *arguments], input=source,
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError("NDK Vulkan compiler check failed:\n" + result.stderr)
    return result.stdout


def header_version(macros):
    patch = re.search(r'^#define VK_HEADER_VERSION ([0-9]+)\s*$', macros, re.M)
    complete = re.search(
        r'^#define VK_HEADER_VERSION_COMPLETE '
        r'VK_MAKE_API_VERSION\(\s*0\s*,\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*VK_HEADER_VERSION\s*\)\s*$',
        macros, re.M)
    if not patch or not complete:
        raise ValueError("Review the selected NDK's unsupported Vulkan version macros")
    version = (int(complete[1]), int(complete[2]), int(patch[1]))
    if version < MINIMUM:
        raise ValueError(f"NDK Vulkan headers {version} do not meet mpv's {MINIMUM} minimum")
    return version


def create(compiler, output, evidence):
    macros = run(compiler, ['-E', '-dM', '-x', 'c', '-'],
                 '#include <vulkan/vulkan.h>\n')
    version = header_version(macros)
    major, minor, patch = version
    probe = f'''#include <vulkan/vulkan.h>
_Static_assert(VK_HEADER_VERSION_COMPLETE == VK_MAKE_API_VERSION(0, {major}, {minor}, {patch}), "Vulkan version differs");
_Static_assert(VK_HEADER_VERSION_COMPLETE >= VK_MAKE_API_VERSION(0, 1, 3, 238), "Vulkan headers are too old");
int main(void) {{ return vkGetInstanceProcAddr(VK_NULL_HANDLE, "vkCreateInstance") == 0; }}
'''
    with tempfile.TemporaryDirectory(prefix='ndk-vulkan-') as temp:
        run(compiler, ['-std=c11', '-Werror', '-x', 'c', '-', '-o',
                       str(Path(temp) / 'probe'), '-lvulkan', '-Wl,--no-undefined'], probe)
    version_string = '.'.join(map(str, version))
    content = ('Name: vulkan\n'
               'Description: Selected Android NDK Vulkan headers and loader\n'
               f'Version: {version_string}\n'
               'Libs: -lvulkan\n')
    if output.is_symlink():
        raise ValueError('Vulkan pkg-config destination must not be a symlink')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
    report = {'schema': 1, 'compiler': Path(compiler).name,
              'header_version': version_string, 'minimum_header_version': '.'.join(map(str, MINIMUM)),
              'preprocessor_sha256': hashlib.sha256(macros.encode()).hexdigest(),
              'probe_sha256': hashlib.sha256(probe.encode()).hexdigest(),
              'pkgconfig_sha256': hashlib.sha256(content.encode()).hexdigest(),
              'compiled': True, 'linked': True, 'runtime': False, 'device': False}
    if evidence:
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(create(args.compiler, args.output, args.evidence), sort_keys=True))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f'NDK Vulkan dependency rejected: {error}\n')
