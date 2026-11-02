"""Demon's Souls model tool: export models to glTF (for Blender) and import edited ones back into the game.

usage:
  python tools/flver_tool.py export <model file> [-o <folder>]
  python tools/flver_tool.py import <edited .gltf/.glb> <model file> [--mod game_mod] [--entry N] [--delete-missing]
  python tools/flver_tool.py list <model file>
  python tools/flver_tool.py selftest [<substring>]

<model file> is any file under game\\PS3_GAME\\USRDIR holding a model: a .flver, .flver.dcx, or a
.chrbnd / .partsbnd / .objbnd (with or without .dcx). The game itself reads the .dcx copies.

export   writes <folder>\\<name>\\<name>.gltf + .bin + textures\\*.png (default folder: models\\). Open it in
         Blender with File > Import > glTF 2.0. Meshes are called m00_<material>, m01_<material>, ...;
         the skeleton comes along (characters, armour), and every vertex keeps its bone weights.
import   reads the .gltf/.glb you exported from Blender and writes a modded copy of the model file into
         <mod folder> (default game_mod, made as hard links to game\\ the first time -- no extra disk
         space, game\\ is never changed). Play it with PLAY_MODDED.bat. Each Blender object goes into the
         FLVER mesh its name starts with (m03... -> mesh 3; several objects may share one); a new object
         named after no mesh goes into a new mesh with the material its glTF material is named after.
         Meshes missing from the file are kept unless --delete-missing. Positions, normals, UVs (map 1
         and 2), vertex colours, bone weights and the triangles all come from the file; materials,
         textures and the skeleton stay as the game had them (textures: use texture packs,
         textures\\README.txt). Too many bones (28) or vertices (65535) for one mesh -> split
         automatically.
selftest checks that every model and archive in game\\ reads and writes back byte for byte, and that an
         exported model imports back to the same mesh data.

Coordinates: the game is left-handed, glTF right-handed -- X is mirrored on export and back on import.
"""
import argparse, base64, json, math, os, re, shutil, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import souls_formats as sf

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.join(BASE, 'game', 'PS3_GAME', 'USRDIR')
MAX_BONES = 28
MAX_VERTS = 0xFFFF   # 16-bit indices, 0xFFFF is the strip restart

# ------------------------------------------------------------------------------------------- math


def mmul(a, b):
    return [[a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] + a[i][3] * b[3][j] for j in range(4)]
            for i in range(4)]


def mident():
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def minv(m):
    """Inverse of an affine 4x4."""
    a, b, c = m[0][:3], m[1][:3], m[2][:3]
    det = a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])
    if abs(det) < 1e-20:
        return mident()
    inv = [[(b[1] * c[2] - b[2] * c[1]) / det, (a[2] * c[1] - a[1] * c[2]) / det, (a[1] * b[2] - a[2] * b[1]) / det],
           [(b[2] * c[0] - b[0] * c[2]) / det, (a[0] * c[2] - a[2] * c[0]) / det, (a[2] * b[0] - a[0] * b[2]) / det],
           [(b[0] * c[1] - b[1] * c[0]) / det, (a[1] * c[0] - a[0] * c[1]) / det, (a[0] * b[1] - a[1] * b[0]) / det]]
    t = [m[0][3], m[1][3], m[2][3]]
    out = [inv[i] + [-(inv[i][0] * t[0] + inv[i][1] * t[1] + inv[i][2] * t[2])] for i in range(3)]
    return out + [[0.0, 0.0, 0.0, 1.0]]


def xform(m, p):
    return (m[0][0] * p[0] + m[0][1] * p[1] + m[0][2] * p[2] + m[0][3],
            m[1][0] * p[0] + m[1][1] * p[1] + m[1][2] * p[2] + m[1][3],
            m[2][0] * p[0] + m[2][1] * p[1] + m[2][2] * p[2] + m[2][3])


def xdir(m, v):
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


def normal_matrix(m):
    """Inverse transpose of m's 3x3, as a 4x4 for xdir (normals stay perpendicular under any scale)."""
    inv = minv(m)
    return [[inv[0][0], inv[1][0], inv[2][0], 0.0], [inv[0][1], inv[1][1], inv[2][1], 0.0],
            [inv[0][2], inv[1][2], inv[2][2], 0.0], [0.0, 0.0, 0.0, 1.0]]


