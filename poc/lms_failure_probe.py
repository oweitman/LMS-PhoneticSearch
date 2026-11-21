"""Reproduce a broken queue trigger against a backup of a disposable LMS DB.

The live test DB is opened read-only. All writes happen in a temporary backup.
"""
import argparse
from pathlib import Path
import sqlite3
import tempfile

from poc.fixture import cleanup_queue, install_queue

ROOT = Path(__file__).resolve().parents[1]


def probe(version):
    source_path = ROOT / "data" / version / "config" / "cache" / "library.db"
    if not source_path.is_file():
        raise FileNotFoundError(f"Disposable test DB missing: {source_path}")
    build = ROOT / ".poc-build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lms-failure-", dir=build) as directory:
        clone_path = Path(directory) / "library.db"
        with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as source:
            with sqlite3.connect(clone_path) as clone:
                source.backup(clone)
        with sqlite3.connect(clone_path) as clone:
            clone.execute("PRAGMA foreign_keys=ON")
            cleanup_queue(clone)
            install_queue(clone)
            track = clone.execute("SELECT id,title FROM tracks WHERE title IS NOT NULL LIMIT 1").fetchone()
            if not track:
                raise RuntimeError("No track in disposable test database")
            track_id, original = track
            clone.execute("UPDATE tracks SET title=? WHERE id=?", (original, track_id))
            clone.commit()
            normal_count = clone.execute("SELECT count(*) FROM ps_dirty").fetchone()[0]
            if normal_count != 1:
                raise AssertionError(f"Expected one dirty entry, got {normal_count}")
            clone.execute("DROP TABLE ps_dirty")
            clone.commit()
            try:
                clone.execute("UPDATE tracks SET title=? WHERE id=?", (original, track_id))
                clone.commit()
            except sqlite3.OperationalError as error:
                clone.rollback()
                failure = str(error)
            else:
                raise AssertionError("Broken queue trigger unexpectedly allowed source write")
            if "ps_dirty" not in failure:
                raise AssertionError(f"Unexpected write failure: {failure}")
            cleanup_queue(clone)
            cleanup_queue(clone)
            clone.execute("UPDATE tracks SET title=? WHERE id=?", (original, track_id))
            clone.commit()
            print(f"version={version} normal_dirty={normal_count}")
            print(f"missing_queue_write_error={failure}")
            print("cleanup_twice=ok source_write_after_cleanup=ok")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=("9.1.0", "9.1", "9.2"))
    probe(parser.parse_args().version)
