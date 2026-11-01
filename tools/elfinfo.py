"""Read DT_NEEDED entries and dynamic symbols from ELF64 little-endian shared objects."""

import struct

SHT_DYNSYM = 11
SHT_DYNAMIC = 6
DT_NEEDED = 1
STB_WEAK = 2
SHN_UNDEF = 0


def _cstr(blob, offset):
    end = blob.index(b"\0", offset)
    return blob[offset:end].decode()


def parse(blob):
    if blob[:4] != b"\x7fELF" or blob[4] != 2 or blob[5] != 1:
        raise ValueError("not an ELF64 little-endian object")
    shoff, = struct.unpack_from("<Q", blob, 0x28)
    shentsize, shnum = struct.unpack_from("<HH", blob, 0x3A)
    sections = []
    for index in range(shnum):
        name, kind, _, _, offset, size, link, _, _, entsize = struct.unpack_from(
            "<IIQQQQIIQQ", blob, shoff + index * shentsize)
        sections.append((kind, offset, size, link, entsize))
    needed = []
    defined = set()
    undefined = set()
    for kind, offset, size, link, entsize in sections:
        if kind == SHT_DYNAMIC:
            strtab = sections[link]
            for pos in range(offset, offset + size, 16):
                tag, value = struct.unpack_from("<qQ", blob, pos)
                if tag == 0:
                    break
                if tag == DT_NEEDED:
                    needed.append(_cstr(blob, strtab[1] + value))
        elif kind == SHT_DYNSYM:
            strtab = sections[link]
            for pos in range(offset + entsize, offset + size, entsize):
                name_off, info, _, shndx, _, _ = struct.unpack_from("<IBBHQQ", blob, pos)
                name = _cstr(blob, strtab[1] + name_off)
                if not name:
                    continue
                if shndx == SHN_UNDEF:
                    if info >> 4 != STB_WEAK:
                        undefined.add(name)
                else:
                    defined.add(name)
    return {"needed": needed, "defined": defined, "undefined": undefined}
