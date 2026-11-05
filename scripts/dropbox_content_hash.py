#!/usr/bin/env python3
"""Print SHA-256 and Dropbox content_hash for files.

Dropbox content_hash: split the file into 4 MiB blocks, SHA-256 each block,
concatenate the binary digests, SHA-256 that. Lets us check a local copy
against the hash Dropbox reports, without the file being in this repo.

Usage: python scripts/dropbox_content_hash.py FILE [FILE ...]
"""
import hashlib
import sys

BLOCK = 4 * 1024 * 1024


def hashes(path):
    whole = hashlib.sha256()
    blocks = []
    size = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(BLOCK)
            if not chunk:
                break
            size += len(chunk)
            whole.update(chunk)
            blocks.append(hashlib.sha256(chunk).digest())
    return size, whole.hexdigest(), hashlib.sha256(b"".join(blocks)).hexdigest()


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    print("size\tsha256\tdropbox_content_hash\tpath")
    for p in argv[1:]:
        size, sha, dbx = hashes(p)
        print(f"{size}\t{sha}\t{dbx}\t{p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
