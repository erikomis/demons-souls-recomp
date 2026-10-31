"""Disassemble libsre exports by NID from lift_prx.py output (relocated image)."""
import json, struct, sys
from capstone import Cs, CS_ARCH_PPC, CS_MODE_64, CS_MODE_BIG_ENDIAN

out = sys.argv[1]
names = sys.argv[2:]          # NID hex values (no 0x) or 'ea:<hex>' / 'n=<count>'
ex = json.load(open(out + '/libsre_exports.json'))
img = open(out + '/libsre_image.bin', 'rb').read()
base = int(ex['base'], 16)
md = Cs(CS_ARCH_PPC, CS_MODE_64 | CS_MODE_BIG_ENDIAN)
count = 160
for a in names:
    if a.startswith('n='):
        count = int(a[2:]); continue
    if a.startswith('ea:'):
        entry = int(a[3:], 16); label = a
    else:
        opd = None
        for lib, m in ex['exports'].items():
            for k, v in m.items():
                if int(k, 16) == int(a, 16):
                    opd = int(v, 16)
        if opd is None:
            print('NID', a, 'not exported'); continue
        entry = struct.unpack('>I', img[opd - base:opd - base + 4])[0]
        label = 'NID %s opd 0x%08X' % (a, opd)
    print('====', label, 'entry 0x%08X' % entry)
    code = img[entry - base:entry - base + count * 4]
    for ins in md.disasm(code, entry):
        print('  %08X  %-8s %s' % (ins.address, ins.mnemonic, ins.op_str))
