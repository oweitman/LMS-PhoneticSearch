"""Trigger-free 9.2 POC: staging swap and a configurable polling interval.

Only a temporary backup of the isolated LMS 9.2 library is modified.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

from poc.fixture import index_schema
from poc.change_gate import ChangeGate
from poc.lms_delta_probe import delta, snapshot
from poc.lms_index_probe import apply_batch, load_extension, text_name

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = ROOT / "data" / "9.2" / "config" / "cache" / "library.db"
DEFAULT_INTERVAL = 5.0
MIN_INTERVAL = 5.0
MAX_INTERVAL = 3600.0


def open_index(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    load_extension(db)
    return db


def read_source(path):
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as source:
        return snapshot(source)


def validate(path, expected):
    with closing(open_index(path)) as index:
        integrity = index.execute("PRAGMA integrity_check").fetchone()[0]
        remaining = delta(index, expected)
        if integrity != "ok" or remaining:
            raise AssertionError(f"stage integrity={integrity} remaining={len(remaining)}")


def build_stage(source_path, stage_path):
    found = read_source(source_path)
    with closing(open_index(stage_path)) as index:
        index_schema(index, extension=True)
        apply_batch(index, [(0, kind, ident, name) for (kind, ident), name in found.items()])
        # Replay changes that landed while the first snapshot was indexed.
        latest = read_source(source_path)
        changes = delta(index, latest)
        if changes:
            apply_batch(index, changes)
    validate(stage_path, latest)
    return len(found), len(changes)


def artist_name(index, ident):
    return index.execute("SELECT original FROM ps_entity WHERE entity_type='artist' AND entity_id=?",
                         (ident,)).fetchone()[0]


def poll(source_path, index_path, interval, cycles):
    next_tick = time.monotonic()
    gate = ChangeGate(source_path)
    try:
        for number in range(cycles):
            time.sleep(max(0, next_tick - time.monotonic()))
            reason, version, gate_ms = gate.check()
            changes = []
            if reason != "unchanged":
                found = read_source(source_path)
                with closing(open_index(index_path)) as index:
                    changes = delta(index, found)
                    if changes:
                        apply_batch(index, changes)
                gate.completed(version, full=True)
            print(json.dumps({"cycle": number, "at": time.time(), "reason": reason,
                              "gate_ms": round(gate_ms, 3), "changes": len(changes)}), flush=True)
            next_tick += interval
    finally:
        gate.close()


def probe(interval):
    if not TEST_DB.is_file():
        raise FileNotFoundError(f"Disposable test LMS 9.2 DB missing: {TEST_DB}")
    build = ROOT / ".poc-build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lms-poll-stage-", dir=build) as directory:
        directory = Path(directory)
        source_path = directory / "library.db"
        active_path = directory / "active.db"
        with closing(sqlite3.connect(f"file:{TEST_DB}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(source_path)) as clone:
                source.backup(clone)
        stage1 = directory / "stage1.db"
        initial, replayed = build_stage(source_path, stage1)
        os.replace(stage1, active_path)
        with closing(sqlite3.connect(source_path)) as clone:
            artist_id, original = clone.execute(
                "SELECT id,name FROM contributors WHERE name IS NOT NULL LIMIT 1").fetchone()
            original = text_name(original)
            clone.execute("UPDATE contributors SET name='POC Staged Artist' WHERE id=?", (artist_id,))
            clone.commit()
        with closing(open_index(active_path)) as old_reader:
            if artist_name(old_reader, artist_id) != original:
                raise AssertionError("Active index changed before swap")
            bad_stage = directory / "bad-stage.db"
            bad_stage.write_bytes(b"not a SQLite database")
            try:
                validate(bad_stage, read_source(source_path))
            except sqlite3.DatabaseError:
                pass
            else:
                raise AssertionError("Corrupt stage was accepted")
            if artist_name(old_reader, artist_id) != original:
                raise AssertionError("Failed stage changed active reader")
            stage2 = directory / "stage2.db"
            _, replayed2 = build_stage(source_path, stage2)
            os.replace(stage2, active_path)
            if artist_name(old_reader, artist_id) != original:
                raise AssertionError("Old reader did not retain old generation")
            with closing(open_index(active_path)) as new_reader:
                if artist_name(new_reader, artist_id) != "POC Staged Artist":
                    raise AssertionError("New reader did not see new generation")

        command = [sys.executable, "-m", "poc.lms_poll_stage_probe", "--worker",
                   str(source_path), str(active_path), str(interval), "3"]
        worker = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(1.0)
            with closing(sqlite3.connect(source_path)) as clone:
                clone.execute("UPDATE contributors SET name='POC Polled Artist' WHERE id=?", (artist_id,))
                clone.commit()
            changed_at = time.time()
            output, errors = worker.communicate(timeout=interval * 3 + 10)
        except BaseException:
            worker.kill()
            worker.communicate()
            raise
        if worker.returncode != 0:
            raise RuntimeError(f"worker exit={worker.returncode}: {errors}")
        cycles = [json.loads(line) for line in output.splitlines()]
        observed = next((item for item in cycles if item["changes"]), None)
        if not observed:
            raise AssertionError(f"No change detected: {cycles}")
        lag = observed["at"] - changed_at
        if not 0 <= lag <= interval + 0.5:
            raise AssertionError(f"lag={lag:.3f}s interval={interval}s cycles={cycles}")
        if cycles[0]["reason"] != "pending" or observed["reason"] != "db_changed":
            raise AssertionError(f"Unexpected change gate sequence: {cycles}")
        validate(active_path, read_source(source_path))
        with closing(open_index(active_path)) as index:
            if artist_name(index, artist_id) != "POC Polled Artist":
                raise AssertionError("Poll did not update active index")
        print(f"version=9.2 initial={initial} first_stage_replay={replayed} "
              f"second_stage_replay={replayed2} corrupt_stage=rejected "
              f"old_reader=old new_reader=new interval_s={interval:g} "
              f"cycles={len(cycles)} lag_s={lag:.3f} "
              f"idle_skips={sum(c['reason'] == 'unchanged' for c in cycles)} integrity=ok")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                        help="POC poll interval in seconds (default: 5; range: 5..3600)")
    parser.add_argument("--worker", nargs=4, metavar=("SOURCE", "INDEX", "INTERVAL", "CYCLES"))
    args = parser.parse_args()
    if args.worker:
        poll(Path(args.worker[0]), Path(args.worker[1]), float(args.worker[2]), int(args.worker[3]))
    elif not MIN_INTERVAL <= args.interval <= MAX_INTERVAL:
        parser.error("--interval must be between 5 and 3600 seconds")
    else:
        probe(args.interval)