def norm(v):
    l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / l, v[1] / l, v[2] / l) if l > 1e-12 else (0.0, 1.0, 0.0)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def qmul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def mat_from_trs(t, q, s):
    x, y, z, w = q
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    return [[r[i][0] * s[0], r[i][1] * s[1], r[i][2] * s[2], t[i]] for i in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


MIRROR = [[-1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]


def mirror_m(m):
    return mmul(MIRROR, mmul(m, MIRROR))


def mirror_p(p):
    return (-p[0], p[1], p[2])


# ------------------------------------------------------------------------------------------- bones


def bone_trs(b):
    r = b['raw']
    t = struct.unpack_from('>3f', r, 0x00)
    rot = struct.unpack_from('>3f', r, 0x10)
    parent = struct.unpack_from('>h', r, 0x1C)[0]
    s = struct.unpack_from('>3f', r, 0x20)
    return t, rot, parent, s


def bone_quat(rot):
    """FromSoft bone rotation (radians, applied X then Z then Y) -> quaternion (x, y, z, w)."""
    qx = (math.sin(rot[0] / 2), 0.0, 0.0, math.cos(rot[0] / 2))
    qy = (0.0, math.sin(rot[1] / 2), 0.0, math.cos(rot[1] / 2))
    qz = (0.0, 0.0, math.sin(rot[2] / 2), math.cos(rot[2] / 2))
    return qmul(qy, qmul(qz, qx))


def bone_worlds(fl):
    """Bind-pose world matrices of every bone (game space)."""
    out = [None] * len(fl.bones)

    def world(i, depth=0):
        if out[i] is not None:
            return out[i]
        t, rot, parent, s = bone_trs(fl.bones[i])
        L = mat_from_trs(t, bone_quat(rot), s)
        out[i] = mmul(world(parent, depth + 1), L) if 0 <= parent < len(fl.bones) and parent != i and depth < 256 else L
        return out[i]
    for i in range(len(fl.bones)):
        world(i)
    return out


def orthonormal(m):
    """m without scale/shear: Gram-Schmidt on the 3x3 columns, translation kept."""
    c0 = norm((m[0][0], m[1][0], m[2][0]))
    c1 = (m[0][1], m[1][1], m[2][1])
    d = dot(c1, c0)
    c1 = norm((c1[0] - c0[0] * d, c1[1] - c0[1] * d, c1[2] - c0[2] * d))
    c2 = cross(c0, c1)   # always a proper rotation (a mirrored bone's flip stays in the vertex positions)
    return [[c0[0], c1[0], c2[0], m[0][3]], [c0[1], c1[1], c2[1], m[1][3]],
            [c0[2], c1[2], c2[2], m[2][3]], [0.0, 0.0, 0.0, 1.0]]


def mat_to_quat(m):
    """Rotation part of an orthonormal 4x4 -> unit quaternion (x, y, z, w)."""
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = ((m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s)
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = (0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s)
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = ((m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s)
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = ((m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s, (m[1][0] - m[0][1]) / s)
    l = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / l for c in q)


def material_names(fl):
    """Unique glTF material names: the FLVER name, plus #index when a name repeats (Blender would
    otherwise make them X / X.001 and a new object could land on the wrong one)."""
    seen = {}
    for m in fl.materials:
        seen[m['name']] = seen.get(m['name'], 0) + 1
    return [m['name'] if seen[m['name']] == 1 else '%s#%d' % (m['name'], i) for i, m in enumerate(fl.materials)]


def joint_names(fl):
    """Unique glTF joint names: the bone name, plus #index when a name repeats."""
    seen = {}
    for b in fl.bones:
        seen[b['name']] = seen.get(b['name'], 0) + 1
    return [b['name'] if seen[b['name']] == 1 else '%s#%d' % (b['name'], i) for i, b in enumerate(fl.bones)]


# ------------------------------------------------------------------------------------------- vertices


def layout_of(fl, me):
    if len(me['vbufs']['buffers']) != 1:
        raise ValueError('mesh with %d vertex buffers is not supported' % len(me['vbufs']['buffers']))
    b = me['vbufs']['buffers'][0]
    return fl.materials[me['material']]['layouts'][b['layout']], b['data']


def decode_vertices(fl, me):
    """-> list of dicts: pos, normal, tangent (x,y,z,w), bitangent, color (r,g,b,a 0-255), uv [..],
    bones (4 local table indices), weights (4 floats), all in the mesh's own space."""
    L, buf = layout_of(fl, me)
    E = fl.E
    S = L['size']
    out = []
    for v in range(me['vertex_count']):
        o = v * S
        d = {'uv': [], 'bones': (0, 0, 0, 0), 'weights': None}
        for _, off, typ, sem, idx in L['members']:
            p = o + off
            if sem == sf.SEM_POSITION:
                d['pos'] = struct.unpack_from(E + '3f', buf, p)
            elif sem == sf.SEM_BONES:
                d['bones'] = tuple(buf[p:p + 4]) if typ in (0x2F, 0x11, 0x10, 0x13) else struct.unpack_from(E + '4h', buf, p)
            elif sem == sf.SEM_WEIGHTS:
                if typ == 0x1A:
                    d['weights'] = tuple(x / 32767 for x in struct.unpack_from(E + '4h', buf, p))
                elif typ in (0x10, 0x11, 0x13, 0x2F):
                    d['weights'] = tuple(x / 255 for x in buf[p:p + 4])
                else:
                    d['weights'] = struct.unpack_from(E + '4f', buf, p)
            elif sem in (sf.SEM_NORMAL, sf.SEM_TANGENT, sf.SEM_BITANGENT):
                if typ == 0x02:
                    x, y, z = struct.unpack_from(E + '3f', buf, p); w = 1.0
                elif typ == 0x03:
                    x, y, z, w = struct.unpack_from(E + '4f', buf, p)
                elif typ == 0x1A:
                    x, y, z, w = (c / 32767 for c in struct.unpack_from(E + '4h', buf, p))
                else:
                    x, y, z, w = ((c - 127) / 127 for c in buf[p:p + 4])
                key = {sf.SEM_NORMAL: 'normal', sf.SEM_TANGENT: 'tangent', sf.SEM_BITANGENT: 'bitangent'}[sem]
                d[key] = (x, y, z, w)
            elif sem == sf.SEM_COLOR:
                d['color'] = tuple(buf[p:p + 4]) if typ != 0x03 else tuple(
                    max(0, min(255, round(c * 255))) for c in struct.unpack_from(E + '4f', buf, p))
            elif sem == sf.SEM_UV:
                if typ == 0x15:
                    d['uv'].append(tuple(c / 1024 for c in struct.unpack_from(E + '2h', buf, p)))
                elif typ == 0x16:
                    u = struct.unpack_from(E + '4h', buf, p)
                    d['uv'] += [(u[0] / 1024, u[1] / 1024), (u[2] / 1024, u[3] / 1024)]
                elif typ == 0x01:
                    d['uv'].append(struct.unpack_from(E + '2f', buf, p))
        out.append(d)
    return out


def encode_vertices(fl, me, verts):
    """Inverse of decode_vertices into the mesh's layout. verts carry the same keys."""
    L, _ = layout_of(fl, me)
    E = fl.E
    S = L['size']
    buf = bytearray(S * len(verts))

    def b127(c):
        return max(0, min(254, int(round(c * 127 + 127))))

    def s16(c, scale):
        return max(-32768, min(32767, int(round(c * scale))))
    for v, d in enumerate(verts):
        o = v * S
        uvs = d['uv']
        uv_i = 0
        for _, off, typ, sem, idx in L['members']:
            p = o + off
            if sem == sf.SEM_POSITION:
                struct.pack_into(E + '3f', buf, p, *d['pos'])
            elif sem == sf.SEM_BONES:
                if typ in (0x2F, 0x11, 0x10, 0x13):
                    buf[p:p + 4] = bytes(d['bones'])
                else:
                    struct.pack_into(E + '4h', buf, p, *d['bones'])
            elif sem == sf.SEM_WEIGHTS:
                w = d['weights'] or (1.0, 0.0, 0.0, 0.0)
                if typ == 0x1A:
                    q = [int(round(x * 32767)) for x in w]
                    q[0] += 32767 - sum(q)          # keep the sum exact
                    struct.pack_into(E + '4h', buf, p, *[max(0, min(32767, x)) for x in q])
                elif typ in (0x10, 0x11, 0x13, 0x2F):
                    q = [int(round(x * 255)) for x in w]; q[0] += 255 - sum(q)
                    buf[p:p + 4] = bytes(max(0, min(255, x)) for x in q)
                else:
                    struct.pack_into(E + '4f', buf, p, *w)
            elif sem in (sf.SEM_NORMAL, sf.SEM_TANGENT, sf.SEM_BITANGENT):
                key = {sf.SEM_NORMAL: 'normal', sf.SEM_TANGENT: 'tangent', sf.SEM_BITANGENT: 'bitangent'}[sem]
                x, y, z, w = d[key]
                if typ == 0x02:
                    struct.pack_into(E + '3f', buf, p, x, y, z)
                elif typ == 0x03:
                    struct.pack_into(E + '4f', buf, p, x, y, z, w)
                elif typ == 0x1A:
                    struct.pack_into(E + '4h', buf, p, s16(x, 32767), s16(y, 32767), s16(z, 32767), s16(w, 32767))
                else:
                    buf[p:p + 4] = bytes((b127(x), b127(y), b127(z), b127(w)))
            elif sem == sf.SEM_COLOR:
                c = d['color']
                if typ == 0x03:
                    struct.pack_into(E + '4f', buf, p, *(x / 255 for x in c))
                else:
                    buf[p:p + 4] = bytes(c)
            elif sem == sf.SEM_UV:
                if typ == 0x15:
                    u = uvs[uv_i] if uv_i < len(uvs) else (0.0, 0.0); uv_i += 1
                    struct.pack_into(E + '2h', buf, p, s16(u[0], 1024), s16(u[1], 1024))
                elif typ == 0x16:
                    u0 = uvs[uv_i] if uv_i < len(uvs) else (0.0, 0.0)
                    u1 = uvs[uv_i + 1] if uv_i + 1 < len(uvs) else u0
                    uv_i += 2
                    struct.pack_into(E + '4h', buf, p, s16(u0[0], 1024), s16(u0[1], 1024), s16(u1[0], 1024), s16(u1[1], 1024))
                elif typ == 0x01:
                    u = uvs[uv_i] if uv_i < len(uvs) else (0.0, 0.0); uv_i += 1
                    struct.pack_into(E + '2f', buf, p, *u)
    return bytes(buf)


def mesh_bone(me, local_idx, nbones):
    """Global bone of a vertex's local bone index (the mesh's 28-entry table), else the mesh's default
    bone -- a GLOBAL bone (the model's own node bone on skinned parts: bd_f_5010 -> 91 'BD_F_5010';
    0 = the root on map pieces), else table[0]. Import keeps the game's default bone as it was."""
    if 0 <= local_idx < MAX_BONES and 0 <= me['bone_indices'][local_idx] < nbones:
        return me['bone_indices'][local_idx]
    if 0 <= me['default_bone'] < nbones:
        return me['default_bone']
    return me['bone_indices'][0] if 0 <= me['bone_indices'][0] < nbones else 0


def bitangent_sign(fl):
    """Does the game store bitangent = cross(N, T) * w (+1) or cross(T, N) * w (-1)? Majority vote over
    the model's own vertices; +1 when it has none."""
    votes = 0
    for me in fl.meshes:
        L, _ = layout_of(fl, me)
        if not any(m[3] == sf.SEM_BITANGENT for m in L['members']):
            continue
        for d in decode_vertices(fl, me)[:500]:
            if 'normal' in d and 'tangent' in d and 'bitangent' in d:
                c = cross(d['normal'][:3], d['tangent'][:3])
                votes += 1 if dot(c, d['bitangent'][:3]) * (d['tangent'][3] or 1) >= 0 else -1
    return 1 if votes >= 0 else -1


# ------------------------------------------------------------------------------------------- containers


class ModelFile:
    """A model file in the game: chains DCX -> BND3 -> FLVER entries, and TPFs found with it."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        raw = open(self.path, 'rb').read()
        self.dcx = None
        if raw[:4] in (b'DCX\0', b'DCP\0'):
            raw, self.dcx = sf.dcx_decompress(raw)
        self.bnd = None
        self.flvers = []          # (label, Flver0, bnd entry index or None)
        self.tpfs = []
        if raw[:4] == b'BND3':
            self.bnd = sf.Bnd3(raw)
            for i, e in enumerate(self.bnd.entries):
                n = (e['name'] or '').lower()
                if n.endswith('.flver'):
                    self.flvers.append((e['name'].split('\\')[-1], sf.Flver0(e['data']), i))
                elif n.endswith('.tpf'):
                    try:
                        self.tpfs.append(sf.Tpf(e['data']))
                    except ValueError:
                        pass
        elif raw[:6] == b'FLVER\0':
            self.flvers.append((os.path.basename(self.path).split('.')[0] + '.flver', sf.Flver0(raw), None))
        else:
            raise SystemExit('%s holds no model (not a FLVER or BND3)' % path)

    def rebuilt(self, which, flver_bytes):
        """The whole file again with flver `which` replaced, in its original packing."""
        label, fl, bi = self.flvers[which]
        if self.bnd is not None:
            self.bnd.entries[bi]['data'] = flver_bytes
            raw = self.bnd.write()
        else:
            raw = flver_bytes
        return sf.dcx_compress(raw, self.dcx) if self.dcx else raw


_tpf_cache = {}


def load_tpf_file(p):
    if p not in _tpf_cache:
        try:
            raw = open(p, 'rb').read()
            if raw[:4] in (b'DCX\0', b'DCP\0'):
                raw, _ = sf.dcx_decompress(raw)
            _tpf_cache[p] = sf.Tpf(raw)
        except (OSError, ValueError):
            _tpf_cache[p] = None
    return _tpf_cache[p]


def texture_index(mf):
    """name (lower, no extension) -> TPF texture, from the model file itself, a .tpf next to it, and for map
    pieces the area's texture files (MAP\\mXX\\*.tpf)."""
    idx = {}
    tpfs = list(mf.tpfs)
    d = os.path.dirname(mf.path)
    stem = os.path.basename(mf.path).split('.')[0]
    for ext in ('.tpf', '.tpf.dcx'):
        t = load_tpf_file(os.path.join(d, stem + ext))
        if t:
            tpfs.append(t)
    parts = os.path.normpath(mf.path).split(os.sep)
    up = [p.upper() for p in parts]
    if 'MAP' in up:
        i = up.index('MAP')
        if i + 1 < len(parts):
            area = parts[i + 1][:3]        # M01_00_00_00 -> M01
            ad = os.path.join(os.sep.join(parts[:i + 1]), area)
            if os.path.isdir(ad):
                for f in sorted(os.listdir(ad)):
                    if f.lower().endswith('.tpf') or (f.lower().endswith('.tpf.dcx') and
                                                      not os.path.exists(os.path.join(ad, f[:-4]))):
                        t = load_tpf_file(os.path.join(ad, f))
                        if t:
                            tpfs.append(t)
    for t in tpfs:
        for x in t.textures:
            idx.setdefault(x['name'].lower(), x)
    return idx


def tex_key(path):
    return re.split(r'[\\/]', path)[-1].rsplit('.', 1)[0].lower()


# ------------------------------------------------------------------------------------------- export


class GltfWriter:
    def __init__(self):
        self.bin = bytearray()
        self.g = {'asset': {'version': '2.0', 'generator': 'Demon\'s Souls flver_tool'}, 'buffers': [],
                  'bufferViews': [], 'accessors': [], 'meshes': [], 'nodes': [], 'scenes': [{'nodes': []}],
                  'scene': 0, 'materials': [], 'skins': [], 'textures': [], 'images': [], 'samplers': [
                      {'magFilter': 9729, 'minFilter': 9987, 'wrapS': 10497, 'wrapT': 10497}]}

    def accessor(self, fmt, ncomp, rows, ctype, atype, target=None, minmax=False, normalized=False):
        while len(self.bin) % 4:
            self.bin += b'\0'
        off = len(self.bin)
        for r in rows:
            self.bin += struct.pack('<' + fmt * ncomp, *r) if ncomp > 1 else struct.pack('<' + fmt, r)
        bv = {'buffer': 0, 'byteOffset': off, 'byteLength': len(self.bin) - off}
        if target:
            bv['target'] = target
        self.g['bufferViews'].append(bv)
        a = {'bufferView': len(self.g['bufferViews']) - 1, 'componentType': ctype, 'count': len(rows), 'type': atype}
        if normalized:
            a['normalized'] = True
        if minmax and rows:
            cols = list(zip(*rows)) if ncomp > 1 else [rows]
            a['min'] = [min(c) for c in cols]
            a['max'] = [max(c) for c in cols]
        self.g['accessors'].append(a)
        return len(self.g['accessors']) - 1


def export_model(model_path, out_dir, textures=True):
    mf = ModelFile(model_path)
    if not mf.flvers:
        raise SystemExit('no FLVER in %s' % model_path)
    texidx = texture_index(mf)
    written = []
    for fi, (label, fl, _) in enumerate(mf.flvers):
        name = label.rsplit('.', 1)[0]
        if len(mf.flvers) > 1:
            name = '%s_%d' % (name, fi)
        od = os.path.join(out_dir, name)
        os.makedirs(os.path.join(od, 'textures'), exist_ok=True)
        if not fl.meshes:
            print('  %s: no meshes (a skeleton-only file) -- skipped' % label)
            continue
        gw = GltfWriter()
        g = gw.g
        worlds = bone_worlds(fl)
        nmats = [normal_matrix(w) for w in worlds]
        jn = joint_names(fl)
        nb = len(fl.bones)
        # bone nodes. The skeleton goes out without scale (a Blender armature's rest pose cannot hold
        # bone scale, so a scaled bone came back from Blender wrong and moved its vertices); vertices
        # are still placed with the real, scaled bone matrices, and import uses joint world x inverse
        # bind, so the scale never needs to make the trip.
        wm = [mirror_m(orthonormal(w)) for w in worlds]
        children = {i: [] for i in range(nb)}
        roots = []
        for i, b in enumerate(fl.bones):
            parent = bone_trs(b)[2]
            has_parent = 0 <= parent < nb and parent != i
            L = mmul(minv(wm[parent]), wm[i]) if has_parent else wm[i]
            q = mat_to_quat(L)
            node = {'name': jn[i], 'translation': [L[0][3], L[1][3], L[2][3]], 'rotation': list(q)}
            g['nodes'].append(node)
            if has_parent:
                children[parent].append(i)
            else:
                roots.append(i)
        for i, ch in children.items():
            if ch:
                g['nodes'][i]['children'] = ch
        if nb:
            ibm = gw.accessor('f', 16, [tuple(minv(w)[r][c] for c in range(4) for r in range(4)) for w in wm],
                              5126, 'MAT4')
            g['skins'].append({'joints': list(range(nb)), 'inverseBindMatrices': ibm, 'skeleton': roots[0],
                               'name': name + '_skeleton'})
        g['scenes'][0]['nodes'] += roots
        # materials and textures
        img_of = {}

        def texture(path):
            k = tex_key(path)
            if k in img_of:
                return img_of[k]
            t = texidx.get(k)
            img_of[k] = None
            if t is None or t['type'] != 0 or not textures:
                return None
            dec = sf.decode_texture(t)
            if dec is None:
                return None
            w, h, rgba = dec
            fn = 'textures/%s.png' % k
            sf.write_png(os.path.join(od, fn), w, h, rgba)
            g['images'].append({'uri': fn, 'name': k})
            g['textures'].append({'source': len(g['images']) - 1, 'sampler': 0})
            img_of[k] = (len(g['textures']) - 1, any(rgba[i] < 250 for i in range(3, len(rgba), 4)))
            return img_of[k]
        mnames = material_names(fl)
        for mi, m in enumerate(fl.materials):
            mat = {'name': mnames[mi], 'pbrMetallicRoughness': {'metallicFactor': 0.0, 'roughnessFactor': 1.0},
                   'extras': {'flver_material': mi, 'mtd': m['mtd'],
                              'textures': {(t['type'] or 'slot%d' % k): t['path'] for k, t in enumerate(m['textures'])}}}
            for t in m['textures']:
                ty = (t['type'] or '').lower()
                if ty.startswith('g_diffuse') and 'baseColorTexture' not in mat['pbrMetallicRoughness']:
                    r = texture(t['path'])
                    if r:
                        mat['pbrMetallicRoughness']['baseColorTexture'] = {'index': r[0]}
                        if r[1]:
                            mat['alphaMode'] = 'MASK'
                            mat['alphaCutoff'] = 0.5
                elif ty.startswith('g_bumpmap') and 'normalTexture' not in mat:
                    r = texture(t['path'])
                    if r:
                        mat['normalTexture'] = {'index': r[0]}
            g['materials'].append(mat)
        # meshes
        for mi, me in enumerate(fl.meshes):
            verts = decode_vertices(fl, me)
            pos, nrm, col, j4, w4 = [], [], [], [], []
            nuv = max((len(d['uv']) for d in verts), default=0)
            uvs = [[] for _ in range(nuv)]
            for d in verts:
                if me['dynamic']:
                    p = d['pos']
                    n = d.get('normal', (0, 1, 0, 1))[:3]
                    ws = d['weights'] or (1.0, 0.0, 0.0, 0.0)
                    if sum(ws) <= 0:   # all-zero weights: bound to its first bone (glTF needs a sum of 1)
                        ws = (1.0, 0.0, 0.0, 0.0)
                    js = [mesh_bone(me, d['bones'][k], nb) if ws[k] > 0 else 0 for k in range(4)]
                else:   # rigid: stored in the space of its bone
                    bone = mesh_bone(me, d['bones'][0], nb)
                    W = worlds[bone] if nb else mident()
                    p = xform(W, d['pos'])
                    n = norm(xdir(nmats[bone], d.get('normal', (0, 1, 0, 1))[:3])) if nb else d.get('normal', (0, 1, 0, 1))[:3]
                    js, ws = [bone, 0, 0, 0], (1.0, 0.0, 0.0, 0.0)
                # no TANGENT: glTF means MikkTSpace dP/du there, the game stores its own (rebuilt on import)
                pos.append(mirror_p(p))
                nrm.append(norm(mirror_p(n)))
                col.append(tuple(c / 255 for c in d.get('color', (255, 255, 255, 255))))
                sw = sum(ws)
                w4.append(tuple(x / sw for x in ws))
                j4.append(tuple(js))
                for k in range(nuv):
                    uvs[k].append(d['uv'][k] if k < len(d['uv']) else (0.0, 0.0))
            tris = [t for t in sf.strip_triangles(me['indices']) if t[0] != t[1] and t[1] != t[2] and t[0] != t[2]]
            attrs = {'POSITION': gw.accessor('f', 3, pos, 5126, 'VEC3', 34962, minmax=True),
                     'NORMAL': gw.accessor('f', 3, nrm, 5126, 'VEC3', 34962),
                     'COLOR_0': gw.accessor('f', 4, col, 5126, 'VEC4', 34962)}
            for k in range(nuv):
                attrs['TEXCOORD_%d' % k] = gw.accessor('f', 2, uvs[k], 5126, 'VEC2', 34962)
            if nb:
                attrs['JOINTS_0'] = gw.accessor('H', 4, j4, 5123, 'VEC4', 34962)
                attrs['WEIGHTS_0'] = gw.accessor('f', 4, w4, 5126, 'VEC4', 34962)
            flat = [i for t in tris for i in t]
            ind = gw.accessor('I' if len(verts) > 65535 else 'H', 1, flat,
                              5125 if len(verts) > 65535 else 5123, 'SCALAR', 34963)
            mname = 'm%02d_%s' % (mi, re.sub(r'[^A-Za-z0-9_#\-]+', '_', mnames[me['material']]))
            g['meshes'].append({'name': mname, 'primitives': [{'attributes': attrs, 'indices': ind,
                                                               'material': me['material'], 'mode': 4}],
                                'extras': {'flver_mesh': mi, 'dynamic': me['dynamic']}})
            node = {'name': mname, 'mesh': len(g['meshes']) - 1}
            if nb:
                node['skin'] = 0
            g['nodes'].append(node)
            g['scenes'][0]['nodes'].append(len(g['nodes']) - 1)
        g['buffers'].append({'byteLength': len(gw.bin), 'uri': name + '.bin'})
        g['extras'] = {'flver_tool': 1, 'source': os.path.relpath(mf.path, BASE) if mf.path.startswith(BASE) else mf.path,
                       'flver': label}
        for k in ('skins', 'textures', 'images'):
            if not g[k]:
                del g[k]
        if not g.get('textures'):
            del g['samplers']
        with open(os.path.join(od, name + '.bin'), 'wb') as f:
            f.write(gw.bin)
        with open(os.path.join(od, name + '.gltf'), 'w', encoding='utf-8') as f:
            json.dump(g, f, indent=1)
        written.append(os.path.join(od, name + '.gltf'))
        print('  %s: %d meshes, %d bones, %d textures -> %s' % (label, len(fl.meshes), nb, len(g.get('images', [])),
                                                                 os.path.join(od, name + '.gltf')))
    return written


# ------------------------------------------------------------------------------------------- glTF reading


COMP = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2), 5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
NORM_DIV = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}


def load_gltf(path):
    raw = open(path, 'rb').read()
    bins = []
    if raw[:4] == b'glTF':
        o = 12
        g = None
        while o < len(raw):
            ln, typ = struct.unpack_from('<II', raw, o)
            chunk = raw[o + 8:o + 8 + ln]
            if typ == 0x4E4F534A:
                g = json.loads(chunk.decode('utf-8'))
            elif typ == 0x004E4942:
                bins.append(chunk)
            o += 8 + ln
    else:
        g = json.loads(raw.decode('utf-8'))
    known = {'KHR_materials_emissive_strength', 'KHR_texture_transform', 'KHR_materials_specular',
             'KHR_materials_ior', 'KHR_materials_transmission', 'KHR_materials_volume', 'KHR_materials_clearcoat',
             'KHR_materials_sheen', 'KHR_materials_unlit', 'KHR_lights_punctual'}
    for ext in g.get('extensionsRequired', []) + g.get('extensionsUsed', []):
        if ext in ('KHR_draco_mesh_compression', 'EXT_meshopt_compression', 'KHR_mesh_quantization'):
            raise SystemExit('%s uses %s -- export again with compression / quantisation off' % (path, ext))
        if ext in g.get('extensionsRequired', []) and ext not in known:
            raise SystemExit('%s needs the glTF extension %s, which this tool cannot read' % (path, ext))
    buffers = []
    for i, b in enumerate(g.get('buffers', [])):
        uri = b.get('uri')
        if uri is None:
            buffers.append(bins[0] if bins else b'')
        elif uri.startswith('data:'):
            buffers.append(base64.b64decode(uri.split(',', 1)[1]))
        else:
            from urllib.parse import unquote
            buffers.append(open(os.path.join(os.path.dirname(path), unquote(uri)), 'rb').read())
    return g, buffers


def read_accessor(g, buffers, ai):
    a = g['accessors'][ai]
    fmt, size = COMP[a['componentType']]
    n = NCOMP[a['type']]
    count = a['count']
    if 'bufferView' not in a:
        if 'sparse' not in a:
            raise SystemExit('a glTF accessor has no data (compressed export?) -- export again without compression')
        rows = [tuple([0] * n) for _ in range(count)]
    else:
        bv = g['bufferViews'][a['bufferView']]
        data = buffers[bv['buffer']]
        base = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
        stride = bv.get('byteStride') or size * n
        rows = [struct.unpack_from('<' + fmt * n, data, base + i * stride) for i in range(count)]
    if a.get('normalized') and a['componentType'] in NORM_DIV:
        dv = NORM_DIV[a['componentType']]
        rows = [tuple(max(-1.0, c / dv) for c in r) for r in rows]
    if 'sparse' in a:
        raise SystemExit('sparse glTF accessors are not supported -- export again without them')
    return [r[0] for r in rows] if n == 1 else rows


def node_worlds(g):
    nodes = g.get('nodes', [])
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get('children', []):
            parent[c] = i
    local = []
    for n in nodes:
        if 'matrix' in n:
            m = n['matrix']
            local.append([[m[c * 4 + r] for c in range(4)] for r in range(4)])
        else:
            local.append(mat_from_trs(n.get('translation', [0, 0, 0]), n.get('rotation', [0, 0, 0, 1]),
                                      n.get('scale', [1, 1, 1])))
    out = [None] * len(nodes)

    def world(i):
        if out[i] is None:
            out[i] = mmul(world(parent[i]), local[i]) if i in parent else local[i]
        return out[i]
    for i in range(len(nodes)):
        world(i)
    return out, parent


# ------------------------------------------------------------------------------------------- import


def triangles_to_strip(tris):
    """Triangles -> triangle strips joined by the 0xFFFF restart, greedy along shared edges, like the
    game's own data (about 2 indices per triangle). Winding as sf.strip_triangles decodes it: triangle
    k of a run is (v[k], v[k+1], v[k+2]) for even k and (v[k+1], v[k], v[k+2]) for odd k, so the next
    triangle must hold the directed edge (v[-1], v[-2]) when it will be odd, (v[-2], v[-1]) when even."""
    by_edge = {}
    for t, (a, b, c) in enumerate(tris):
        for e in ((a, b), (b, c), (c, a)):
            by_edge.setdefault(e, []).append(t)
    used = [False] * len(tris)

    def third(t, p, q):
        a, b, c = tris[t]
        for x, y, z in ((a, b, c), (b, c, a), (c, a, b)):
            if x == p and y == q:
                return z
        return None

    def grow(strip, mark):
        taken = set()
        while True:
            k = len(strip) - 2            # index of the triangle to add
            p, q = (strip[-1], strip[-2]) if k & 1 else (strip[-2], strip[-1])
            nxt = None
            for t in by_edge.get((p, q), ()):
                if not used[t] and t not in taken:
                    nxt = t
                    break
            if nxt is None:
                return taken
            z = third(nxt, p, q)
            if z is None:
                return taken
            strip.append(z)
            taken.add(nxt)
            if mark:
                used[nxt] = True
    out = []
    for t in range(len(tris)):
        if used[t]:
            continue
        a, b, c = tris[t]
        used[t] = True
        best = None
        for rot in ((a, b, c), (b, c, a), (c, a, b)):   # keep the start rotation that runs longest
            trial = list(rot)
            n = len(grow(trial, False))
            if best is None or n > best[0]:
                best = (n, rot)
        strip = list(best[1])
        grow(strip, True)
        if out:
            out.append(0xFFFF)
        out += strip
    return out


def import_model(gltf_path, model_path, mod_root, entry=None, delete_missing=False, dry=False, quiet=False):
    g, buffers = load_gltf(gltf_path)
    src = os.path.abspath(model_path)
    rel = None
    roots = [GAME] + ([mod_paths(mod_root)[1]] if mod_root else [])
    for r in roots:   # the original in game\, or the version in the mod copy it was exported from
        if os.path.normcase(src).startswith(os.path.normcase(os.path.abspath(r)) + os.sep):
            rel = os.path.relpath(src, r)
    if rel is None and not dry:
        raise SystemExit('the model file must be under %s (or the same file in the mod copy)' % GAME)
    mf = ModelFile(src)
    if entry is None:
        if len(mf.flvers) != 1:
            raise SystemExit('%s holds %d models; pick one with --entry (0..%d)' % (model_path, len(mf.flvers),
                                                                                 len(mf.flvers) - 1))
        entry = 0
    if not 0 <= entry < len(mf.flvers):
        raise SystemExit('--entry %d: %s holds models 0..%d' % (entry, model_path, len(mf.flvers) - 1))
    label, fl, _ = mf.flvers[entry]
    worlds = bone_worlds(fl)
    nb = len(fl.bones)
    jn = joint_names(fl)
    bone_by_name = {n: i for i, n in enumerate(jn)}
    for i, b in enumerate(fl.bones):
        bone_by_name.setdefault(b['name'], i)
    bsign = bitangent_sign(fl)
    gworld, gparent = node_worlds(g)
    nodes = g.get('nodes', [])
    mat_by_name = {}
    for i, n in enumerate(material_names(fl)):   # unique export names first, then plain FLVER names
        mat_by_name[n] = i
    for i, m in enumerate(fl.materials):
        mat_by_name.setdefault(m['name'], i)

    def prim_material(prim):
        """FLVER material a glTF primitive's material stands for, or None."""
        if 'material' not in prim:
            return None
        gmat = g['materials'][prim['material']]
        fm = (gmat.get('extras') or {}).get('flver_material')
        if isinstance(fm, int) and 0 <= fm < len(fl.materials):
            return fm
        nm = gmat.get('name', '')
        if nm in mat_by_name:
            return mat_by_name[nm]
        return mat_by_name.get(re.sub(r'\.\d{3}$', '', nm))

    # glTF joint node -> FLVER bone (by name; Blender keeps bone names)
    def node_bone(ni):
        nm = nodes[ni].get('name', '')
        if nm in bone_by_name:
            return bone_by_name[nm]
        nm2 = re.sub(r'\.\d{3}$', '', nm)
        return bone_by_name.get(nm2)

    def node_target(node):
        """FLVER mesh an object's name points at (m03... -> 3), or None."""
        for nm in (node.get('name', ''), g['meshes'][node['mesh']].get('name', '')):
            mt = re.match(r'^m(\d+)', nm)
            if mt and int(mt.group(1)) < len(fl.meshes):
                return int(mt.group(1))
        return None
    present = {node_target(n) for n in nodes if 'mesh' in n} - {None}
    groups = {}      # FLVER mesh index (or ('new', material)) -> list of vertex/triangle sets
    for ni, node in enumerate(nodes):
        if 'mesh' not in node:
            continue
        gm = g['meshes'][node['mesh']]
        target = node_target(node)
        skin = g['skins'][node['skin']] if 'skin' in node else None
        if skin:
            jworld = [gworld[j] for j in skin['joints']]
            ibm = read_accessor(g, buffers, skin['inverseBindMatrices']) if 'inverseBindMatrices' in skin else None
            ibm = [[[m[c * 4 + r] for c in range(4)] for r in range(4)] for m in ibm] if ibm else [mident()] * len(jworld)
            jmat = [mmul(jworld[k], ibm[k]) for k in range(len(jworld))]
            jbone = [node_bone(j) for j in skin['joints']]
            rigid = None
        else:
            # no skin (exported without the armature, or parented to a bone): rigid to the nearest
            # ancestor that is a bone, else the target mesh's default bone (resolved below)
            anc, rigid = gparent.get(ni), None
            while anc is not None and rigid is None:
                rigid = node_bone(anc)
                anc = gparent.get(anc)
        for prim in gm['primitives']:
            if prim.get('mode', 4) != 4:
                raise SystemExit('object %s has non-triangle faces -- triangulate it in Blender' % node.get('name'))
            t = target
            pm = prim_material(prim)
            if t is not None and pm is not None and pm != fl.meshes[t]['material']:
                # this face set has another of the model's materials: put it with a mesh in the file that
                # uses it (never one left out of the export -- that would overwrite it), else a new mesh
                t = next((i for i in sorted(present) if fl.meshes[i]['material'] == pm), ('new', pm))
                if not quiet:
                    print('  note: part of "%s" uses material %s -- imported into %s' % (
                        node.get('name'), fl.materials[pm]['name'], 'm%02d' % t if isinstance(t, int) else 'a new mesh'))
            if t is None:
                if pm is None:
                    raise SystemExit('object "%s": name it after a mesh (m00_..., m01_...) or give it one of the '
                                     'model\'s materials (%s)' % (node.get('name'), ', '.join(material_names(fl))))
                t = ('new', pm)
            A = prim['attributes']
            P = read_accessor(g, buffers, A['POSITION'])
            N = read_accessor(g, buffers, A['NORMAL']) if 'NORMAL' in A else None
            # TANGENT is ignored: glTF's is MikkTSpace dP/du, the game's its own -- rebuilt in fill_missing
            C = read_accessor(g, buffers, A['COLOR_0']) if 'COLOR_0' in A else None
            UV = []
            k = 0
            while 'TEXCOORD_%d' % k in A:
                UV.append(read_accessor(g, buffers, A['TEXCOORD_%d' % k])); k += 1
            J = read_accessor(g, buffers, A['JOINTS_0']) if 'JOINTS_0' in A and skin else None
            W = read_accessor(g, buffers, A['WEIGHTS_0']) if 'WEIGHTS_0' in A and skin else None
            I = read_accessor(g, buffers, prim['indices']) if 'indices' in prim else list(range(len(P)))
            node_nm = normal_matrix(gworld[ni])
            verts = []
            for v in range(len(P)):
                if J is not None:
                    infl = [(J[v][k], W[v][k]) for k in range(4) if W[v][k] > 1e-6]
                    tot = sum(w for _, w in infl) or 1.0
                    infl = [(j, w / tot) for j, w in infl] or [(0, 1.0)]
                    M = [[sum(jmat[j][r][c] * w for j, w in infl) for c in range(4)] for r in range(4)]
                    bones = []
                    for j, w in infl:
                        b = jbone[j] if j < len(jbone) else None
                        if b is None:
                            raise SystemExit('object "%s" is weighted to bone "%s", which the game model does not '
                                             'have' % (node.get('name'), nodes[skin['joints'][j]].get('name')))
                        bones.append((b, w))
                else:
                    M = gworld[ni]
                    bones = [(rigid, 1.0)] if rigid is not None else None
                p = mirror_p(xform(M, P[v]))
                if N:   # skinned: blend of rigid joint matrices, xdir is exact enough; unskinned: the node's
                    n = mirror_p(norm(xdir(M if J is not None else node_nm, N[v])))
                else:
                    n = None
                if C:
                    cc = [max(0, min(255, int(round(x * 255)))) for x in C[v]]
                    c = tuple(cc[:4]) if len(cc) >= 4 else tuple(cc[:3]) + (None,)   # no alpha: from the game's, below
                else:
                    c = None
                det = M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1]) - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0]) \
                    + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0])
                verts.append({'pos': p, 'normal': n, 'tangent': None, 'color': c,
                              'uv': [tuple(u[v]) for u in UV], 'infl': bones, 'flip': det < 0})
            tris = []
            raw_tris = [(I[k], I[k + 1], I[k + 2]) for k in range(0, len(I) - 2, 3)]
            # A mirrored object (negative scale, skinned or not -- Blender bakes it into the vertices and
            # keeps the face order) comes in inside out. Decide from the data: in game space a front face's
            # normal is -cross(b-a, c-a) (see export); if most faces point against their vertex normals,
            # flip the whole primitive. Without normals, fall back to the matrix determinant.
            if N:
                against = 0
                for a, b, c3 in raw_tris:
                    pa, pb, pc = verts[a]['pos'], verts[b]['pos'], verts[c3]['pos']
                    fn = cross([pb[i] - pa[i] for i in range(3)], [pc[i] - pa[i] for i in range(3)])
                    vn = [verts[a]['normal'][i] + verts[b]['normal'][i] + verts[c3]['normal'][i] for i in range(3)]
                    if dot(fn, vn) > 0:   # -cross against the normals
                        against += 1
                flip = against * 2 > len(raw_tris)
            else:
                flip = sum(v['flip'] for v in verts) * 2 > len(verts)
            tris = [(a, c3, b) if flip else (a, b, c3) for a, b, c3 in raw_tris]
            groups.setdefault(t, []).append((verts, tris))
    if not groups:
        raise SystemExit('no meshes in %s' % gltf_path)

    report = []
    new_meshes = list(fl.meshes)
    replaced = set()
    for t, parts in groups.items():
        if isinstance(t, tuple):
            mat = t[1]
            tmpl = next((m for m in fl.meshes if m['material'] == mat), None)
            if tmpl is None:
                raise SystemExit('material %d has no mesh to copy settings from' % mat)
        else:
            tmpl = fl.meshes[t]
            replaced.add(t)
        # merge the parts
        verts, tris = [], []
        for vs, ts in parts:
            base = len(verts)
            verts += vs
            tris += [(a + base, b + base, c + base) for a, b, c in ts]
        tris = [x for x in tris if x[0] != x[1] and x[1] != x[2] and x[0] != x[2]]
        fill_colors(verts, fl, tmpl, worlds)
        fill_missing(verts, tris)
        chunks = split_chunks(verts, tris, tmpl, nb)
        built = [build_mesh(fl, tmpl, verts, ch, worlds, bsign) for ch in chunks]
        if isinstance(t, tuple):
            new_meshes += built
            report.append('new mesh (%s): %d vertices, %d triangles%s' % (
                fl.materials[t[1]]['name'], len(verts), len(tris), ', %d parts' % len(built) if len(built) > 1 else ''))
        else:
            new_meshes[t] = built[0]
            new_meshes += built[1:]
            report.append('m%02d: %d -> %d vertices, %d triangles%s' % (
                t, tmpl['vertex_count'], len(verts), len(tris), ' (split into %d meshes)' % len(built) if len(built) > 1 else ''))
    # an object named after a mesh whose faces all went to other materials: that mesh is now empty
    emptied = present - replaced
    if emptied:
        report.append('removed %s: every face of it now uses another material' %
                      ', '.join('m%02d' % i for i in sorted(emptied)))
    if delete_missing:
        keep = [m for i, m in enumerate(new_meshes) if i >= len(fl.meshes) or i in replaced]
        report.append('removed %d meshes not in the file' % (len(new_meshes) - len(keep)))
        new_meshes = keep
    elif emptied:
        new_meshes = [m for i, m in enumerate(new_meshes) if i not in emptied]
    fl.meshes = new_meshes
    update_bounds(fl, worlds)
    out = fl.write()
    sf.Flver0(out)   # must read back
    if not quiet:
        for r in report:
            print('  ' + r)
    if dry:
        return out
    write_mod(mf, entry, out, mod_root, gltf_path, rel)
    return out


