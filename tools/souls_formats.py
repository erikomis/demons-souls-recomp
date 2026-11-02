"""Demon's Souls (PS3) file formats for tools/flver_tool.py: DCX, BND3, FLVER0, TPF. Standard library only.

Every reader keeps what it does not interpret as raw bytes, and every writer is checked to give back the
original file byte for byte when nothing was changed (flver_tool.py selftest), so a model that is imported
changes only what the import touched.

Layouts as SoulsFormats documents them, confirmed against the game's own files:

  DCX (EDGE)  "DCX\\0" ... "DCS\\0" usize csize "DCP\\0EDGE" ... "DCA\\0" size "EgdT" table of 64 KB blocks,
              each raw deflate (or stored); DFLT = one zlib stream. The game opens the .dcx copies.
  BND3        "BND3" + 8-char version, format byte, endianness, file entries (flags, size, offset, id,
              name offset, uncompressed size), Shift-JIS names, data.
  FLVER0      big-endian, version 0x15: header 0x80, dummies 0x40 each, materials 0x20 each, bones 0x80
              each, meshes 0x64 each, then per material its strings / texture table / buffer layouts, the
              bone names, per mesh its vertex buffer headers, and at dataOffset per mesh the triangle-strip
              indices (0xFFFF = restart) and vertex buffers, each 32-byte aligned.
  TPF (PS3)   "TPF\\0" data size, count, platform 2; entries: offset, size, format, type, mips, flags,
              width, height, two words (the second is the RSX channel remap), name offset, flags.
"""
import struct, zlib

# ------------------------------------------------------------------------------------------------ DCX


def dcx_decompress(data):
    """-> (payload, info) where info carries what dcx_compress needs to write the same kind back."""
    if data[:4] == b'DCP\0':   # bare "DCP" container (a few files): DFLT body after a DCS header
        dcs = data.find(b'DCS\0')
        usize = struct.unpack_from('>I', data, dcs + 4)[0]
        csize = struct.unpack_from('>I', data, dcs + 8)[0]
        return zlib.decompress(data[dcs + 12: dcs + 12 + csize])[:usize], \
            {'kind': 'DCP-DFLT', 'head': data[:dcs], 'tail': data[dcs + 12 + csize:]}
    if data[:4] != b'DCX\0':
        raise ValueError('not a DCX file')
    dcs = data.find(b'DCS\0')
    usize = struct.unpack_from('>I', data, dcs + 4)[0]
    dcp = data.find(b'DCP\0')
    kind = data[dcp + 4:dcp + 8]
    dca = data.find(b'DCA\0', dcp)
    dca_size = struct.unpack_from('>I', data, dca + 4)[0]
    body = dca + dca_size
    if kind == b'DFLT':
        return zlib.decompress(data[body:])[:usize], {'kind': 'DFLT', 'head': data[:body]}
    if kind != b'EDGE':
        raise ValueError('unsupported DCX kind %r' % kind)
    egdt = dca + 8
    if data[egdt:egdt + 4] != b'EgdT':
        raise ValueError('EDGE DCX without an EgdT table')
    block_count = struct.unpack_from('>I', data, egdt + 0x1C)[0]
    out = bytearray()
    for i in range(block_count):
        _, off, size, comp = struct.unpack_from('>4I', data, egdt + 0x24 + i * 16)
        chunk = data[body + off: body + off + size]
        out += zlib.decompress(chunk, -15) if comp else chunk
    return bytes(out[:usize]), {'kind': 'EDGE', 'head': data[:egdt + 0x24]}


