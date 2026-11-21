"""Build a throwaway index from a read-only LMS snapshot, without triggers."""
import argparse
from pathlib import Path
import sqlite3
import tempfile
import time

from poc.fixture import TYPES, index_schema
from poc.lms_index_probe import apply_batch, load_extension, text_name

ROOT = Path(__file__).resolve().parents[1]


def probe(version):
    source_path = ROOT / "data" / version / "config" / "cache" / "library.db"
    if not source_path.is_file():
        raise FileNotFoundError(f"Disposable test DB missing: {source_path}")
    build = ROOT / ".poc-build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lms-reconcile-", dir=build) as directory:
        index_path = Path(directory) / "index.db"
        started = time.perf_counter()
        source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        try:
            source.execute("BEGIN")
            snapshot = []
            counts = {}
            for kind, (table, column) in TYPES.items():
                rows = source.execute(f"SELECT id,{column} FROM {table}").fetchall()
                counts[kind] = len(rows)
                snapshot.extend((0, kind, ident, text_name(name)) for ident, name in rows)
            source.commit()
        finally:
            source.close()
        snapshot_seconds = time.perf_counter() - started
        with sqlite3.connect(index_path) as index:
            index.execute("PRAGMA foreign_keys=ON")
            load_extension(index)
            index_schema(index, extension=True)
            apply_batch(index, snapshot)
            indexed = index.execute("SELECT count(*) FROM ps_entity").fetchone()[0]
            integrity = index.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise AssertionError(integrity)
            # Empty names are intentionally absent from the index.
            expected = sum(1 for _, _, _, name in snapshot if name)
            if indexed != expected:
                raise AssertionError(f"indexed={indexed} expected={expected}")
            total_seconds = time.perf_counter() - started
            print(f"version={version} counts={counts} indexed={indexed}")
            print(f"snapshot_seconds={snapshot_seconds:.3f} total_seconds={total_seconds:.3f} "
                  f"index_bytes={index_path.stat().st_size} integrity={integrity}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=("9.1.0", "9.1", "9.2"))
    probe(parser.parse_args().version)
