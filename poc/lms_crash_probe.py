"""Kill a POC index writer before/after commit on disposable LMS DB backups."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

from poc.fixture import index_schema
from poc.lms_delta_probe import delta, snapshot
from poc.lms_index_probe import apply_batch, load_extension

ROOT = Path(__file__).resolve().parents[1]


def open_index(path):
    index = sqlite3.connect(path)
    index.execute("PRAGMA foreign_keys=ON")
    load_extension(index)
    return index


def child(index_path, mode, ident, name):
    index = open_index(index_path)
    if mode == "before":
        index.execute("BEGIN")
        index.execute("DELETE FROM ps_entity WHERE entity_type='artist' AND entity_id=?", (ident,))
        os._exit(42)
    apply_batch(index, [(0, "artist", ident, name)])
    os._exit(43)


def crash(index_path, mode, ident, name):
    result = subprocess.run([sys.executable, "-m", "poc.lms_crash_probe", "--child",
                             str(index_path), mode, str(ident), name], check=False)
    expected = 42 if mode == "before" else 43
    if result.returncode != expected:
        raise AssertionError(f"Child exit={result.returncode}, expected={expected}")


def probe(version):
    source_path = ROOT / "data" / version / "config" / "cache" / "library.db"
    if not source_path.is_file():
        raise FileNotFoundError(f"Disposable test DB missing: {source_path}")
    build = ROOT / ".poc-build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lms-crash-", dir=build) as directory:
        clone_path = Path(directory) / "library.db"
        index_path = Path(directory) / "index.db"
        with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as original:
            with sqlite3.connect(clone_path) as clone:
                original.backup(clone)
        with closing(sqlite3.connect(clone_path)) as clone, closing(open_index(index_path)) as index:
            index_schema(index, extension=True)
            initial = snapshot(clone)
            apply_batch(index, [(0, kind, ident, name) for (kind, ident), name in initial.items()])
            artist_id = clone.execute("SELECT id FROM contributors WHERE name IS NOT NULL LIMIT 1").fetchone()[0]
            clone.execute("UPDATE contributors SET name='POC Crash Before' WHERE id=?", (artist_id,))
            clone.commit()
        crash(index_path, "before", artist_id, "POC Crash Before")
        with closing(sqlite3.connect(clone_path)) as clone, closing(open_index(index_path)) as index:
            pending = delta(index, snapshot(clone))
            if len(pending) != 1 or pending[0][1:3] != ("artist", artist_id):
                raise AssertionError(f"Before-commit recovery delta={pending}")
            apply_batch(index, pending)
            clone.execute("UPDATE contributors SET name='POC Crash After' WHERE id=?", (artist_id,))
            clone.commit()
        crash(index_path, "after", artist_id, "POC Crash After")
        with closing(sqlite3.connect(clone_path)) as clone, closing(open_index(index_path)) as index:
            remaining = delta(index, snapshot(clone))
            integrity = index.execute("PRAGMA integrity_check").fetchone()[0]
            if remaining or integrity != "ok":
                raise AssertionError(f"After-commit remaining={remaining} integrity={integrity}")
            print(f"version={version} before_commit_exit=42 recovered={len(pending)} "
                  f"after_commit_exit=43 remaining=0 integrity={integrity}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("version", nargs="?", choices=("9.1.0", "9.1", "9.2"))
    parser.add_argument("--child", nargs=4, metavar=("INDEX", "MODE", "ID", "NAME"))
    args = parser.parse_args()
    if args.child:
        child(Path(args.child[0]), args.child[1], int(args.child[2]), args.child[3])
    elif args.version:
        probe(args.version)
    else:
        parser.error("version required")