def dcx_compress(payload, info):
    """Write payload as the same kind of DCX `info` (from dcx_decompress) came from. EDGE: header copied
    from the original with sizes and the block table rewritten."""
    if info['kind'] == 'EDGE':
        head = bytearray(info['head'])
        egdt = head.find(b'EgdT')
        block = struct.unpack_from('>I', head, egdt + 0x10)[0] or 0x10000
        blocks, table, body = [], bytearray(), bytearray()
        for o in range(0, len(payload), block):
            raw = payload[o:o + block]
            co = zlib.compressobj(9, zlib.DEFLATED, -15)
            c = co.compress(raw) + co.flush()
            comp = len(c) < len(raw)
            data = c if comp else raw
            table += struct.pack('>4I', 0, len(body), len(data), 1 if comp else 0)
            body += data
            pad = (-len(body)) % 16
            body += b'\0' * pad
            blocks.append(len(data))
        n = len(blocks)
        last = len(payload) - (n - 1) * block if n else 0
        egdt_size = 0x24 + len(table)
        struct.pack_into('>I', head, egdt + 0x14, last)          # uncompressed size of the last block
        struct.pack_into('>I', head, egdt + 0x18, egdt_size)     # table size
        struct.pack_into('>I', head, egdt + 0x1C, n)
        dca = head.find(b'DCA\0')
        struct.pack_into('>I', head, dca + 4, 8 + egdt_size)
        # 0x14 = header size before the block data (0x10's DCS/DCP part + the DCA section); the game's
        # reader skips h[0x14] - (h[0x10] + DCA size) bytes, so a stale value after the block count
        # changed made it read from the wrong place and the map loader hang (NOTES fix 61)
        struct.pack_into('>I', head, 0x14, struct.unpack_from('>I', head, 0x10)[0] + 8 + egdt_size)
        dcs = head.find(b'DCS\0')
        struct.pack_into('>II', head, dcs + 4, len(payload), len(body))   # block data only, as the game's files
        return bytes(head) + bytes(table) + bytes(body)
    if info['kind'] == 'DFLT':
        head = bytearray(info['head'])
        c = zlib.compress(payload, 9)
        dcs = head.find(b'DCS\0')
        struct.pack_into('>II', head, dcs + 4, len(payload), len(c))
        return bytes(head) + c
    if info['kind'] == 'DCP-DFLT':   # "DCP\0DFLT" ... "DCS\0" usize csize, zlib, "DCA\0" trailer
        c = zlib.compress(payload, 9)
        return bytes(info['head']) + b'DCS\0' + struct.pack('>II', len(payload), len(c)) + c + bytes(info['tail'])
    raise ValueError('cannot write DCX kind %s' % info['kind'])


# ------------------------------------------------------------------------------------------------ BND3


