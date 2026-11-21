"""Synthetic Linux POC scale probe; never opens an LMS database."""
import argparse
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter

from poc.fixture import index_schema
from poc.lms_index_probe import apply_batch, load_extension

ROOT = Path(__file__).resolve().parents[1]


def run(count):
    build = ROOT / ".poc-build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="scale-", dir=build) as directory:
        source_path = Path(directory) / "source.db"
        index_path = Path(directory) / "index.db"
        with sqlite3.connect(source_path) as source:
            source.execute("CREATE TABLE tracks(id INTEGER PRIMARY KEY,title TEXT)")
            started = perf_counter()
            source.executemany("INSERT INTO tracks(id,title) VALUES (?,?)",
                               ((ident, f"Album Track {ident:06d}") for ident in range(1, count + 1)))
            source.commit()
            populate = perf_counter() - started
            started = perf_counter()
            source.execute("BEGIN")
            snapshot = [(0, "track", ident, name) for ident, name in
                        source.execute("SELECT id,title FROM tracks")]
            source.commit()
            snapshot_time = perf_counter() - started
        with sqlite3.connect(index_path) as index:
            index.execute("PRAGMA foreign_keys=ON")
            load_extension(index)
            index_schema(index, extension=True)
            started = perf_counter()
            apply_batch(index, snapshot)
            index_time = perf_counter() - started
            started = perf_counter()
            current = dict(index.execute("SELECT entity_id,original FROM ps_entity WHERE entity_type='track'"))
            unchanged = sum(current.get(ident) == name for _, _, ident, name in snapshot)
            compare_time = perf_counter() - started
            if unchanged != count:
                raise AssertionError(f"unchanged={unchanged} expected={count}")
            with sqlite3.connect(source_path) as source:
                source.execute("UPDATE tracks SET title='Changed Album Track' WHERE id=42")
                source.commit()
                started = perf_counter()
                changed_snapshot = [(0, "track", ident, name) for ident, name in
                                    source.execute("SELECT id,title FROM tracks")]
                changed = [row for row in changed_snapshot if current.get(row[2]) != row[3]]
                detect_time = perf_counter() - started
            if len(changed) != 1 or changed[0][2] != 42:
                raise AssertionError(f"changed={changed[:3]} count={len(changed)}")
            apply_batch(index, changed)
            started = perf_counter()
            hits = index.execute("SELECT word FROM ps_spell_track WHERE word MATCH ? LIMIT 5",
                                 ("album trak 000042",)).fetchall()
            query_ms = (perf_counter() - started) * 1000
            integrity = index.execute("PRAGMA integrity_check").fetchone()[0]
            indexed = index.execute("SELECT count(*) FROM ps_entity").fetchone()[0]
            if indexed != count or integrity != "ok":
                raise AssertionError(f"indexed={indexed} integrity={integrity}")
            print(f"count={count} populate_s={populate:.3f} snapshot_s={snapshot_time:.3f} "
                  f"index_s={index_time:.3f} unchanged_compare_s={compare_time:.3f} "
                  f"one_change_detect_s={detect_time:.3f} query_ms={query_ms:.3f} "
                  f"source_bytes={source_path.stat().st_size} index_bytes={index_path.stat().st_size} "
                  f"hits={len(hits)} integrity={integrity}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("count", type=int, choices=(10_000, 100_000, 500_000))
    run(parser.parse_args().count)
