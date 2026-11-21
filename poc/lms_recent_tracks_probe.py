"""POC of the 9.2 track timestamp fast path on a temporary DB backup."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time

from poc.lms_delta_probe import delta, snapshot
from poc.lms_index_probe import apply_batch
from poc.lms_poll_stage_probe import ROOT, TEST_DB, build_stage, open_index
from poc.recent_delta import apply_recent, recent_entities


def probe():
    if not TEST_DB.is_file():
        raise FileNotFoundError(TEST_DB)
    build = ROOT / ".poc-build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lms-recent-", dir=build) as directory:
        clone_path = Path(directory) / "library.db"
        index_path = Path(directory) / "index.db"
        with closing(sqlite3.connect(f"file:{TEST_DB}?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(clone_path)) as clone:
                original.backup(clone)
        with closing(sqlite3.connect(clone_path)) as clone:
            clone.execute("PRAGMA foreign_keys=ON")
            watermark = clone.execute("SELECT max(updated_time) FROM tracks").fetchone()[0]
            build_stage(clone_path, index_path)
            fresh_time = max(int(time.time()), watermark + 2)
            album = clone.execute("INSERT INTO albums(title) VALUES ('POC New Album')").lastrowid
            artist = clone.execute("INSERT INTO contributors(name) VALUES ('POC New Artist')").lastrowid
            genre = clone.execute("INSERT INTO genres(name) VALUES ('POC New Genre')").lastrowid
            track = clone.execute("INSERT INTO tracks(url,title,audio,remote,album,updated_time) "
                                  "VALUES (?,?,?,?,?,?)",
                                  ("file:///poc-new-track", "POC New Track", 1, 0, album, fresh_time)).lastrowid
            clone.execute("INSERT INTO contributor_track(role,contributor,track) VALUES (1,?,?)", (artist, track))
            clone.execute("INSERT INTO genre_track(genre,track) VALUES (?,?)", (genre, track))
            clone.commit()

            cutoff = watermark  # Inclusive, so same-second changes are reconsidered.
            plan = [row[3] for row in clone.execute(
                "EXPLAIN QUERY PLAN SELECT id,title,album FROM tracks WHERE updated_time>=?", (cutoff,))]
            started = time.perf_counter()
            changed = clone.execute("SELECT id,title,album FROM tracks WHERE updated_time>=?", (cutoff,)).fetchall()
            query_ms = (time.perf_counter() - started) * 1000
            if track not in {row[0] for row in changed}:
                raise AssertionError(f"recent tracks={changed}")
            album_name = clone.execute("SELECT title FROM albums WHERE id=?", (album,)).fetchone()[0]
            artist_name = clone.execute(
                "SELECT c.name FROM contributors c JOIN contributor_track ct ON ct.contributor=c.id "
                "WHERE ct.track=?", (track,)).fetchone()[0]
            genre_name = clone.execute(
                "SELECT g.name FROM genres g JOIN genre_track gt ON gt.genre=g.id "
                "WHERE gt.track=?", (track,)).fetchone()[0]
            if (album_name, artist_name, genre_name) != (
                    "POC New Album", "POC New Artist", "POC New Genre"):
                raise AssertionError("Related entities missing")
            candidates, recent_count, newest = recent_entities(clone, cutoff)
            expected = {("track", track), ("album", album), ("artist", artist), ("genre", genre)}
            if candidates is None or not expected <= candidates.keys():
                raise AssertionError(f"Fast-path candidates missing: {candidates}")
            with closing(open_index(index_path)) as index:
                applied = apply_recent(index, candidates)
                if applied != 4:
                    raise AssertionError(f"Fast-path applied={applied}, expected=4")
                hit = index.execute(
                    "SELECT word FROM ps_spell_artist WHERE word MATCH ? LIMIT 1",
                    ("poc new artist",)).fetchone()
                if hit != ("poc new artist",):
                    raise AssertionError(f"New artist search={hit}")

            # Deletion leaves no recent track row; an exact reconciliation remains required.
            clone.execute("DELETE FROM tracks WHERE id=?", (track,))
            clone.commit()
            after_delete = clone.execute("SELECT id FROM tracks WHERE updated_time>=?", (cutoff,)).fetchall()
            if track in {row[0] for row in after_delete}:
                raise AssertionError("Deleted track still visible")
            with closing(open_index(index_path)) as index:
                # The fast path cannot infer this deletion; periodic/full pass can.
                if not index.execute("SELECT 1 FROM ps_entity WHERE entity_type='track' AND entity_id=?",
                                     (track,)).fetchone():
                    raise AssertionError("Fast path unexpectedly removed deleted track")
                missing = delta(index, snapshot(clone))
                apply_batch(index, missing)
                if index.execute("SELECT 1 FROM ps_entity WHERE entity_type='track' AND entity_id=?",
                                 (track,)).fetchone():
                    raise AssertionError("Full reconciliation failed to remove deleted track")
            print(f"version=9.2 recent_tracks={recent_count} newest={newest} "
                  f"new_entities_indexed={applied} artist_search=ok deletion_needs_full=1 "
                  f"query_ms={query_ms:.3f} plan={plan}")


if __name__ == "__main__":
    probe()
