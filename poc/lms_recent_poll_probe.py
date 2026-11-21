"""Measure five-second discovery of a new track and its related names."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

from poc.lms_poll_stage_probe import ROOT, TEST_DB


def probe():
    if not TEST_DB.is_file():
        raise FileNotFoundError(TEST_DB)
    build = ROOT / ".poc-build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lms-recent-poll-", dir=build) as directory:
        clone_path = Path(directory) / "library.db"
        with closing(sqlite3.connect(f"file:{TEST_DB}?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(clone_path)) as clone:
                original.backup(clone)
        worker = subprocess.Popen(
            [sys.executable, "-m", "poc.lms_live_poll_probe", "--source", str(clone_path),
             "--cycles", "3"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            ready_line = worker.stdout.readline()
            if not ready_line:
                raise RuntimeError(f"Worker did not become ready: {worker.stderr.read()}")
            ready = json.loads(ready_line)
            if ready.get("event") != "ready":
                raise AssertionError(ready)
            time.sleep(1)
            with closing(sqlite3.connect(clone_path)) as clone:
                clone.execute("PRAGMA foreign_keys=ON")
                latest = clone.execute("SELECT coalesce(max(updated_time),0) FROM tracks").fetchone()[0]
                timestamp = max(int(time.time()), latest + 2)
                album = clone.execute("INSERT INTO albums(title) VALUES ('POC Poll Album')").lastrowid
                artist = clone.execute("INSERT INTO contributors(name) VALUES ('POC Poll Artist')").lastrowid
                genre = clone.execute("INSERT INTO genres(name) VALUES ('POC Poll Genre')").lastrowid
                track = clone.execute(
                    "INSERT INTO tracks(url,title,audio,remote,album,updated_time) VALUES (?,?,?,?,?,?)",
                    ("file:///poc-poll-track", "POC Poll Track", 1, 0, album, timestamp)).lastrowid
                clone.execute("INSERT INTO contributor_track(role,contributor,track) VALUES (1,?,?)",
                              (artist, track))
                clone.execute("INSERT INTO genre_track(genre,track) VALUES (?,?)", (genre, track))
                clone.commit()
            committed_at = time.time()
            output, errors = worker.communicate(timeout=25)
        except BaseException:
            worker.kill()
            worker.communicate()
            raise
        if worker.returncode != 0:
            raise RuntimeError(f"Worker exit={worker.returncode}: {errors}")
        cycles = [json.loads(line) for line in output.splitlines()]
        detected = next((row for row in cycles if row.get("changes", 0) >= 4), None)
        if detected is None or detected["mode"] != "fast":
            raise AssertionError(f"No fast-path detection: {cycles}")
        lag = detected["at"] - committed_at
        if not 0 <= lag <= 5.5:
            raise AssertionError(f"Lag {lag:.3f}s exceeds five-second POC target")
        print(f"version=9.2 clone_only=1 mode={detected['mode']} "
              f"new_entities={detected['changes']} recent_tracks={detected['recent_tracks']} "
              f"lag_s={lag:.3f} gate_ms={detected['gate_ms']:.3f}")


if __name__ == "__main__":
    probe()
