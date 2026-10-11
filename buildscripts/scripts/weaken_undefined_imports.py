#!/usr/bin/env python3
"""Weaken specific undefined dynamic symbols in an ELF64 .so (in place or to a new file).

Why: the app supports Android API 24-27 (minSdk 24), but system libvulkan.so
only exports Vulkan 1.0 core there. libplacebo (statically linked into
libmpv.so) imports two Vulkan 1.1 core symbols unconditionally:

    vkGetPhysicalDeviceProperties2
    vkGetPhysicalDeviceQueueFamilyProperties2

The Android dynamic linker fails dlopen on a missing STB_GLOBAL undefined
import, so on those devices libmpv.so cannot load at all and
MediaKit.ensureInitialized fails. An STB_WEAK undefined import is optional:
missing at load time resolves to NULL instead of failing dlopen.

Contract: the weakened symbols are only reached when a Vulkan context is
created. The PiliPlusX Android playback topology (Texture / mediacodec-copy
/ gpu-next over GLES) never creates one, so the imports stay unresolved and
untouched. If a future build ships vo=vulkan / gpu-context=vulkan on
Android, restore strong imports (rebuild without this step) and raise the
effective minSdk to API 28+ instead.

Byte-level effect: for each listed symbol's .dynsym entry, st_info binding
GLOBAL(1) -> WEAK(2); type and everything else unchanged.
"""
import struct
import sys

STB_WEAK = 2

# Vulkan 1.1 core symbols imported by libplacebo but absent from the system
# Vulkan loader on Android API 24-27. Keep in sync with the contract above.
VULKAN_1_1_MISSING_BEFORE_API_28 = (
    "vkGetPhysicalDeviceProperties2",
    "vkGetPhysicalDeviceQueueFamilyProperties2",
)


def main(src, dst=None, symbols=VULKAN_1_1_MISSING_BEFORE_API_28):
    dst = dst or src
    with open(src, "rb") as f:
        data = bytearray(f.read())
    if data[:4] != b"\x7fELF" or data[4] != 2:
        sys.exit(f"{src}: not an ELF64 file")
    e_shoff, = struct.unpack_from("<Q", data, 0x28)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 0x3A)

    sections = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        fields = struct.unpack_from("<IIQQQQIIQQ", data, off)
        sections.append(
            dict(name_off=fields[0], typ=fields[1], offset=fields[4],
                 size=fields[5], link=fields[6], entsize=fields[9])
        )
    shstr = sections[e_shstrndx]
    strtab = data[shstr["offset"]:shstr["offset"] + shstr["size"]]

    def sec_name(entry):
        end = strtab.index(b"\0", entry["name_off"])
        return strtab[entry["name_off"]:end].decode()

    by_name = {sec_name(s): s for s in sections}
    if ".dynsym" not in by_name:
        sys.exit(f"{src}: no .dynsym section")
    dynsym = by_name[".dynsym"]
    dynstr = sections[dynsym["link"]]
    names = set(symbols)

    patched, already = [], []
    for i in range(dynsym["size"] // dynsym["entsize"]):
        off = dynsym["offset"] + i * dynsym["entsize"]
        st_name, st_info, st_other, st_shndx = struct.unpack_from("<IBBH", data, off)
        if st_shndx != 0:  # only undefined imports
            continue
        end = data.index(b"\0", dynstr["offset"] + st_name)
        sym = data[dynstr["offset"] + st_name:end].decode()
        if sym not in names:
            continue
        bind, symtype = st_info >> 4, st_info & 0xF
        if bind == STB_WEAK:
            already.append(sym)
            continue
        struct.pack_into("<B", data, off + 4, (STB_WEAK << 4) | symtype)
        patched.append(sym)

    with open(dst, "wb") as f:
        f.write(data)

    for sym in patched:
        print(f"{sym}: GLOBAL -> WEAK")
    for sym in already:
        print(f"{sym}: already WEAK")
    missing = names - set(patched) - set(already)
    if missing:
        sys.exit(f"{src}: target symbols not found as undefined imports: {sorted(missing)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: weaken_undefined_imports.py <libmpv.so> [output.so] [symbols...]")
    src = sys.argv[1]
    rest = sys.argv[2:]
    dst = None
    if rest and not rest[0].startswith(("vk",)):
        dst = rest[0]
        rest = rest[1:]
    main(src, dst, rest or VULKAN_1_1_MISSING_BEFORE_API_28)
