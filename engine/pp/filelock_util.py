"""Cross-platform advisory file locking (POSIX fcntl, Windows msvcrt)."""
from __future__ import annotations

import os
from typing import IO

try:
    import fcntl as _fcntl
except ImportError:  # Windows
    _fcntl = None

try:
    import msvcrt as _msvcrt
except ImportError:  # POSIX
    _msvcrt = None


def lock_file(fh: IO, *, nonblocking: bool = False) -> None:
    """Acquire an exclusive lock on an open file handle. Raises OSError on contention when nonblocking."""
    if _fcntl is not None:
        flags = _fcntl.LOCK_EX | (_fcntl.LOCK_NB if nonblocking else 0)
        _fcntl.flock(fh.fileno(), flags)
        return
    if _msvcrt is not None:
        fh.seek(0)
        if os.fstat(fh.fileno()).st_size == 0:
            fh.write("\0" if isinstance(fh.read(0), str) else b"\0")
            fh.flush()
            fh.seek(0)
        mode = _msvcrt.LK_NBLCK if nonblocking else _msvcrt.LK_LOCK
        _msvcrt.locking(fh.fileno(), mode, 1)
        return
    raise RuntimeError("No supported file locking mechanism available on this platform")


def unlock_file(fh: IO) -> None:
    """Release a lock acquired by lock_file (best-effort)."""
    if _fcntl is not None:
        try:
            _fcntl.flock(fh.fileno(), _fcntl.LOCK_UN)
        except OSError:
            pass
        return
    if _msvcrt is not None:
        try:
            fh.seek(0)
            _msvcrt.locking(fh.fileno(), _msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
