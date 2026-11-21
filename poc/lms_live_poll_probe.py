"""Read-only polling of the isolated LMS 9.2 library during a real scan."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time

from poc.lms_delta_probe import delta
from poc.change_gate import ChangeGate
from poc.lms_poll_stage_probe import DEFAULT_INTERVAL, TEST_DB, build_stage, open_index, read_source
from poc.lms_index_probe import apply_batch
from poc.recent_delta import apply_recent, recent_entities

ROOT = Path(__file__).resolve().parents[1]


def probe(interval, cycles, source_path):
    source_path = Path(source_path).resolve()
    allowed = (ROOT / ".poc-build").resolve()
    if source_path != TEST_DB.resolve() and allowed not in source_path.parents:
        raise ValueError("Source must be isolated LMS 9.2 DB or a POC backup")
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    build = ROOT / ".poc-build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lms-live-poll-", dir=build) as directory:
        index_path = Path(directory) / "index.db"
        initial, replayed = build_stage(source_path, index_path)
        with closing(sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)) as source:
            watermark = source.execute("SELECT coalesce(max(updated_time),0) FROM tracks").fetchone()[0]
        print(json.dumps({"event": "ready", "at": time.time(),
                          "initial": initial, "replayed": replayed,
                          "watermark": watermark}), flush=True)
        next_tick = time.monotonic()
        gate = ChangeGate(source_path)
        try:
            for cycle in range(cycles):
                time.sleep(max(0, next_tick - time.monotonic()))
                reason, version, gate_ms = gate.check()
                snapshot_ms = compare_ms = 0.0
                changes = []
                found = None
                recent_count = 0
                mode = "skip"
                if reason == "db_changed":
                    started = time.perf_counter()
                    with closing(sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)) as source:
                        candidates, recent_count, newest = recent_entities(source, max(0, watermark - 1))
                    snapshot_ms = (time.perf_counter() - started) * 1000
                    if candidates is not None:
                        with closing(open_index(index_path)) as index:
                            changed_count = apply_recent(index, candidates)
                        changes = [None] * changed_count
                        compare_ms = (time.perf_counter() - started) * 1000 - snapshot_ms
                        watermark = max(watermark, newest)
                        mode = "fast"
                if reason != "unchanged" and mode != "fast":
                    started = time.perf_counter()
                    found = read_source(source_path)
                    snapshot_ms = (time.perf_counter() - started) * 1000
                    with closing(open_index(index_path)) as index:
                        changes = delta(index, found)
                        compare_ms = (time.perf_counter() - started) * 1000 - snapshot_ms
                        if changes:
                            apply_batch(index, changes)
                    with closing(sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)) as source:
                        full_watermark = source.execute("SELECT coalesce(max(updated_time),0) FROM tracks").fetchone()[0]
                    mode = "full"
                if reason != "unchanged":
                    gate.completed(version, full=mode == "full")
                    if mode == "full" and not gate.pending:
                        watermark = full_watermark
                print(json.dumps({"event": "poll", "cycle": cycle, "at": time.time(),
                                  "reason": reason, "gate_ms": round(gate_ms, 3),
                                  "mode": mode, "recent_tracks": recent_count,
                                  "source_entities": len(found) if found is not None else None,
                                  "changes": len(changes), "snapshot_ms": round(snapshot_ms, 3),
                                  "compare_ms": round(compare_ms, 3)}), flush=True)
                next_tick += interval
        finally:
            gate.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    parser.add_argument("--cycles", type=int, default=4)
    parser.add_argument("--source", default=str(TEST_DB))
    args = parser.parse_args()
    if not 5 <= args.interval <= 3600 or not 1 <= args.cycles <= 100:
        parser.error("interval must be 5..3600 seconds and cycles 1..100")
    probe(args.interval, args.cycles, args.source)