def fill_colors(verts, fl, tmpl, worlds):
    """Vertex colour the file did not carry -- Blender exports COLOR_0 without alpha, or not at all --
    from the nearest original vertex of the template mesh (1 cm grid, then its neighbours); white for
    geometry nowhere near the original."""
    if all(v['color'] is not None and v['color'][3] is not None for v in verts):
        return
    nb = len(fl.bones)
    grid = {}
    for d in decode_vertices(fl, tmpl):
        if 'color' not in d:
            continue
        if tmpl['dynamic'] or not nb:
            p, n = d['pos'], d.get('normal', (0, 0, 0))[:3]
        else:
            W = worlds[mesh_bone(tmpl, d['bones'][0], nb)]
            p, n = xform(W, d['pos']), norm(xdir(W, d.get('normal', (0, 0, 0))[:3]))
        grid.setdefault(tuple(int(math.floor(c * 100)) for c in p), []).append(
            (p, n, d['uv'][0] if d['uv'] else (0.0, 0.0), d['color']))

    def near(v, rgb=None):
        """The closest original vertex (then the one facing the same way, then nearest UV; when only
        alpha is missing, one whose RGB matches first)."""
        p = v['pos']
        n = v['normal'] or (0.0, 0.0, 0.0)
        uv = v['uv'][0] if v['uv'] else (0.0, 0.0)
        k = tuple(int(math.floor(c * 100)) for c in p)
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for q, qn, quv, col in grid.get((k[0] + dx, k[1] + dy, k[2] + dz), ()):
                        key = (rgb is not None and tuple(col[:3]) != tuple(rgb),
                               round(sum((q[i] - p[i]) ** 2 for i in range(3)), 8), 1.0 - dot(n, qn),
                               (quv[0] - uv[0]) ** 2 + (quv[1] - uv[1]) ** 2)
                        if best is None or key < best[0]:
                            best = (key, col)
        return best[1] if best else (255, 255, 255, 255)
    for v in verts:
        if v['color'] is None:
            v['color'] = tuple(near(v))
        elif v['color'][3] is None:
            v['color'] = tuple(v['color'][:3]) + (near(v, v['color'][:3])[3],)


