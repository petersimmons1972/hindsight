#!/usr/bin/env python3
"""Atomically exchange two directories on Linux.

Used by the correction path to publish a fully prepared catalog directory in
one namespace operation.  There is deliberately no copy/rename fallback: a
platform without ``renameat2(RENAME_EXCHANGE)`` cannot satisfy the transaction
contract and must fail before touching the live directory.
"""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from pathlib import Path

AT_FDCWD = -100
RENAME_EXCHANGE = 2


def _fsync_tree(path: Path) -> None:
    """Flush the prepared regular files and their directory metadata."""
    for child in path.rglob("*"):
        mode = child.lstat().st_mode
        if stat.S_ISREG(mode):
            descriptor = os.open(child, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def exchange(left: Path, right: Path) -> None:
    left = left.absolute()
    right = right.absolute()
    for path in (left, right):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ValueError(f"atomic-exchange target is not a real directory: {path}")
    if left.stat().st_dev != right.stat().st_dev:
        raise ValueError("atomic-exchange targets are on different filesystems")

    _fsync_tree(left)
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise OSError(
            errno.ENOSYS, "libc has no renameat2; refusing non-atomic fallback"
        )
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        AT_FDCWD,
        os.fsencode(left),
        AT_FDCWD,
        os.fsencode(right),
        RENAME_EXCHANGE,
    )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), f"{left} <-> {right}")

    for parent in {left.parent, right.parent}:
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: atomic-exchange.py PREPARED_DIR LIVE_DIR", file=sys.stderr)
        return 2
    try:
        exchange(Path(argv[0]), Path(argv[1]))
    except (OSError, ValueError) as exc:
        print(f"ERROR: atomic directory exchange failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
