"""Kill a staging worker around atomic activation on an LMS 9.2 DB backup.

Linux POC only. The live isolated test library is opened read-only; all writes
and SIGKILL targets are confined to child processes and a temporary directory.
"""
import argparse
from contextlib import closing
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile

from poc.lms_poll_stage_probe import ROOT, TEST_DB, build_stage, open_index, read_source, validate
from poc.change_gate import ChangeGate
from poc.fixture import index_schema
from poc.lms_index_probe import apply_batch


def child(source_path, active_path, stage_path, point):
    if point == "during_build":
        found = read_source(source_path)
        with closing(open_index(stage_path)) as index:
            index_schema(index, extension=True)
            first = next(iter(found.items()))
            apply_batch(index, [(0, first[0][0], first[0][1], first[1])])
        print("READY during_build", flush=True)
        signal.pause()
        return
    build_stage(source_path, stage_path)
    if point == "before_swap":
        print("READY before_swap", flush=True)
        signal.pause()
    os.replace(stage_path, active_path)
    print("READY after_swap", flush=True)
    signal.pause()


def kill_at(source_path, active_path, stage_path, point):
    worker = subprocess.Popen(
        [sys.executable, "-m", "poc.lms_stage_kill_probe", "--child",
         str(source_path), str(active_path), str(stage_path), point],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready = worker.stdout.readline().strip()
        if ready != f"READY {point}":
            raise AssertionError(f"Worker did not reach {point}: {ready}; {worker.stderr.read()}")
        os.kill(worker.pid, signal.SIGKILL)
        worker.communicate(timeout=10)
        if worker.returncode != -signal.SIGKILL:
            raise AssertionError(f"Worker exit={worker.returncode}, expected SIGKILL")
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.communicate()


def is_current(active_path, found):
    if not active_path.is_file():
        return False
    try:
        validate(active_path, found)
        return True
    except (sqlite3.DatabaseError, AssertionError):
        return False


def recover(source_path, active_path, orphan_stage):
    # Never activate an orphan left by a dead worker: its source generation and
    # completeness are unknown. Rebuild from a fresh consistent snapshot.
    if orphan_stage.exists():
        orphan_stage.unlink()
    found = read_source(source_path)
    if is_current(active_path, found):
        return "retained"
    replacement = active_path.with_name("recovery-stage.db")
    build_stage(source_path, replacement)
    validate(replacement, read_source(source_path))
    os.replace(replacement, active_path)
    validate(active_path, read_source(source_path))
    return "rebuilt"


def probe():
    if sys.platform != "linux":
        raise RuntimeError("SIGKILL staging POC is Linux-only")
    if not TEST_DB.is_file():
        raise FileNotFoundError(TEST_DB)
    build = ROOT / ".poc-build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lms-stage-kill-", dir=build) as directory:
        directory = Path(directory)
        source_path = directory / "library.db"
        active_path = directory / "active.db"
        with closing(sqlite3.connect(f"file:{TEST_DB}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(source_path)) as clone:
                source.backup(clone)
        first_stage = directory / "stage-initial.db"
        initial, _ = build_stage(source_path, first_stage)
        os.replace(first_stage, active_path)

        with closing(sqlite3.connect(source_path)) as clone:
            artist_id = clone.execute(
                "SELECT id FROM contributors WHERE name IS NOT NULL LIMIT 1").fetchone()[0]
            clone.execute("UPDATE contributors SET name='POC Before Swap' WHERE id=?", (artist_id,))
            clone.commit()
        partial_stage = directory / "stage-partial.db"
        kill_at(source_path, active_path, partial_stage, "during_build")
        if not partial_stage.is_file() or is_current(partial_stage, read_source(source_path)):
            raise AssertionError("Partially built orphan was missing or incorrectly valid")
        partial_recovery = recover(source_path, active_path, partial_stage)
        if partial_recovery != "rebuilt" or partial_stage.exists():
            raise AssertionError("Partial-stage recovery did not rebuild and discard orphan")

        with closing(sqlite3.connect(source_path)) as clone:
            clone.execute("UPDATE contributors SET name='POC Before Swap 2' WHERE id=?", (artist_id,))
            clone.commit()
        before_stage = directory / "stage-before.db"
        kill_at(source_path, active_path, before_stage, "before_swap")
        if is_current(active_path, read_source(source_path)):
            raise AssertionError("Old active index unexpectedly matches changed source")
        if not before_stage.is_file():
            raise AssertionError("Expected orphan staging file")
        before_recovery = recover(source_path, active_path, before_stage)
        if before_recovery != "rebuilt" or before_stage.exists():
            raise AssertionError("Pre-swap recovery did not rebuild and discard orphan")

        with closing(sqlite3.connect(source_path)) as clone:
            clone.execute("UPDATE contributors SET name='POC After Swap' WHERE id=?", (artist_id,))
            clone.commit()
        after_stage = directory / "stage-after.db"
        kill_at(source_path, active_path, after_stage, "after_swap")
        if after_stage.exists():
            raise AssertionError("Stage remained after atomic activation")
        after_recovery = recover(source_path, active_path, after_stage)
        if after_recovery != "retained":
            raise AssertionError("Post-swap recovery rebuilt a valid active index")

        before_inode = source_path.stat().st_ino
        with closing(sqlite3.connect(source_path)) as clone:
            clone.execute("DELETE FROM contributors WHERE id=?", (artist_id,))
            clone.execute("INSERT INTO contributors(id,name) VALUES (?,?)",
                          (artist_id, "POC Same ID Replacement"))
            clone.commit()
        if source_path.stat().st_ino != before_inode:
            raise AssertionError("In-place same-ID source test replaced the DB file")
        in_place_recovery = recover(source_path, active_path, directory / "absent-stage.db")
        if in_place_recovery != "rebuilt":
            raise AssertionError("Same-ID in-place change was not detected")
        validate(active_path, read_source(source_path))
        with closing(open_index(active_path)) as index:
            row = index.execute(
                "SELECT original FROM ps_entity WHERE entity_type='artist' AND entity_id=?",
                (artist_id,)).fetchone()
            if row != ("POC Same ID Replacement",):
                raise AssertionError(row)

        # A source commit in the final validation/swap window must remain
        # pending for a fresh reconciliation; the stage is never trusted as
        # current merely because its atomic swap succeeded.
        gate = ChangeGate(source_path)
        try:
            _, initial_version, _ = gate.check()
            gate.completed(initial_version, full=True)
            _, staged_version, _ = gate.check()
            race_stage = directory / "stage-race.db"
            build_stage(source_path, race_stage)
            with closing(sqlite3.connect(source_path)) as clone:
                clone.execute("UPDATE contributors SET name='POC During Swap' WHERE id=?",
                              (artist_id,))
                clone.commit()
            os.replace(race_stage, active_path)
            gate.completed(staged_version, full=True)
            if not gate.pending or gate.check()[0] != "pending":
                raise AssertionError("Concurrent source commit was lost at activation")
            race_recovery = recover(source_path, active_path, directory / "absent-stage.db")
            if race_recovery != "rebuilt":
                raise AssertionError("Activation race was not repaired")
            validate(active_path, read_source(source_path))
        finally:
            gate.close()
        print(f"version=9.2 clone_only=1 initial={initial} "
              f"during_build_kill=SIGKILL recovery={partial_recovery} "
              f"before_swap_kill=SIGKILL recovery={before_recovery} "
              f"after_swap_kill=SIGKILL recovery={after_recovery} "
              f"in_place_same_id={in_place_recovery} "
              f"commit_during_activation={race_recovery} integrity=ok")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", nargs=4, metavar=("SOURCE", "ACTIVE", "STAGE", "POINT"))
    args = parser.parse_args()
    if args.child:
        child(Path(args.child[0]), Path(args.child[1]), Path(args.child[2]), args.child[3])
    else:
        probe()