def fill_missing(verts, tris):
    """Normals and tangents for vertices the file had none for (a new object exported without them)."""
    if any(v['normal'] is None for v in verts):
        acc = [[0.0, 0.0, 0.0] for _ in verts]
        for a, b, c in tris:
            pa, pb, pc = verts[a]['pos'], verts[b]['pos'], verts[c]['pos']
            fnrm = cross([pb[k] - pa[k] for k in range(3)], [pc[k] - pa[k] for k in range(3)])
            fnrm = (-fnrm[0], -fnrm[1], -fnrm[2])   # game winding is the other way round (see export)
            for i in (a, b, c):
                for k in range(3):
                    acc[i][k] += fnrm[k]
        for i, v in enumerate(verts):
            if v['normal'] is None:
                v['normal'] = norm(acc[i])
    if any(v['tangent'] is None for v in verts):
        # The game's tangent is dP/dv (not glTF's dP/du) and its w is minus the UV handedness
        # sign(dot(cross(N, dP/du), dP/dv)) -- 21908 of 21934 game vertices agree (NOTES fix 61).
        acc_u = [[0.0, 0.0, 0.0] for _ in verts]
        acc_v = [[0.0, 0.0, 0.0] for _ in verts]
        for a, b, c in tris:
            va, vb, vc = verts[a], verts[b], verts[c]
            if not va['uv'] or not vb['uv'] or not vc['uv']:
                continue
            e1 = [vb['pos'][k] - va['pos'][k] for k in range(3)]
            e2 = [vc['pos'][k] - va['pos'][k] for k in range(3)]
            du1, dv1 = vb['uv'][0][0] - va['uv'][0][0], vb['uv'][0][1] - va['uv'][0][1]
            du2, dv2 = vc['uv'][0][0] - va['uv'][0][0], vc['uv'][0][1] - va['uv'][0][1]
            r = du1 * dv2 - du2 * dv1
            if abs(r) < 1e-12:
                continue
            tu = [(e1[k] * dv2 - e2[k] * dv1) / r for k in range(3)]
            tv = [(e2[k] * du1 - e1[k] * du2) / r for k in range(3)]
            for i in (a, b, c):
                for k in range(3):
                    acc_u[i][k] += tu[k]
                    acc_v[i][k] += tv[k]
        for i, v in enumerate(verts):
            if v['tangent'] is None:
                n = v['normal']
                t = acc_v[i]
                d = dot(t, n)
                t = norm([t[k] - n[k] * d for k in range(3)]) if any(abs(x) > 1e-12 for x in t) else \
                    norm(cross(n, (0.0, 0.0, 1.0) if abs(n[2]) < 0.9 else (1.0, 0.0, 0.0)))
                hand = 1.0 if dot(cross(n, acc_u[i]), acc_v[i]) >= 0 else -1.0
                v['tangent'] = t + (-hand,)


