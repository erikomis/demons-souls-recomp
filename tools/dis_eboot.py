"""Disassemble Demon's Souls EBOOT.elf code with TOC-load annotations.
usage: dis_eboot.py <EBOOT.elf> [n=<count>] (opd:<hex> | ea:<hex>) ...
  opd:<hex>  function descriptor (entry, toc) -> disassemble its entry
  ea:<hex>   raw code address
lwz/ld rX, d(r2) lines are annotated with the TOC slot's value and, when that
points at a C string, the string."""
import struct, sys
from capstone import Cs, CS_ARCH_PPC, CS_MODE_64, CS_MODE_BIG_ENDIAN

b = open(sys.argv[1], 'rb').read()
phoff = struct.unpack_from('>Q', b, 0x20)[0]
segs = []
for i in range(struct.unpack_from('>H', b, 0x38)[0]):
    t, f, off, va, pa, fs, ms, al = struct.unpack_from('>IIQQQQQQ', b, phoff + i * 56)
    if t == 1 and fs:
        segs.append((va, off, fs))


def rd(va, n):
    for sva, off, fs in segs:
        if sva <= va < sva + fs:
            return b[off + va - sva: off + va - sva + n]
    return None


def u32(va):
    d = rd(va, 4)
    return struct.unpack('>I', d)[0] if d else None


def cstr(va):
    d = rd(va, 96)
    if not d:
        return None
    s = d.split(b'\0')[0]
    if len(s) >= 3 and all(32 <= c < 127 for c in s):
        return s.decode()
    return None


entry_opd = struct.unpack_from('>Q', b, 0x18)[0]
toc = u32(entry_opd + 4)
md = Cs(CS_ARCH_PPC, CS_MODE_64 | CS_MODE_BIG_ENDIAN)
count = 120
for a in sys.argv[2:]:
    if a.startswith('n='):
        count = int(a[2:])
        continue
    if a.startswith('opd:'):
        opd = int(a[4:], 16)
        ea, ftoc = u32(opd), u32(opd + 4)
        print('==== opd 0x%08X -> entry 0x%08X toc 0x%08X' % (opd, ea, ftoc))
        if ftoc:
            toc = ftoc
    else:
        ea = int(a[3:], 16)
        print('==== ea 0x%08X (toc 0x%08X)' % (ea, toc))
    code = rd(ea, count * 4) or b''
    for ins in md.disasm(code, ea):
        note = ''
        if ins.mnemonic in ('lwz', 'ld', 'addi') and ins.op_str.endswith('(r2)') or \
                (ins.mnemonic == 'addi' and ', r2, ' in ins.op_str):
            try:
                if ins.mnemonic == 'addi':
                    d = int(ins.op_str.split(',')[-1], 0)
                    note = '; &toc[%+d] = 0x%08X' % (d, toc + d)
                else:
                    d = int(ins.op_str.split(',')[1].split('(')[0], 0)
                    v = u32(toc + d)
                    note = '; toc[%+d] = 0x%08X' % (d, v)
                    s = cstr(v) if v else None
                    if s:
                        note += ' "%s"' % s
            except ValueError:
                pass
        print('  %08X  %-8s %s %s' % (ins.address, ins.mnemonic, ins.op_str, note))