class Bnd3:
    """BND3 archive. entries: list of dicts {flags, id, name, data, uflags(raw extra)}."""

    def __init__(self, data):
        if data[:4] != b'BND3':
            raise ValueError('not a BND3 archive')
        self.version = data[4:12]
        self.fmt = data[12]
        self.big = data[13] != 0 or data[12] & 0x01 == 0   # endianness byte; DeS files are big-endian
        self.head_bytes = data[12:16]
        E = '>' if data[13] else '<'
        self.E = E
        n = struct.unpack_from(E + 'i', data, 0x10)[0]
        self.header_size = struct.unpack_from(E + 'i', data, 0x14)[0]
        self.unk18 = data[0x18:0x20]
        fmt = self.fmt
        has_id = fmt & 0x02
        has_name = fmt & 0x0C
        has_usize = fmt & 0x20
        esize = 12 + (4 if has_id else 0) + (4 if has_name else 0) + (4 if has_usize else 0)
        self.entries = []
        o = 0x20
        for i in range(n):
            flags = data[o]
            pad = data[o + 1:o + 4]
            csize, off = struct.unpack_from(E + 'ii', data, o + 4)
            p = o + 12
            fid = name = None
            usize = None
            if has_id:
                fid = struct.unpack_from(E + 'i', data, p)[0]; p += 4
            if has_name:
                no = struct.unpack_from(E + 'i', data, p)[0]; p += 4
                e = data.index(b'\0', no)
                name = data[no:e].decode('shift_jis')
            if has_usize:
                usize = struct.unpack_from(E + 'i', data, p)[0]; p += 4
            self.entries.append({'flags': flags, 'pad': pad, 'id': fid, 'name': name, 'usize': usize,
                                 'data': data[off:off + csize], 'off': off})
            o += esize
        self.esize = esize
        self.names_start = o
        # data alignment as the original laid it out (first data offset after the names)
        self.first_data = min((e['off'] for e in self.entries), default=self.header_size)
        self.tail = data[max((e['off'] + len(e['data']) for e in self.entries), default=o):]   # empty: all after the header
        # file data alignment: the largest of 16 / 4 / 1 every data offset keeps
        self.align = next((a for a in (16, 4, 2, 1) if all(e['off'] % a == 0 for e in self.entries if e['data'])), 1)

    def write(self):
        E = self.E
        out = bytearray(b'BND3' + self.version + self.head_bytes)
        out += struct.pack(E + 'ii', len(self.entries), 0) + self.unk18
        table = len(out)
        out += b'\0' * (self.esize * len(self.entries))
        name_offs = []
        for e in self.entries:
            if e['name'] is not None:
                name_offs.append(len(out))
                out += e['name'].encode('shift_jis') + b'\0'
            else:
                name_offs.append(0)
        header_size = len(out) if self.entries else self.header_size
        struct.pack_into(E + 'i', out, 0x14, header_size)
        A = self.align
        offs = []
        for e in self.entries:
            if e['data']:   # padding goes before each file with data; an empty file sits where it falls
                out += b'\0' * ((-len(out)) % A)
            offs.append(len(out))
            out += e['data']
        out += self.tail
        for i, e in enumerate(self.entries):
            o = table + i * self.esize
            out[o] = e['flags']
            out[o + 1:o + 4] = e['pad']
            struct.pack_into(E + 'ii', out, o + 4, len(e['data']), offs[i])
            p = o + 12
            if self.fmt & 0x02:
                struct.pack_into(E + 'i', out, p, e['id']); p += 4
            if self.fmt & 0x0C:
                struct.pack_into(E + 'i', out, p, name_offs[i]); p += 4
            if self.fmt & 0x20:
                struct.pack_into(E + 'i', out, p, len(e['data'])); p += 4
        return bytes(out)


# ------------------------------------------------------------------------------------------------ FLVER0

# layout member types (as in SoulsFormats FLVER.LayoutType) and their sizes in bytes
LAYOUT_SIZE = {0x01: 8, 0x02: 12, 0x03: 16, 0x10: 4, 0x11: 4, 0x12: 4, 0x13: 4, 0x15: 4, 0x16: 8,
               0x18: 8, 0x1A: 8, 0x2E: 8, 0x2F: 4, 0xF0: 4}
SEM_POSITION, SEM_WEIGHTS, SEM_BONES, SEM_NORMAL, SEM_UV, SEM_TANGENT, SEM_BITANGENT, SEM_COLOR = 0, 1, 2, 3, 5, 6, 7, 10