def vert_bones(v, tmpl, nb):
    if v['infl']:
        return [b for b, w in v['infl']]
    return [mesh_bone(tmpl, tmpl['default_bone'], nb)]


def split_chunks(verts, tris, tmpl, nb):
    """Triangles -> chunks with at most 28 bones and 65535 vertices each."""
    chunks = []
    cur_t, cur_b, cur_v = [], set(), set()
    for tri in tris:
        tb = set()
        for i in tri:
            if tmpl['dynamic']:
                tb.update(vert_bones(verts[i], tmpl, nb))
            else:
                tb.add(rigid_bone(verts[i], tmpl, nb))
        new = [i for i in set(tri) if i not in cur_v]
        if cur_t and (len(cur_b | tb) > MAX_BONES or len(cur_v) + len(new) >= MAX_VERTS):
            chunks.append(cur_t)
            cur_t, cur_b, cur_v = [], set(), set()
        if len(tb) > MAX_BONES:
            raise SystemExit('one triangle uses more than %d bones' % MAX_BONES)
        cur_t.append(tri); cur_b |= tb; cur_v.update(tri)
    if cur_t or not chunks:
        chunks.append(cur_t)
    return chunks


def rigid_bone(v, tmpl, nb):
    if v['infl']:
        return max(v['infl'], key=lambda x: x[1])[0]
    return mesh_bone(tmpl, tmpl['default_bone'], nb)


