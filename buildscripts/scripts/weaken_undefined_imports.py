#!/usr/bin/env python3
"""Validate and atomically weaken the existing two Vulkan imports, if present.

Only GLOBAL undefined .dynsym entries may become WEAK; definitions, symbol
order, types and all other bytes remain unchanged. Absence is a valid no-op
only after the complete ELF and linked string table have been parsed. This
supports the four Android ABI layouts (ELF32/64, little endian), not extended
section numbering or arbitrary architectures. A successful mutation is NOT
approval of the runtime weak-import contract or evidence of device playback.
See https://gabi.xinuos.com/elf/05-symtab.html for the symbol layouts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import tempfile

VULKAN_1_1_MISSING_BEFORE_API_28 = (
    "vkGetPhysicalDeviceProperties2",
    "vkGetPhysicalDeviceQueueFamilyProperties2",
)
ABIS = {"arm64-v8a": (2, 183), "armeabi-v7a": (1, 40),
        "x86": (1, 3), "x86_64": (2, 62)}
MAX_FILE = 256 * 1024 * 1024


class ElfError(ValueError):
    pass


def checked_span(data: bytes, offset: int, size: int, label: str) -> bytes:
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise ElfError(f"{label}: out of file bounds")
    return data[offset:offset + size]


def string_at(table: bytes, offset: int, label: str) -> str:
    if not 0 <= offset < len(table):
        raise ElfError(f"{label}: string offset out of bounds")
    end = table.find(b"\0", offset)
    if end == -1:
        raise ElfError(f"{label}: unterminated string")
    # Non-ASCII symbol names elsewhere must not hide the target imports.
    return table[offset:end].decode("utf-8", errors="surrogateescape")


def inspect(data: bytes, abi: str | None = None) -> dict:
    if len(data) < 16 or len(data) > MAX_FILE or data[:4] != b"\x7fELF":
        raise ElfError("not a bounded ELF file")
    cls = data[4]
    if cls not in (1, 2) or data[5:7] != b"\x01\x01":
        raise ElfError("unsupported ELF class, endianness or version")
    header_format = "<16sHHIIIIIHHHHHH" if cls == 1 else "<16sHHIQQQIHHHHHH"
    header_size = struct.calcsize(header_format)
    header = struct.unpack(header_format, checked_span(data, 0, header_size, "ELF header"))
    _, kind, machine, version, _, phoff, shoff, _, ehsize, phsize, phnum, shsize, shnum, shstrndx = header
    actual_abi = next((name for name, layout in ABIS.items() if layout == (cls, machine)), None)
    if kind != 3 or version != 1 or ehsize != header_size or actual_abi is None:
        raise ElfError("expected ET_DYN with a supported Android ABI layout")
    if abi is not None and abi != actual_abi:
        raise ElfError(f"ABI mismatch: expected {abi}, found {actual_abi}")
    section_format = "<IIIIIIIIII" if cls == 1 else "<IIQQQQIIQQ"
    if shsize != struct.calcsize(section_format) or not 0 < shnum < 0xff00 or not 0 < shstrndx < shnum:
        raise ElfError("invalid/extended section table numbering or entry size")
    if shoff < header_size:
        raise ElfError("section table overlaps ELF header")
    checked_span(data, shoff, shsize * shnum, "section table")
    if not phnum or phnum == 0xffff or phsize != (32 if cls == 1 else 56) or phoff < header_size:
        raise ElfError("invalid/extended program header table")
    checked_span(data, phoff, phsize * phnum, "program table")
    sections = [struct.unpack_from(section_format, data, shoff + i * shsize) for i in range(shnum)]
    if any(sections[0]):
        raise ElfError("nonzero null section is unsupported")
    spans = [(0, header_size), (phoff, phoff + phsize * phnum), (shoff, shoff + shsize * shnum)]
    for section in sections[1:]:
        offset, size = section[4:6]
        if section[1] != 8 and size:  # SHT_NOBITS occupies no file bytes.
            checked_span(data, offset, size, "section data")
            spans.append((offset, offset + size))
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise ElfError("overlapping ELF file regions")
    names_section = sections[shstrndx]
    if names_section[1] != 3:
        raise ElfError("section names must reference SHT_STRTAB")
    names = checked_span(data, names_section[4], names_section[5], "section names")
    if not names or names[0] or names[-1]:
        raise ElfError("invalid section name string table")
    section_names = [string_at(names, section[0], "section name") for section in sections]
    tables = [i for i, section in enumerate(sections) if section[1] == 11]
    if len(tables) != 1 or section_names[tables[0]] != ".dynsym":
        raise ElfError("exactly one .dynsym SHT_DYNSYM section is required")
    dyn = sections[tables[0]]
    entry_size = 16 if cls == 1 else 24
    if dyn[9] != entry_size or dyn[5] < entry_size or dyn[5] % entry_size or not 0 < dyn[6] < shnum:
        raise ElfError("invalid dynamic symbol entry size, count or string link")
    strings = sections[dyn[6]]
    if strings[1] != 3:
        raise ElfError("dynamic symbols must link to SHT_STRTAB")
    string_table = checked_span(data, strings[4], strings[5], "dynamic strings")
    if not string_table or string_table[0] or string_table[-1]:
        raise ElfError("invalid dynamic string table")
    if any(checked_span(data, dyn[4], entry_size, "null symbol")):
        raise ElfError("nonzero null dynamic symbol")
    symbols = []
    for offset in range(dyn[4] + entry_size, dyn[4] + dyn[5], entry_size):
        name_offset = struct.unpack_from("<I", data, offset)[0]
        info_offset = offset + (12 if cls == 1 else 4)
        info, _, shndx = struct.unpack_from("<BBH", data, info_offset)
        if shndx == 0xffff:
            raise ElfError("extended symbol section index is unsupported")
        name = string_at(string_table, name_offset, "dynamic symbol name")
        symbols.append({"name": name, "binding": info >> 4, "type": info & 15,
                        "section": shndx, "infoOffset": info_offset})
    return {"abi": actual_abi, "elfClass": 32 if cls == 1 else 64,
            "machine": machine, "symbols": symbols}


def plan(data: bytes, symbols=VULKAN_1_1_MISSING_BEFORE_API_28, *, abi=None):
    symbols = tuple(symbols)
    if not symbols or len(set(symbols)) != len(symbols) or not set(symbols) <= set(VULKAN_1_1_MISSING_BEFORE_API_28):
        raise ElfError("only the distinct approved target names may be requested")
    parsed = inspect(data, abi)
    changes, already, seen = [], set(), set()
    for symbol in parsed["symbols"]:
        if symbol["name"] not in symbols or symbol["section"] != 0:
            continue
        name = symbol["name"]
        seen.add(name)
        if symbol["binding"] == 2:
            already.add(name)
        elif symbol["binding"] == 1:
            changes.append(symbol)
        else:
            raise ElfError(f"{name}: unexpected undefined binding {symbol['binding']}")
    patched = bytearray(data)
    for symbol in changes:
        patched[symbol["infoOffset"]] = (2 << 4) | symbol["type"]
    result = bytes(patched)
    verified = inspect(result, abi)
    if any(s["name"] in symbols and s["section"] == 0 and s["binding"] != 2 for s in verified["symbols"]):
        raise ElfError("post-mutation symbol verification failed")
    receipt = {"schemaVersion": 1, "abi": parsed["abi"], "elfClass": parsed["elfClass"],
               "machine": parsed["machine"], "patched": sorted({s["name"] for s in changes}),
               "alreadyWeak": sorted(already), "absent": sorted(set(symbols) - seen),
               "changedByteOffsets": [s["infoOffset"] for s in changes],
               "beforeSha256": hashlib.sha256(data).hexdigest(),
               "afterSha256": hashlib.sha256(result).hexdigest(),
               "runtimeContractApproved": False}
    return result, receipt


def main(src, dst=None, symbols=VULKAN_1_1_MISSING_BEFORE_API_28, *, abi=None):
    source = Path(src)
    metadata = source.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > MAX_FILE:
        raise ElfError("input must be one bounded regular file, not a link")
    data = source.read_bytes()
    result, receipt = plan(data, symbols, abi=abi)
    destination = Path(dst) if dst is not None else source
    same = destination.absolute() == source.absolute()
    if not same and (destination.exists() or destination.is_symlink()):
        raise ElfError("output already exists; refusing to replace an unrelated file")
    if same and result == data:
        return receipt  # Valid no-op; do not even change the input inode/mtime.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".elf-", dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(result)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(stat.S_IMODE(metadata.st_mode))
        if same:
            current = source.lstat()
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns
            ) or source.read_bytes() != data:
                raise ElfError("input changed during validation")
            os.replace(temporary, destination)
        else:
            os.link(temporary, destination)  # Atomic, and fails if destination appeared.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", type=Path)
    parser.add_argument("dst", nargs="?", type=Path)
    parser.add_argument("--abi", choices=ABIS)
    args = parser.parse_args()
    try:
        print(json.dumps(main(args.src, args.dst, abi=args.abi), sort_keys=True))
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f"ELF import validation failed: {error}\n")
