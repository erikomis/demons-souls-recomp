"""Decompress FromSoftware DCX containers (EDGE and DFLT variants) from Demon's Souls.

Layout (big-endian), as SoulsFormats documents it:
  "DCX\\0" ... "DCS\\0" u32 uncompressed_size u32 compressed_size
  "DCP\\0" "EDGE"|"DFLT" ...  "DCA\\0" u32 dca_size
  EDGE: dca is followed by "EgdT" with a block table: per block
        {u32 0, u32 offset, u32 size, u32 compressed}; offsets are relative
        to the end of the DCA section; compressed blocks are raw deflate.
  DFLT: a zlib stream follows the DCA section.
Usage: dcx.py <in.dcx> <out>"""
import struct, sys, zlib

def u32(b, o): return struct.unpack_from('>I', b, o)[0]

def decompress(data):
    if data[:4] != b'DCX\0':
        raise ValueError('not a DCX file')
    dcs = data.find(b'DCS\0')
    usize = u32(data, dcs + 4)
    dcp = data.find(b'DCP\0')
    kind = data[dcp + 4:dcp + 8]
    dca = data.find(b'DCA\0', dcp)
    dca_size = u32(data, dca + 4)
    body = dca + dca_size
    if kind == b'DFLT':
        return zlib.decompress(data[body:])[:usize]
    if kind != b'EDGE':
        raise ValueError('unsupported DCX kind %r' % kind)
    egdt = dca + 8
    assert data[egdt:egdt + 4] == b'EgdT', 'no EgdT table'
    block_count = u32(data, egdt + 0x1C)
    out = bytearray()
    for i in range(block_count):
        _, off, size, comp = struct.unpack_from('>4I', data, egdt + 0x24 + i * 16)
        chunk = data[body + off: body + off + size]
        out += zlib.decompress(chunk, -15) if comp else chunk
    return bytes(out[:usize])

if __name__ == '__main__':
    raw = decompress(open(sys.argv[1], 'rb').read())
    open(sys.argv[2], 'wb').write(raw)
    print('%s -> %d bytes' % (sys.argv[2], len(raw)))