def build_mesh(fl, tmpl, verts, tris, worlds, bsign):
    nb = len(fl.bones)
    invs = [minv(w) for w in worlds]
    nmat_inv = [normal_matrix(m) for m in invs]
    used = sorted(set(i for t in tris for i in t))
    remap = {o: n for n, o in enumerate(used)}
    table = []

    def local(b):
        if b not in table:
            table.append(b)
        return table.index(b)
    out = []
    for o in used:
        v = verts[o]
        d = {'uv': v['uv'], 'color': v['color'] or (255, 255, 255, 255)}
        n, tg = v['normal'], v['tangent']
        if tmpl['dynamic']:
            infl = v['infl'] or [(vert_bones(v, tmpl, nb)[0], 1.0)]
            infl = sorted(infl, key=lambda x: -x[1])[:4]
            tot = sum(w for _, w in infl) or 1.0
            ids = [local(b) for b, _ in infl] + [0] * (4 - len(infl))
            ws = [w / tot for _, w in infl] + [0.0] * (4 - len(infl))
            d['pos'] = v['pos']
        else:
            b = rigid_bone(v, tmpl, nb)
            ids = [local(b), 0, 0, 0]
            ws = [1.0, 0.0, 0.0, 0.0]
            inv = invs[b] if nb else mident()
            d['pos'] = xform(inv, v['pos'])
            n = norm(xdir(nmat_inv[b], n)) if nb else n
            tg = norm(xdir(inv, tg[:3])) + (tg[3],)
        d['bones'] = tuple(ids)
        d['weights'] = tuple(ws)
        d['normal'] = tuple(n[:3]) + (0.0,)   # the game's normal W byte is 127 (= 0)
        d['tangent'] = tuple(tg)
        bt = cross(n[:3], tg[:3]) if bsign > 0 else cross(tg[:3], n[:3])
        d['bitangent'] = tuple(c * (tg[3] or 1.0) for c in bt) + (tg[3],)
        out.append(d)
    if len(table) > MAX_BONES:
        raise SystemExit('internal: mesh chunk with %d bones' % len(table))
    me = {k: (list(v) if isinstance(v, list) else v) for k, v in tmpl.items()}
    me['raw'] = bytearray(tmpl['raw'])
    me['bone_indices'] = table + [-1] * (MAX_BONES - len(table))
    # default bone (a global bone, see mesh_bone): kept as the game had it
    me['vertex_count'] = len(out)
    me['indices'] = triangles_to_strip([(remap[a], remap[b], remap[c]) for a, b, c in tris])
    buf = dict(tmpl['vbufs']['buffers'][0])
    buf['data'] = encode_vertices(fl, me, out)
    me['vbufs'] = {'ab': tmpl['vbufs']['ab'], 'buffers': [buf]}
    if tmpl['vbufs'].get('implicit'):
        me['vbufs']['implicit'] = True
    me['vbufs2'] = None
    return me