class Flver0:
    def __init__(self, data):
        if data[:6] != b'FLVER\0':
            raise ValueError('not a FLVER file')
        self.big = data[6:8] == b'B\0'
        E = self.E = '>' if self.big else '<'
        self.raw_header = bytearray(data[:0x80])
        self.version = struct.unpack_from(E + 'i', data, 8)[0]
        if self.version >= 0x20000:
            raise ValueError('this is a FLVER2 (later games); only Demon\'s Souls FLVER0 is supported')
        data_off, data_size, nd, nm, nb, nme, nvb = struct.unpack_from(E + '7i', data, 0x0C)
        self.index_size = data[0x48]
        self.unicode = data[0x49] != 0
        self.dummies = [data[0x80 + i * 0x40: 0xC0 + i * 0x40] for i in range(nd)]
        o = 0x80 + nd * 0x40
        self.materials = []
        for i in range(nm):
            name_o, mtd_o, tex_o, lay_o, _len, lh_o, z1, z2 = struct.unpack_from(E + '8i', data, o + i * 0x20)
            m = {'name': self._str(data, name_o), 'mtd': self._str(data, mtd_o), 'textures': [],
                 'layouts': [], 'z': (z1, z2), 'tex_hdr': None, 'layout_header': lh_o != 0}
            if tex_o:
                cnt = data[tex_o]
                m['tex_hdr'] = data[tex_o:tex_o + 16]
                for k in range(cnt):
                    p_o, t_o, a, b = struct.unpack_from(E + '4i', data, tex_o + 16 + k * 16)
                    m['textures'].append({'path': self._str(data, p_o), 'type': self._str(data, t_o) if t_o else None,
                                          'ab': (a, b)})
            if lh_o:
                cnt, list_o, a, b = struct.unpack_from(E + '4i', data, lh_o)
                m['lh_ab'] = (a, b)
                for k in range(cnt):
                    lo = struct.unpack_from(E + 'i', data, list_o + 4 * k)[0]
                    m['layouts'].append(self._layout(data, lo))
            else:
                m['layouts'].append(self._layout(data, lay_o))
            self.materials.append(m)
        o += nm * 0x20
        self.bones = []
        for i in range(nb):
            raw = bytearray(data[o + i * 0x80: o + (i + 1) * 0x80])
            name_o = struct.unpack_from(E + 'i', raw, 0x0C)[0]
            self.bones.append({'raw': raw, 'name': self._str(data, name_o)})
        o += nb * 0x80
        self.meshes = []
        for i in range(nme):
            mo = o + i * 0x64
            raw = bytearray(data[mo:mo + 0x64])
            dyn, mat, u2, u3 = raw[0], raw[1], raw[2], raw[3]
            nidx, nvert = struct.unpack_from(E + 'ii', raw, 4)
            default_bone = struct.unpack_from(E + 'h', raw, 12)[0]
            bone_idx = list(struct.unpack_from(E + '28h', raw, 14))
            idx_len, idx_off, buf_len, buf_off, vb1, vb2, z = struct.unpack_from(E + '7i', raw, 0x48)
            isz = 4 if self.index_size == 32 else 2
            indices = list(struct.unpack_from(E + ('%dI' if isz == 4 else '%dH') % nidx, data, data_off + idx_off))
            if vb1:
                vbs = self._vbufs(data, vb1, data_off)
            else:   # no vertex buffer header (some characters): one buffer, layout 0
                vbs = {'ab': (0, 0), 'implicit': True, 'buffers': [
                    {'layout': 0, 'data': data[data_off + buf_off: data_off + buf_off + buf_len], 'z': 0}]}
            vbs2 = self._vbufs(data, vb2, data_off) if vb2 else None
            self.meshes.append({'raw': raw, 'dynamic': dyn, 'material': mat, 'default_bone': default_bone,
                                'bone_indices': bone_idx, 'indices': indices, 'vertex_count': nvert,
                                'vbufs': vbs, 'vbufs2': vbs2})
        self.data_align = 0x20

    def _str(self, data, o):
        if self.unicode:
            e = o
            while data[e:e + 2] != b'\0\0':
                e += 2
            return data[o:e].decode('utf-16-be' if self.big else 'utf-16-le')
        e = data.index(b'\0', o)
        return data[o:e].decode('shift_jis')

    def _enc(self, s):
        if self.unicode:
            return s.encode('utf-16-be' if self.big else 'utf-16-le') + b'\0\0'
        return s.encode('shift_jis') + b'\0'

    def _layout(self, data, o):
        E = self.E
        n, size = struct.unpack_from(E + 'hh', data, o)
        hdr = data[o + 4:o + 16]
        members = [list(struct.unpack_from(E + '5i', data, o + 16 + k * 20)) for k in range(n)]
        return {'size': size, 'hdr': hdr, 'members': members}

    def _vbufs(self, data, o, data_off):
        E = self.E
        cnt, list_o, a, b = struct.unpack_from(E + '4i', data, o)
        out = {'ab': (a, b), 'buffers': []}
        for k in range(cnt):
            lay, blen, boff, z = struct.unpack_from(E + '4i', data, list_o + 16 * k)
            out['buffers'].append({'layout': lay, 'data': data[data_off + boff: data_off + boff + blen], 'z': z})
        return out

    # -------------------------------------------------------------------------------------------- write
    def write(self):
        E = self.E
        nd, nm, nb, nme = len(self.dummies), len(self.materials), len(self.bones), len(self.meshes)
        out = bytearray(self.raw_header)
        for d in self.dummies:
            out += d
        mat_tab = len(out); out += b'\0' * (0x20 * nm)
        bone_tab = len(out); out += b'\0' * (0x80 * nb)
        mesh_tab = len(out); out += b'\0' * (0x64 * nme)
        for i, m in enumerate(self.materials):
            start = len(out)
            name_o = len(out); out += self._enc(m['name'])
            mtd_o = len(out); out += self._enc(m['mtd'])
            tex_o = 0
            if m['tex_hdr'] is not None:
                tex_o = len(out)
                hdr = bytearray(m['tex_hdr']); hdr[0] = len(m['textures'])
                out += hdr
                tab = len(out); out += b'\0' * (16 * len(m['textures']))
                for k, t in enumerate(m['textures']):
                    p_o = len(out); out += self._enc(t['path'])
                    t_o = 0
                    if t['type'] is not None:
                        t_o = len(out); out += self._enc(t['type'])
                    struct.pack_into(E + '4i', out, tab + 16 * k, p_o, t_o, *t['ab'])
            lh_o = 0
            if m['layout_header']:
                lh_o = len(out)
                out += struct.pack(E + '4i', len(m['layouts']), lh_o + 16, *m.get('lh_ab', (0, 0)))
                lst = len(out); out += b'\0' * (4 * len(m['layouts']))
            lay_first = None
            for k, L in enumerate(m['layouts']):
                lo = len(out)
                if lay_first is None:
                    lay_first = lo
                if m['layout_header']:
                    struct.pack_into(E + 'i', out, lst + 4 * k, lo)
                out += struct.pack(E + 'hh', len(L['members']), L['size']) + L['hdr']
                for mem in L['members']:
                    out += struct.pack(E + '5i', *mem)
            struct.pack_into(E + '8i', out, mat_tab + 0x20 * i, name_o, mtd_o, tex_o, lay_first or 0,
                             len(out) - start, lh_o, *m['z'])
        for i, b in enumerate(self.bones):
            name_o = len(out); out += self._enc(b['name'])
            raw = bytearray(b['raw'])
            struct.pack_into(E + 'i', raw, 0x0C, name_o)
            out[bone_tab + 0x80 * i: bone_tab + 0x80 * (i + 1)] = raw
        vb_heads = []
        for me in self.meshes:
            pair = []
            for vbs in (me['vbufs'], me['vbufs2']):
                if vbs is None or vbs.get('implicit'):
                    pair.append(None); continue
                h = len(out)
                out += struct.pack(E + '4i', len(vbs['buffers']), h + 16, *vbs['ab'])
                lst = len(out); out += b'\0' * (16 * len(vbs['buffers']))
                pair.append((h, lst))
            vb_heads.append(pair)
        out += b'\0' * ((-len(out)) % self.data_align)
        data_off = len(out)
        data = bytearray()
        isz = 4 if self.index_size == 32 else 2
        total_faces = 0
        true_faces = 0
        for i, me in enumerate(self.meshes):
            idx_off = len(data)
            data += struct.pack(E + ('%dI' if isz == 4 else '%dH') % len(me['indices']), *me['indices'])
            data += b'\0' * ((-len(data)) % self.data_align)
            buf_start = len(data)
            for p, vbs in enumerate((me['vbufs'], me['vbufs2'])):
                if vbs is None:
                    continue
                for k, b in enumerate(vbs['buffers']):
                    boff = len(data)
                    data += b['data']
                    data += b'\0' * ((-len(data)) % self.data_align)
                    if vb_heads[i][p] is not None:
                        struct.pack_into(E + '4i', out, vb_heads[i][p][1] + 16 * k, b['layout'], len(b['data']),
                                         boff, b['z'])
            raw = me['raw']
            raw[0] = me['dynamic']; raw[1] = me['material']
            struct.pack_into(E + 'ii', raw, 4, len(me['indices']), me['vertex_count'])
            struct.pack_into(E + 'h', raw, 12, me['default_bone'])
            struct.pack_into(E + '28h', raw, 14, *me['bone_indices'])
            buf_len = sum(len(b['data']) for b in me['vbufs']['buffers'])
            vb1 = vb_heads[i][0][0] if vb_heads[i][0] else 0
            vb2 = vb_heads[i][1][0] if vb_heads[i][1] else 0
            struct.pack_into(E + '6i', raw, 0x48, len(me['indices']) * isz, idx_off, buf_len, buf_start, vb1, vb2)
            out[mesh_tab + 0x64 * i: mesh_tab + 0x64 * (i + 1)] = raw
            f = strip_triangles(me['indices'])
            total_faces += len(f)
            true_faces += sum(1 for t in f if t[0] != t[1] and t[1] != t[2] and t[0] != t[2])
        hdr = out
        struct.pack_into(E + '7i', hdr, 0x0C, data_off, len(data), nd, nm, nb, nme,
                         sum(len(me['vbufs']['buffers']) + (len(me['vbufs2']['buffers']) if me['vbufs2'] else 0)
                             for me in self.meshes))
        return bytes(out) + bytes(data)


