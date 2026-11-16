#!/usr/bin/env python3
"""Bounded Nintendo AGL PMAA parameter edits for Bloom and DepthOfField.

The previous BYML-only search missed the game's other AGL parameter format
(.baglblm/.bagldof). Only known parameter names (CRC32), typed values and
matching PMAA effect types may be modified; no Create flags or shader code.
"""
import struct
import zlib

class Error(ValueError):
    pass

MAX_FILE = 2 * 1024 * 1024
BOOLEAN_NAMES = {
    'bloom': ('enable', 'is_enable', 'Enable', 'IsEnable', 'active', 'bloom_enable'),
    'dof': ('enable', 'is_enable', 'Enable', 'IsEnable', 'near_enable', 'far_enable'),
}
FLOAT_NAMES = {
    'bloom': ('bloom_intensity', 'bloom_intencity', 'BloomIntencity', 'intensity', 'bloom_strength'),
    'dof': ('depth_blur', 'dof_far_max', 'dof_blur_mipmap'),
}
EXPECTED_TYPE = {'bloom': 'aglblm', 'dof': 'agldof'}


def patch(data, family):
    if family not in EXPECTED_TYPE:
        raise Error('unknown agl effect family')
    if len(data) < 40 or len(data) > MAX_FILE or data[:4] not in (b'AAMP', b'PMAA'):
        raise Error('not supported AGL PMAA')
    endian = '<' if data[:4] == b'AAMP' else '>'
    def u32(off):
        if off < 0 or off + 4 > len(data): raise Error('PMAA read outside file')
        return struct.unpack_from(endian + 'I', data, off)[0]
    version = u32(4)
    declared = u32(12)
    if version not in (1,2) or declared != len(data):
        raise Error('unsupported PMAA version/filesize')
    name_len = u32(20)
    header_start = 0x18 if version == 1 else 0x30
    if name_len < 4 or name_len > 128 or header_start + name_len > len(data):
        raise Error('bad PMAA type name size')
    effect_type = data[header_start:header_start+name_len].split(b'\0',1)[0].decode('ascii', 'replace')
    if effect_type != EXPECTED_TYPE[family]:
        raise Error('effect type does not match file extension')
    allowed_bools = {zlib.crc32(n.encode()) for n in BOOLEAN_NAMES[family]}
    allowed_floats = {zlib.crc32(n.encode()) for n in FLOAT_NAMES[family]}
    # Collect candidate value offsets; each name hash and scalar type must match.
    candidate = []
    if version == 2:
        nlists, nobjects, nparams = (u32(0x18), u32(0x1c), u32(0x20))
        if nlists > 65535 or nobjects > 65535 or nparams > 262144:
            raise Error('PMAA table counts unreasonable')
        table = 0x30 + name_len + 12 * nlists + 8 * nobjects
        if table + nparams * 8 > len(data):
            raise Error('PMAA parameter table outside file')
        for i in range(nparams):
            entry = table + i * 8
            h, meta = u32(entry), u32(entry + 4)
            ty, rel = meta >> 24, meta & 0xffffff
            if not (ty == 0 and h in allowed_bools or ty == 1 and h in allowed_floats):
                continue
            target = entry + 4 * rel
            if target < 0 or target + (1 if ty == 0 else 4) > len(data):
                raise Error('PMAA effect value offset outside file')
            candidate.append((h, ty, target))
    else:
        root = 0x18 + name_len
        seen = set()
        def visit_list(at, depth):
            if at in seen or depth > 12: return
            seen.add(at)
            size = u32(at)
            lists = u32(at + 8)
            objects = u32(at + 12)
            if size < 16 or at + size > len(data) or lists > 4096 or objects > 8192:
                raise Error('bad PMAA parameter list')
            pos = at + 16
            for _ in range(lists):
                child = pos
                visit_list(child, depth + 1)
                pos = child + u32(child)
            for _ in range(objects):
                obj = pos
                sz = u32(obj)
                if sz < 16 or obj + sz > at + size: raise Error('bad PMAA object')
                num = u32(obj + 4)
                if num > 8192: raise Error('PMAA object too many values')
                atp = obj + 16
                for _i in range(num):
                    psz, ty, h = u32(atp), u32(atp+4), u32(atp+8)
                    if psz < 12 or atp + psz > obj + sz: raise Error('bad PMAA value')
                    if (ty == 0 and h in allowed_bools or ty == 1 and h in allowed_floats):
                        candidate.append((h,ty,atp+12))
                    atp += psz
                pos = obj + sz
        visit_list(root,0)
    if not candidate:
        return data, 0
    out = bytearray(data)
    count = 0
    for h, ty, off in candidate:
        if ty == 0:
            v = out[off]
            if v not in (0, 1): raise Error('invalid PMAA boolean for AGL effect')
            if v == 1:
                out[off] = 0
                count += 1
        else:
            val = struct.unpack_from(endian+'f', out, off)[0]
            if 0.0 < val <= 10000.0:
                struct.pack_into(endian+'f', out, off, 0.0)
                count += 1
    allowed = {off+i for _h, ty, off in candidate for i in range(1 if ty == 0 else 4)}
    if any(i not in allowed for i,(x,y) in enumerate(zip(data,out)) if x != y):
        raise Error('PMAA changed bytes outside verified effect parameter')
    return bytes(out), count