def update_bounds(fl, worlds):
    """Header bounding box and face counts; bone boxes only grow (they cull)."""
    E = fl.E
    nb = len(fl.bones)
    mn = [float('inf')] * 3
    mx = [float('-inf')] * 3
    bmin = {}
    bmax = {}
    true_faces = 0
    invs = [minv(w) for w in worlds]
    for me in fl.meshes:
        for d in decode_vertices(fl, me):
            b = mesh_bone(me, d['bones'][0], nb) if nb else 0
            if me['dynamic'] or not nb:
                p = d['pos']
                local = xform(invs[b], p) if nb else p
            else:
                local = d['pos']
                p = xform(worlds[b], local)
            for k in range(3):
                mn[k] = min(mn[k], p[k]); mx[k] = max(mx[k], p[k])
            if nb:
                lo = bmin.setdefault(b, [float('inf')] * 3); hi = bmax.setdefault(b, [float('-inf')] * 3)
                for k in range(3):
                    lo[k] = min(lo[k], local[k]); hi[k] = max(hi[k], local[k])
        true_faces += sum(1 for t in sf.strip_triangles(me['indices']) if t[0] != t[1] and t[1] != t[2] and t[0] != t[2])
    if mn[0] != float('inf'):   # grow only: a box shrunk by float rounding could cull edges
        omn = struct.unpack_from(E + '3f', fl.raw_header, 0x28); omx = struct.unpack_from(E + '3f', fl.raw_header, 0x34)
        if omn[0] <= omx[0]:
            mn = [min(mn[k], omn[k]) for k in range(3)]; mx = [max(mx[k], omx[k]) for k in range(3)]
        struct.pack_into(E + '6f', fl.raw_header, 0x28, *(mn + mx))
    old_true, old_total = struct.unpack_from(E + 'ii', fl.raw_header, 0x40)
    total = true_faces if old_total == old_true else sum(max(0, len(m['indices']) - 2) for m in fl.meshes)
    struct.pack_into(E + 'ii', fl.raw_header, 0x40, true_faces, total)
    for b, lo in bmin.items():
        raw = fl.bones[b]['raw']
        olo = list(struct.unpack_from(E + '3f', raw, 0x30)); ohi = list(struct.unpack_from(E + '3f', raw, 0x40))
        if olo[0] > 1e30:   # bone with no geometry so far (FLT_MAX box)
            olo, ohi = list(lo), list(bmax[b])
        struct.pack_into(E + '3f', raw, 0x30, *[min(olo[k], lo[k]) for k in range(3)])
        struct.pack_into(E + '3f', raw, 0x40, *[max(ohi[k], bmax[b][k]) for k in range(3)])


def mod_paths(mod_root):
    """(mod folder, its USRDIR) -- refusing anything that is, or is inside, or contains game\\."""
    mr = os.path.normcase(os.path.realpath(os.path.join(BASE, mod_root)))
    gr = os.path.normcase(os.path.realpath(os.path.join(BASE, 'game')))
    if mr == gr or mr.startswith(gr + os.sep) or gr.startswith(mr + os.sep):
        raise SystemExit('the mod folder must be a copy beside game\\ (e.g. game_mod), not game\\ itself')
    return os.path.join(BASE, mod_root), os.path.join(BASE, mod_root, 'PS3_GAME', 'USRDIR')


def ensure_mod_copy(mod_root):
    """Make <mod_root> as hard links to game\\ (no extra disk space). A marker is written last, so an
    interrupted build is completed next time (only missing files are linked; nothing is replaced)."""
    top, _ = mod_paths(mod_root)
    marker = os.path.join(top, '.links_complete')
    if os.path.exists(marker):
        return
    print('making %s\\ (hard links to game\\, no extra disk space)' % mod_root)
    src = os.path.join(BASE, 'game')
    copied = 0
    for d, _, fs in os.walk(src):
        t = os.path.join(top, os.path.relpath(d, src))
        os.makedirs(t, exist_ok=True)
        for f in fs:
            dst = os.path.join(t, f)
            if os.path.exists(dst):
                continue
            try:
                os.link(os.path.join(d, f), dst)
            except OSError:
                shutil.copy2(os.path.join(d, f), dst)
                copied += 1
    if copied:
        print('  (%d files had to be copied -- hard links were refused there)' % copied)
    with open(marker, 'w') as f:
        f.write('hard-link copy of game\\ complete\n')


def write_mod(mf, entry, data, mod_root, gltf_path, rel=None):
    """Put the new FLVER into <mod_root>'s copy of the model file and of its loose / .dcx twin. When the
    mod copy is already modded (an earlier import, or the PC Remaster's own file) that copy is the base,
    so only this FLVER changes -- other models in the same archive keep their edits."""
    top, root = mod_paths(mod_root)
    ensure_mod_copy(mod_root)
    groot = os.path.normcase(os.path.realpath(GAME))
    rel = rel or os.path.relpath(mf.path, GAME)
    label = mf.flvers[entry][0]
    targets = [rel]
    twin = rel[:-4] if rel.lower().endswith('.dcx') else rel + '.dcx'   # the game reads the .dcx copy
    if os.path.exists(os.path.join(GAME, twin)) or os.path.exists(os.path.join(root, twin)):
        targets.append(twin)
    for t in targets:
        dst = os.path.join(root, t)
        orig = os.path.join(GAME, t)
        modded = os.path.exists(dst) and not (os.path.exists(orig) and os.path.samefile(dst, orig))
        base = ModelFile(dst) if modded else (mf if os.path.normcase(os.path.abspath(orig)) == os.path.normcase(mf.path)
                                              else ModelFile(orig))
        k = next((i for i, (lb, _, _) in enumerate(base.flvers) if lb.lower() == label.lower()), None)
        if k is None:
            k = entry if entry < len(base.flvers) else 0
        payload = base.rebuilt(k, data)
        if os.path.normcase(os.path.realpath(os.path.dirname(dst))).startswith(groot):
            raise SystemExit('refusing to write into game\\: %s' % dst)
        if os.path.exists(dst):
            os.remove(dst)   # may be a hard link shared with game\ -- never write into it
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as f:
            f.write(payload)
        print('  wrote %s' % os.path.join(mod_root, 'PS3_GAME', 'USRDIR', t))
    with open(os.path.join(top, 'MODEL_IMPORTS.txt'), 'a', encoding='utf-8') as f:
        f.write('%s [%s] <- %s\n' % (rel, label, os.path.abspath(gltf_path)))
    # the low-detail copy shown at a distance keeps the old shape unless it is imported too
    for lod in lod_twins(rel):
        if os.path.exists(os.path.join(GAME, lod)):
            print('  note: %s is the low-detail copy seen from far away -- import into it too, or the old shape'
                  ' shows at a distance' % lod)


