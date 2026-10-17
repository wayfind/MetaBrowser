"""Fragment this fixture's single-track, all-intra FFmpeg CENC MP4 for MSE.

This deliberately narrow converter preserves encrypted samples and their senc
auxiliary data. It rejects other layouts rather than pretending to be a muxer.
No decryption key or external packages are required.
"""
import argparse
from pathlib import Path
import struct


def u32(*values):
    return struct.pack('>' + 'I' * len(values), *values)


def box(kind, payload):
    return u32(8 + len(payload)) + kind + payload


def boxes(data):
    offset = 0
    while offset < len(data):
        if len(data) - offset < 8:
            raise ValueError('Truncated box')
        size, kind = struct.unpack_from('>I4s', data, offset)
        if size < 8 or size > len(data) - offset:
            raise ValueError('Unsupported box size')
        yield kind, data[offset + 8:offset + size]
        offset += size


def fragment(data):
    top = dict(boxes(data))
    tables = {}

    def rewrite(kind, payload):
        if kind in (b'moov', b'trak', b'mdia', b'minf', b'stbl'):
            children = list(boxes(payload))
            if kind == b'moov' and sum(k == b'trak' for k, _ in children) != 1:
                raise ValueError('Expected one track')
            if kind == b'stbl':
                tables.update(children)
                return box(kind, b''.join([
                    box(b'stsd', tables[b'stsd']), box(b'stts', u32(0, 0)),
                    box(b'stsc', u32(0, 0)), box(b'stsz', u32(0, 0, 0)),
                    box(b'stco', u32(0, 0))]))
            result = b''.join(rewrite(k, v) for k, v in children)
            if kind == b'moov':
                result += box(b'mvex', box(b'trex', u32(0, 1, 1, 0, 0, 0)))
            return box(kind, result)
        return box(kind, payload)

    moov = rewrite(b'moov', top[b'moov'])
    if tables[b'stts'][:8] != u32(0, 1):
        raise ValueError('Expected constant sample duration')
    count, duration = struct.unpack_from('>II', tables[b'stts'], 8)
    if tables[b'stsz'][:12] != u32(0, 0, count):
        raise ValueError('Expected explicit sample sizes')
    sizes = struct.unpack('>' + 'I' * count, tables[b'stsz'][12:])
    if sum(sizes) != len(top[b'mdat']):
        raise ValueError('Expected contiguous samples without padding')
    if tables[b'stsc'] != u32(0, 1, 1, count, 1):
        raise ValueError('Expected one chunk/description')
    if struct.unpack_from('>I', tables[b'senc'], 4)[0] != count:
        raise ValueError('Encryption sample count mismatch')

    def moof(data_offset, auxiliary_offset):
        trun = box(b'trun', u32(0x701, count, data_offset) + b''.join(
            u32(duration, size, 0x02000000) for size in sizes))
        traf = box(b'traf', box(b'tfhd', u32(0x020000, 1)) +
                   box(b'tfdt', u32(0x01000000, 0, 0)) + trun +
                   box(b'saiz', tables[b'saiz']) +
                   box(b'saio', u32(0, 1, auxiliary_offset)) +
                   box(b'senc', tables[b'senc']))
        return box(b'moof', box(b'mfhd', u32(0, 1)) + traf)

    provisional = moof(0, 0)
    # senc type begins four bytes after its size. Skip full-box flags and count.
    auxiliary_offset = provisional.index(b'senc') + 12
    final = moof(len(provisional) + 8, auxiliary_offset)
    ftyp = box(b'ftyp', b'isom' + u32(0x200) + b'isomiso6avc1mp41')
    return ftyp + moov + final + box(b'mdat', top[b'mdat'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_bytes(fragment(args.source.read_bytes()))
