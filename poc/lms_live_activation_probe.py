"""Activate a stale POC stage during a real isolated LMS 9.2 wipe.

Only the disposable test LMS receives a wipecache RPC. Its library database is
read-only to this probe; stage and active index files stay under .poc-build.
"""
import os
from pathlib import Path
import tempfile
import time

from poc.change_gate import ChangeGate
from poc.lms_live_wipe_probe import rpc, source_counts
from poc.lms_poll_stage_probe import ROOT, TEST_DB, build_stage, read_source, validate
from poc.lms_stage_kill_probe import recover


def probe():
    status = rpc("serverstatus", "0", "10")
    if status.get("version") != "9.2.0" or status.get("httpport") != "9002":
        raise RuntimeError(f"Wrong LMS target: {status}")
    if not TEST_DB.is_file() or rpc("rescanprogress").get("rescan") != 0:
        raise RuntimeError("Isolated 9.2 DB missing or scanner already active")
    before = source_counts()
    if before["tracks"] < 100:
        raise RuntimeError(f"Unexpected test library: {before}")
    build = ROOT / ".poc-build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lms-live-activation-", dir=build) as directory:
        directory = Path(directory)
        stage = directory / "stage.db"
        active = directory / "active.db"
        initial, replayed = build_stage(TEST_DB, stage)
        gate = ChangeGate(TEST_DB)
        try:
            _, baseline_version, _ = gate.check()
            gate.completed(baseline_version, full=True)
            if gate.check()[0] != "unchanged":
                raise RuntimeError("Source changed while preparing the probe")
            accepted = rpc("wipecache")
            seen_scan = False
            activated_at_zero = False
            stale_rejected = False
            stable_since = None
            started = time.monotonic()
            while time.monotonic() - started < 120:
                scanning = rpc("rescanprogress").get("rescan") == 1
                counts = source_counts()
                if scanning:
                    seen_scan = True
                    stable_since = None
                elif seen_scan and stable_since is None:
                    stable_since = time.monotonic()
                if scanning and counts["tracks"] == 0 and not activated_at_zero:
                    os.replace(stage, active)
                    activated_at_zero = True
                    try:
                        validate(active, read_source(TEST_DB))
                    except AssertionError:
                        stale_rejected = True
                    gate.completed(baseline_version, full=True)
                    if not gate.pending or gate.check()[0] != "pending":
                        raise AssertionError("Scanner commit was lost across activation")
                if (activated_at_zero and not scanning and stable_since is not None
                        and time.monotonic() - stable_since >= 5
                        and counts["tracks"] >= before["tracks"]):
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError(f"Scanner did not settle or zero-track window missed: "
                                   f"scan={seen_scan} activated={activated_at_zero}")
            after = source_counts()
            if after != before or not stale_rejected:
                raise AssertionError(f"Unexpected post-wipe state: after={after} stale={stale_rejected}")
            reason, version, _ = gate.check()
            if reason != "pending":
                raise AssertionError(f"Expected pending full reconciliation, got {reason}")
            recovery = recover(TEST_DB, active, directory / "absent-stage.db")
            validate(active, read_source(TEST_DB))
            gate.completed(version, full=True)
            print(f"version=9.2 wipecache_accepted={int(accepted == {})} "
                  f"scan_seen={int(seen_scan)} stage_entities={initial} "
                  f"stage_replayed={replayed} activated_at_zero={int(activated_at_zero)} "
                  f"stale_rejected={int(stale_rejected)} pending_after_swap=1 "
                  f"post_scan_recovery={recovery} source_counts_restored=1 integrity=ok")
        finally:
            gate.close()


if __name__ == "__main__":
    probe()