def lod_twins(rel):
    """bd_f_5010.partsbnd.dcx -> bd_f_5010_l.partsbnd.dcx; m2400b0.flver.dcx -> m2400b0l1.flver.dcx."""
    d, f = os.path.split(rel)
    stem, dot, ext = f.partition('.')
    if stem.lower().endswith('_l') or re.search(r'l\d$', stem.lower()):
        return []
    return [os.path.join(d, stem + '_l' + dot + ext), os.path.join(d, stem + 'l1' + dot + ext)]


# ------------------------------------------------------------------------------------------- list / selftest


def list_model(path):
    mf = ModelFile(path)
    for label, fl, _ in mf.flvers:
        print('%s: %d meshes, %d materials, %d bones, %d dummies' % (label, len(fl.meshes), len(fl.materials),
                                                                    len(fl.bones), len(fl.dummies)))
        for i, me in enumerate(fl.meshes):
            m = fl.materials[me['material']]
            print('  m%02d  %-28s %6d vertices %6d triangles  %s' % (
                i, m['name'][:28], me['vertex_count'],
                sum(1 for t in sf.strip_triangles(me['indices']) if len(set(t)) == 3),
                'skinned' if me['dynamic'] else 'rigid'))


def selftest(only=''):
    import tempfile
    n_ok = n_bad = n_bnd = n_rt = 0
    worst = 0.0
    samples = []
    for dp, dn, fn in os.walk(GAME):
        for f in fn:
            lf = f.lower()
            if only and only.lower() not in lf:
                continue
            p = os.path.join(dp, f)
            if not (lf.endswith('.flver') or lf.endswith('.flver.dcx') or re.search(r'\.(chr|parts|obj)bnd(\.dcx)?$', lf)):
                continue
            try:
                raw = open(p, 'rb').read()
                info = None
                if raw[:4] in (b'DCX\0', b'DCP\0'):
                    pay, info = sf.dcx_decompress(raw)
                    if sf.dcx_decompress(sf.dcx_compress(pay, info))[0] != pay:
                        raise ValueError('DCX round trip')
                    raw = pay
                if raw[:4] == b'BND3':
                    b = sf.Bnd3(raw)
                    if b.write() != raw:
                        raise ValueError('BND3 round trip')
                    n_bnd += 1
                    fls = [e['data'] for e in b.entries if (e['name'] or '').lower().endswith('.flver')]
                else:
                    fls = [raw]
                for d in fls:
                    fl = sf.Flver0(d)
                    if fl.write() != d:
                        raise ValueError('FLVER round trip')
                    if fl.meshes and len(samples) < 400 and (len(samples) * 7 + n_ok) % 13 == 0:
                        samples.append(p)
                n_ok += 1
            except Exception as e:
                n_bad += 1
                print('FAIL %s: %s' % (os.path.relpath(p, GAME), e))
    print('read/write byte for byte: %d files OK (%d archives), %d failed' % (n_ok, n_bnd, n_bad))
    # an import changes the payload size: the EDGE header must follow (0x14 = 0x10 + DCA size, which the
    # game's reader uses to find the block data -- a stale one hung the map loader)
    dcx_bad = 0
    for rel in ('PARTS/bd_f_5010.partsbnd.dcx', 'MAP/M02_00_00_00/m4000b0.flver.dcx'):
        p = os.path.join(GAME, rel)
        if not os.path.exists(p):
            continue
        pay, info = sf.dcx_decompress(open(p, 'rb').read())
        for grown in (pay + b'\0' * 0x30000, pay[:max(16, len(pay) - 0x20000)]):
            w = sf.dcx_compress(grown, info)
            if info['kind'] == 'EDGE':
                dca = w.find(b'DCA\0')
                if struct.unpack_from('>I', w, 0x14)[0] != struct.unpack_from('>I', w, 0x10)[0] + \
                        struct.unpack_from('>I', w, dca + 4)[0]:
                    dcx_bad += 1
            if sf.dcx_decompress(w)[0] != grown:
                dcx_bad += 1
    print('DCX resized rewrite: %s' % ('OK' if not dcx_bad else '%d FAILED' % dcx_bad))
    n_bad += dcx_bad
    # export -> import with no edits must give back the same vertices (to quantisation) and triangles
    tmp = tempfile.mkdtemp(prefix='flvertest')
    seen = set()
    for p in samples[:40]:
        if p in seen:
            continue
        seen.add(p)
        mf = ModelFile(p)
        if len(mf.flvers) != 1:
            continue
        try:
            files = export_model(p, tmp, textures=False)
        except SystemExit:
            continue
        if not files:
            continue
        sys.stdout.flush()
        out = import_model(files[0], p, None, dry=True, quiet=True)
        a, b = mf.flvers[0][1], sf.Flver0(out)
        err = compare_models(a, b)
        worst = max(worst, err)
        n_rt += 1
        if err > 0.01:
            print('ROUND TRIP DIFF %s: %.4f' % (os.path.relpath(p, GAME), err))
    shutil.rmtree(tmp, ignore_errors=True)
    print('export -> import unchanged: %d models, worst position error %.5f' % (n_rt, worst))
    return n_bad == 0 and worst <= 0.01


def compare_models(a, b):
    """Largest position difference between matching triangles' vertices (model space)."""
    wa, wb = bone_worlds(a), bone_worlds(b)
    worst = 0.0
    if len(a.meshes) != len(b.meshes):
        return 1e9
    for ma, mb in zip(a.meshes, b.meshes):
        va, vb = decode_vertices(a, ma), decode_vertices(b, mb)

        def world(fl, me, d, W):
            if me['dynamic'] or not fl.bones:
                return d['pos']
            return xform(W[mesh_bone(me, d['bones'][0], len(fl.bones))], d['pos'])
        # the stripifier reorders triangles: match each of b's to one of a's near its centre (same winding,
        # any rotation), and take the worst vertex distance
        ta = [[world(a, ma, va[i], wa) for i in t] for t in sf.strip_triangles(ma['indices']) if len(set(t)) == 3]
        tb = [[world(b, mb, vb[i], wb) for i in t] for t in sf.strip_triangles(mb['indices']) if len(set(t)) == 3]
        if len(ta) != len(tb):
            return 1e9
        cell = {}
        for k, t in enumerate(ta):
            c = tuple(int(math.floor(sum(p[j] for p in t) / 3 * 50)) for j in range(3))
            cell.setdefault(c, []).append(k)
        used = set()
        for t in tb:
            c = tuple(int(math.floor(sum(p[j] for p in t) / 3 * 50)) for j in range(3))
            best = None
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for k in cell.get((c[0] + dx, c[1] + dy, c[2] + dz), ()):
                            if k in used:
                                continue
                            s = ta[k]
                            for r in range(3):   # rotations keep the winding
                                e = max(max(abs(s[(i + r) % 3][j] - t[i][j]) for j in range(3)) for i in range(3))
                                if best is None or e < best[0]:
                                    best = (e, k)
            if best is None:
                return 1e9
            used.add(best[1])
            worst = max(worst, best[0])
    return worst


def main():
    for s in (sys.stdout, sys.stderr):   # material names can be Japanese; a cp1252 console must not crash
        try:
            s.reconfigure(errors='replace')
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('export'); e.add_argument('model'); e.add_argument('-o', '--out', default=os.path.join(BASE, 'models'))
    i = sub.add_parser('import'); i.add_argument('gltf'); i.add_argument('model')
    i.add_argument('--mod', default='game_mod'); i.add_argument('--entry', type=int)
    i.add_argument('--delete-missing', action='store_true')
    l = sub.add_parser('list'); l.add_argument('model')
    s = sub.add_parser('selftest'); s.add_argument('only', nargs='?', default='')
    a = ap.parse_args()
    if a.cmd == 'export':
        export_model(a.model, a.out)
    elif a.cmd == 'import':
        if a.mod.lower() == 'game':
            raise SystemExit('import into a mod copy, not game\\ itself')
        import_model(a.gltf, a.model, a.mod, a.entry, a.delete_missing)
        bat = next((b for b in ('PLAY_MODDED.bat', os.path.join('..', 'PLAY_DEMONS_SOULS_MODDED.bat'))
                    if os.path.exists(os.path.join(BASE, b))), 'PLAY_MODDED.bat')
        if a.mod.lower() == 'game_mod':
            print('done -- play it with %s' % os.path.basename(bat))
        elif a.mod.lower() == 'game_remaster':
            print('done -- play it with the PC Remaster launcher')
        else:
            print('done -- play it with DES_GAME=%s set before the launcher' % a.mod)
    elif a.cmd == 'list':
        list_model(a.model)
    elif a.cmd == 'selftest':
        sys.exit(0 if selftest(a.only) else 1)


if __name__ == '__main__':
    main()
