#!/usr/bin/env python3
"""Compare two U-Boot uInitrd.lz4 images (initramfs) without extracting them.

Handles: optional 64-byte U-Boot legacy header, LZ4 legacy format (what the
Linux kernel build emits) or LZ4 frame format, and cpio "newc"/"crc" archives.
Pure standard library, no lz4 package needed.

Usage:
  python scripts/initrd_diff.py OLD.lz4 NEW.lz4            # file-level diff
  python scripts/initrd_diff.py OLD.lz4 NEW.lz4 --show PATH  # unified diff of one text file
  python scripts/initrd_diff.py IMG.lz4 --list             # list one image

Output never prints the contents of etc/shadow, etc/gshadow or private keys;
it only says whether they changed.
"""
import difflib
import hashlib
import struct
import sys

SECRET_PATHS = ("etc/shadow", "etc/gshadow", "etc/shadow-", "etc/gshadow-")
SECRET_HINTS = ("ssh_host_", "id_rsa", "id_ed25519", "id_ecdsa", ".key", ".pem")


def is_secret(path):
    return path in SECRET_PATHS or any(h in path for h in SECRET_HINTS)


def lz4_block(src, out):
    """Decode one raw LZ4 block, appending to bytearray `out`."""
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i:i + lit]
        i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        if off == 0:
            raise ValueError("bad lz4 offset 0")
        ml = token & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(out) - off
        if start < 0:
            raise ValueError("lz4 offset before start")
        if off >= ml:
            out += out[start:start + ml]
        else:
            for k in range(ml):
                out.append(out[start + k])


def lz4_decompress(data):
    magic = struct.unpack_from("<I", data, 0)[0]
    out = bytearray()
    if magic == 0x184C2102:  # legacy
        i = 4
        while i + 4 <= len(data):
            size = struct.unpack_from("<I", data, i)[0]
            if size == 0x184C2102:  # concatenated legacy streams
                i += 4
                continue
            i += 4
            if size == 0 or i + size > len(data):
                break
            lz4_block(data[i:i + size], out)
            i += size
        return bytes(out)
    if magic == 0x184D2204:  # frame
        flg = data[4]
        bd = data[5]
        i = 6 + (8 if flg & 0x08 else 0) + (4 if flg & 0x01 else 0) + 1
        block_ck = bool(flg & 0x10)
        while True:
            size = struct.unpack_from("<I", data, i)[0]
            i += 4
            if size == 0:
                break
            raw, size = bool(size & 0x80000000), size & 0x7FFFFFFF
            blk = data[i:i + size]
            i += size + (4 if block_ck else 0)
            if raw:
                out += blk
            else:
                lz4_block(blk, out)
        return bytes(out)
    raise ValueError("not LZ4 (magic 0x%08x)" % magic)


def load(path):
    data = open(path, "rb").read()
    if data[:4] == b"\x27\x05\x19\x56":  # U-Boot legacy image header
        name = data[32:64].split(b"\0")[0].decode("ascii", "replace")
        comp = data[31]
        print(f"# {path}: U-Boot header, name={name!r}, comp={comp}", file=sys.stderr)
        data = data[64:]
    if data[:2] == b"\x1f\x8b":
        import gzip
        return gzip.decompress(data)
    if data[:6] in (b"070701", b"070702"):
        return data
    return lz4_decompress(data)


def cpio_entries(blob):
    """Yield (path, mode, size, sha256, content) from concatenated newc archives."""
    i = 0
    n = len(blob)
    while i + 110 <= n:
        if blob[i:i + 6] not in (b"070701", b"070702"):
            # skip padding between concatenated archives
            i += 1
            continue
        hdr = blob[i:i + 110]
        f = [int(hdr[6 + 8 * k:14 + 8 * k], 16) for k in range(13)]
        mode, filesize, namesize = f[1], f[6], f[11]
        name_start = i + 110
        name = blob[name_start:name_start + namesize - 1].decode("utf-8", "replace")
        data_start = (name_start + namesize + 3) & ~3
        content = blob[data_start:data_start + filesize]
        i = (data_start + filesize + 3) & ~3
        if name == "TRAILER!!!":
            continue
        name = name.lstrip("./") if name not in (".", "./") else "."
        yield name, mode, filesize, hashlib.sha256(content).hexdigest(), content


def kind(mode):
    t = mode & 0o170000
    return {0o100000: "file", 0o040000: "dir", 0o120000: "link",
            0o020000: "chr", 0o060000: "blk", 0o010000: "fifo"}.get(t, "other")


def index(path):
    idx = {}
    for name, mode, size, sha, content in cpio_entries(load(path)):
        idx[name] = (kind(mode), oct(mode & 0o7777), size, sha, content)
    return idx


def main(argv):
    args = argv[1:]
    if len(args) == 2 and args[1] == "--list":
        for name, (k, perm, size, sha, content) in sorted(index(args[0]).items()):
            extra = " -> " + content.decode("utf-8", "replace") if k == "link" else ""
            print(f"{k}\t{perm}\t{size}\t{name}{extra}")
        return 0
    if len(args) == 4 and args[2] == "--show":
        a, b = index(args[0]), index(args[1])
        p = args[3].lstrip("/")
        if is_secret(p):
            print("refusing to print secret file; changed =", a.get(p, (0,) * 5)[3] != b.get(p, (0,) * 5)[3])
            return 0
        old = a[p][4].decode("utf-8", "replace").splitlines() if p in a else []
        new = b[p][4].decode("utf-8", "replace").splitlines() if p in b else []
        sys.stdout.writelines(l + "\n" for l in difflib.unified_diff(old, new, "old/" + p, "new/" + p, lineterm=""))
        return 0
    if len(args) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    a, b = index(args[0]), index(args[1])
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = sorted(p for p in set(a) & set(b) if a[p][:4] != b[p][:4])
    print(f"old_entries={len(a)} new_entries={len(b)} added={len(added)} removed={len(removed)} changed={len(changed)}")
    for tag, paths, src in (("+", added, b), ("-", removed, a)):
        for p in paths:
            k, perm, size = src[p][:3]
            print(f"{tag} {k}\t{perm}\t{size}\t{p}")
    for p in changed:
        (ka, pa, sa, ha, _), (kb, pb, sb, hb, _) = a[p], b[p]
        note = " [secret: content not shown]" if is_secret(p) else ""
        print(f"~ {kb}\t{pa}->{pb}\t{sa}->{sb}\t{p}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