def strip_triangles(indices, restart=0xFFFF):
    """Triangle strip (with restart index) -> list of (a, b, c), winding as the strip implies; keeps
    degenerate triangles (callers drop them)."""
    tris = []
    run = []
    for i in indices:
        if i == restart or i == 0xFFFFFFFF:
            run = []
            continue
        run.append(i)
        if len(run) >= 3:
            a, b, c = run[-3], run[-2], run[-1]
            tris.append((a, b, c) if len(run) % 2 == 1 else (b, a, c))
    return tris


# ------------------------------------------------------------------------------------------------ TPF


class Tpf:
    """PS3 TPF: textures with name, format code, size, mip count, raw data, remap word."""

    def __init__(self, data):
        if data[:4] != b'TPF\0':
            raise ValueError('not a TPF file')
        self.platform = data[0x0C]
        if self.platform != 2:
            raise ValueError('only PS3 TPFs are supported (platform %d)' % self.platform)
        n = struct.unpack_from('>i', data, 8)[0]
        flag2 = data[0x0D]
        self.textures = []
        o = 0x10
        for i in range(n):
            off, size = struct.unpack_from('>Ii', data, o)
            fmt, typ, mips, fl1 = data[o + 8:o + 12]
            w, h = struct.unpack_from('>HH', data, o + 12)
            u1 = struct.unpack_from('>I', data, o + 16)[0]
            p = o + 20
            u2 = 0
            if flag2:
                u2 = struct.unpack_from('>I', data, p)[0]; p += 4
            name_o, fl2 = struct.unpack_from('>Ii', data, p); p += 8
            e = data.index(b'\0', name_o)
            name = data[name_o:e].decode('shift_jis')
            self.textures.append({'name': name, 'format': fmt, 'type': typ, 'mips': mips, 'w': w, 'h': h,
                                  'remap': u2, 'data': data[off:off + size]})
            o = p


