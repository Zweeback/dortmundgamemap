from __future__ import annotations

import os
from pathlib import Path
from typing import IO


class ProcessLockError(RuntimeError):
    pass


class ProcessExclusiveLock:
    """OS-managed process lock held for the lifetime of the gateway instance.

    The lock is advisory but process-scoped. On process death the OS releases it,
    so a cold-start replacement can safely become the sole sweeper authority.
    This intentionally forbids multiple FastAPI worker processes from sharing the
    same JOBS_DIR until a distributed leader election is introduced.
    """

    def __init__(self, path: str | os.PathLike[str], *, holder: str) -> None:
        self.path = Path(path)
        self.holder = holder
        self._fh: IO[bytes] | None = None

    @property
    def acquired(self) -> bool:
        return self._fh is not None

    def acquire(self) -> None:
        if self._fh is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b", buffering=0)
        if os.name == "nt":
            import msvcrt

            if self.path.stat().st_size == 0:
                fh.write(b"\0")
                fh.flush()
            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                fh.close()
                raise ProcessLockError(
                    f"gateway process lock is already held: {self.path}"
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                fh.close()
                raise ProcessLockError(
                    f"gateway process lock is already held: {self.path}"
                ) from exc

        # Diagnostic holder text is written only after the OS lock is held.
        fh.seek(0)
        fh.truncate()
        fh.write((self.holder + "\n").encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())
        self._fh = fh

    def release(self) -> None:
        fh = self._fh
        if fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()
            self._fh = None

    def __enter__(self) -> "ProcessExclusiveLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
