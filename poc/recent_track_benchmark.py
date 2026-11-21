"""Synthetic cost of scanning LMS-style updated_time without a source index."""
import argparse
from pathlib import Path
import sqlite3
from statistics import median
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]


def run(count):
    build = ROOT / ".poc-build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="recent-track-", dir=build) as directory:
        path = Path(directory) / "source.db"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE tracks(id INTEGER PRIMARY KEY,title TEXT,updated_time INTEGER)")
            db.executemany("INSERT INTO tracks(id,title,updated_time) VALUES (?,?,?)",
                           ((ident, f"Track {ident:06d}", 1) for ident in range(1, count + 1)))
            db.execute("UPDATE tracks SET updated_time=2 WHERE id=?", (count,))
            db.commit()
            plan = [row[3] for row in db.execute(
                "EXPLAIN QUERY PLAN SELECT id,title FROM tracks WHERE updated_time>=2")]
            times = []
            for _ in range(20):
                started = perf_counter()
                found = db.execute("SELECT id,title FROM tracks WHERE updated_time>=2").fetchall()
                times.append((perf_counter() - started) * 1000)
                if found != [(count, f"Track {count:06d}")]:
                    raise AssertionError(found)
            ordered = sorted(times)
            print(f"count={count} recent=1 median_ms={median(times):.3f} "
                  f"p95_ms={ordered[18]:.3f} max_ms={max(times):.3f} "
                  f"db_bytes={path.stat().st_size} plan={plan}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("count", type=int, choices=(100_000, 500_000))
    run(parser.parse_args().count)
