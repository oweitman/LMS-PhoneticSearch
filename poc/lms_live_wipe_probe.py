"""Observe a real wipecache on the isolated LMS 9.2 and rebuild off-source.

Run on the remote POC host, where 127.0.0.1:9002 is bound to the disposable
LMS 9.2 container. The LMS database is opened read-only by this probe.
"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from urllib.request import Request, urlopen

from poc.change_gate import ChangeGate
from poc.lms_poll_stage_probe import ROOT, TEST_DB, build_stage, read_source, validate


def rpc(*command):
    payload = json.dumps({"id": 1, "method": "slim.request",
                          "params": ["", list(command)]}).encode()
    request = Request("http://127.0.0.1:9002/jsonrpc.js", data=payload,
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=15) as response:
        result = json.load(response)
    if "error" in result:
        raise RuntimeError(result["error"])
    return result.get("result", {})


def source_counts():
    with closing(sqlite3.connect(f"file:{TEST_DB}?mode=ro", uri=True)) as source:
        source.execute("BEGIN")
        try:
            counts = {table: source.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for table in ("tracks", "albums", "contributors", "genres")}
            source.commit()
            return counts
        except BaseException:
            source.rollback()
            raise


def probe():
    if not TEST_DB.is_file() or TEST_DB.resolve() != (
            ROOT / "data/9.2/config/cache/library.db").resolve():
        raise RuntimeError("Isolated LMS 9.2 database missing")
    status = rpc("serverstatus", "0", "10")
    if status.get("version") != "9.2.0" or status.get("httpport") != "9002":
        raise RuntimeError(f"Wrong LMS target: {status}")
    if rpc("rescanprogress").get("rescan") != 0:
        raise RuntimeError("Refusing to start wipecache while scanner is active")
    before = source_counts()
    if before["tracks"] < 100:
        raise RuntimeError(f"Test library unexpectedly small: {before}")
    identity = TEST_DB.stat()
    gate = ChangeGate(TEST_DB)
    try:
        _, version, _ = gate.check()
        gate.completed(version, full=True)
        accepted = rpc("wipecache")
        started = time.monotonic()
        seen_scanning = False
        seen_commits = 0
        min_tracks = before["tracks"]
        stable_since = None
        while time.monotonic() - started < 120:
            scanning = rpc("rescanprogress").get("rescan") == 1
            reason, version, _ = gate.check()
            if reason != "unchanged":
                seen_commits += 1
                gate.completed(version, full=False)
                stable_since = None
            if scanning:
                seen_scanning = True
                stable_since = None
            elif seen_scanning and stable_since is None:
                stable_since = time.monotonic()
            counts = source_counts()
            min_tracks = min(min_tracks, counts["tracks"])
            if (seen_scanning and stable_since is not None
                    and time.monotonic() - stable_since >= 5
                    and counts["tracks"] >= before["tracks"]):
                break
            time.sleep(0.2)
        else:
            raise TimeoutError(f"Wipe did not settle: scanning={seen_scanning} "
                               f"commits={seen_commits} counts={counts}")
        after = source_counts()
        current = TEST_DB.stat()
        build = ROOT / ".poc-build"
        build.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="lms-live-wipe-", dir=build) as directory:
            stage = Path(directory) / "stage.db"
            initial, replayed = build_stage(TEST_DB, stage)
            validate(stage, read_source(TEST_DB))
        if not seen_commits:
            raise AssertionError("ChangeGate observed no scanner commits")
        if after != before:
            raise AssertionError(f"Library counts changed: before={before} after={after}")
        print(f"version=9.2 wipecache_accepted={int(accepted == {})} "
              f"scan_seen={int(seen_scanning)} commits_seen={seen_commits} "
              f"same_inode={int(identity.st_ino == current.st_ino)} "
              f"min_tracks={min_tracks} before={before} after={after} "
              f"stage_entities={initial} replayed={replayed} integrity=ok")
    finally:
        gate.close()


if __name__ == "__main__":
    probe()
