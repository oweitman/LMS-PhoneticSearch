"""POC gate for avoiding unconditional full LMS library comparisons.

Keep one read-only SQLite connection open: PRAGMA data_version may only be
compared across calls on that same connection. File identity detects DB swaps.
"""
from pathlib import Path
import sqlite3
import time

DEFAULT_FORCE_SECONDS = 900.0


class ChangeGate:
    def __init__(self, source_path, force_seconds=DEFAULT_FORCE_SECONDS):
        self.path = Path(source_path)
        self.force_seconds = force_seconds
        self.connection = None
        self.identity = None
        self.version = None
        self.last_full = time.monotonic()
        self.pending = True  # A newly staged index needs one post-activation check.
        self._open()

    def _open(self):
        if self.connection is not None:
            self.connection.close()
        self.connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        stat = self.path.stat()
        self.identity = (stat.st_dev, stat.st_ino)
        self.version = self.connection.execute("PRAGMA data_version").fetchone()[0]

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def check(self):
        started = time.perf_counter()
        stat = self.path.stat()
        identity = (stat.st_dev, stat.st_ino)
        if identity != self.identity:
            self._open()
            self.pending = True
            observed = self.version
            reason = "file_replaced"
        else:
            observed = self.connection.execute("PRAGMA data_version").fetchone()[0]
            if self.pending:
                reason = "pending"
            elif observed != self.version:
                reason = "db_changed"
            elif time.monotonic() - self.last_full >= self.force_seconds:
                reason = "periodic"
            else:
                reason = "unchanged"
        return reason, observed, (time.perf_counter() - started) * 1000

    def completed(self, observed_version, full=False):
        stat = self.path.stat()
        if (stat.st_dev, stat.st_ino) != self.identity:
            self._open()
            self.pending = True
            return
        after = self.connection.execute("PRAGMA data_version").fetchone()[0]
        self.version = observed_version
        self.pending = after != observed_version
        if full and not self.pending:
            self.last_full = time.monotonic()