def _565(c):
    return (((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31)


def decode_texture(t):
    """TPF texture level 0 -> (w, h, RGBA bytes) or None for formats not handled. PS3 DXT blocks are
    stored as on PC (little-endian colour words)."""
    w, h, fmt, d = t['w'], t['h'], t['format'], t['data']
    if fmt in (0, 1, 3, 5, 6, 0x18):   # BC1 / BC2 / BC3 by code (see TPF_BC)
        kind = TPF_BC.get(fmt)
        if kind is None:
            return None
        return w, h, decode_bc(d, w, h, kind)
    if fmt in (9, 10):   # 32-bit; PS3 stores A8R8G8B8 (swizzled when power of two)
        return w, h, decode_argb8(d, w, h)
    return None


TPF_BC = {0: 1, 1: 1, 5: 3, 6: 3, 3: 2, 0x18: 3}


def decode_bc(d, w, h, kind):
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    bs = 8 if kind == 1 else 16
    out = bytearray(w * h * 4)
    for by in range(bh):
        for bx in range(bw):
            b = d[(by * bw + bx) * bs:(by * bw + bx + 1) * bs]
            if len(b) < bs:
                continue
            cb = b if kind == 1 else b[8:]
            c0, c1 = cb[0] | cb[1] << 8, cb[2] | cb[3] << 8
            p0, p1 = _565(c0), _565(c1)
            if kind != 1 or c0 > c1:
                pal = [p0 + (255,), p1 + (255,),
                       tuple((2 * p0[k] + p1[k] + 1) // 3 for k in range(3)) + (255,),
                       tuple((p0[k] + 2 * p1[k] + 1) // 3 for k in range(3)) + (255,)]
            else:
                pal = [p0 + (255,), p1 + (255,), tuple((p0[k] + p1[k]) // 2 for k in range(3)) + (255,), (0, 0, 0, 0)]
            bits = cb[4] | cb[5] << 8 | cb[6] << 16 | cb[7] << 24
            alpha = None
            if kind == 2:
                alpha = [((b[i // 2] >> ((i & 1) * 4)) & 15) * 17 for i in range(16)]
            elif kind == 3:
                a0, a1 = b[0], b[1]
                ap = [a0, a1] + ([((7 - k) * a0 + k * a1 + 3) // 7 for k in range(1, 7)] if a0 > a1 else
                                 [((5 - k) * a0 + k * a1 + 2) // 5 for k in range(1, 5)] + [0, 255])
                ab = int.from_bytes(b[2:8], 'little')
                alpha = [ap[(ab >> (3 * i)) & 7] for i in range(16)]
            for i in range(16):
                x, y = bx * 4 + (i & 3), by * 4 + (i >> 2)
                if x >= w or y >= h:
                    continue
                c = pal[(bits >> (2 * i)) & 3]
                o = (y * w + x) * 4
                out[o:o + 3] = bytes(c[:3])
                out[o + 3] = c[3] if alpha is None else alpha[i]
    return bytes(out)


def _morton(x, y, lw, lh):
    idx = shift = 0
    while lw or lh:
        if lw:
            idx |= (x & 1) << shift; x >>= 1; shift += 1; lw -= 1
        if lh:
            idx |= (y & 1) << shift; y >>= 1; shift += 1; lh -= 1
    return idx


def decode_argb8(d, w, h):
    pot = (w & (w - 1)) == 0 and (h & (h - 1)) == 0
    lw, lh = w.bit_length() - 1, h.bit_length() - 1
    out = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            s = (_morton(x, y, lw, lh) if pot else y * w + x) * 4
            if s + 4 > len(d):
                continue
            a, r, g, b = d[s:s + 4]
            o = (y * w + x) * 4
            out[o:o + 4] = bytes((r, g, b, a))
    return bytes(out)


def write_png(path, w, h, rgba):
    def chunk(t, b):
        return struct.pack('>I', len(b)) + t + b + struct.pack('>I', zlib.crc32(t + b) & 0xFFFFFFFF)
    raw = b''.join(b'\0' + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + \
        chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(png)
