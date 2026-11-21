"""Exercise trigger-free deltas against a temporary backup of a test LMS DB."""
import argparse
from pathlib import Path
import sqlite3
import tempfile

from poc.fixture import TYPES, index_schema
from poc.lms_index_probe import apply_batch, load_extension, text_name

ROOT = Path(__file__).resolve().parents[1]


def snapshot(source):
    source.execute("BEGIN")
    try:
        found = {}
        for kind, (table, column) in TYPES.items():
            for ident, name in source.execute(f"SELECT id,{column} FROM {table}"):
                name = text_name(name)
                if name:
                    found[(kind, ident)] = name
        source.commit()
        return found
    except BaseException:
        source.rollback()
        raise


def delta(index, found):
    prior = {(kind, ident): name for kind, ident, name in
             index.execute("SELECT entity_type,entity_id,original FROM ps_entity")}
    keys = found.keys() | prior.keys()
    return [(0, kind, ident, found.get((kind, ident))) for kind, ident in sorted(keys)
            if found.get((kind, ident)) != prior.get((kind, ident))]


def probe(version):
    source_path = ROOT / "data" / version / "config" / "cache" / "library.db"
    if not source_path.is_file():
        raise FileNotFoundError(f"Disposable test DB missing: {source_path}")
    build = ROOT / ".poc-build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lms-delta-", dir=build) as directory:
        clone_path = Path(directory) / "library.db"
        index_path = Path(directory) / "index.db"
        with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as original:
            with sqlite3.connect(clone_path) as clone:
                original.backup(clone)
        with sqlite3.connect(clone_path) as clone, sqlite3.connect(index_path) as index:
            clone.execute("PRAGMA foreign_keys=ON")
            index.execute("PRAGMA foreign_keys=ON")
            load_extension(index)
            index_schema(index, extension=True)
            initial = snapshot(clone)
            apply_batch(index, [(0, kind, ident, name) for (kind, ident), name in initial.items()])
            if delta(index, snapshot(clone)):
                raise AssertionError("Unchanged snapshot created a delta")

            artist_id, artist_name = clone.execute("SELECT id,name FROM contributors WHERE name IS NOT NULL LIMIT 1").fetchone()
            new_genre_id = clone.execute("SELECT coalesce(max(id),0)+1 FROM genres").fetchone()[0]
            clone.execute("UPDATE contributors SET name=? WHERE id=?", ("POC Renamed Artist", artist_id))
            clone.execute("INSERT INTO genres(id,name) VALUES (?,?)", (new_genre_id, "POC Genre A"))
            clone.commit()
            first = delta(index, snapshot(clone))
            if {(row[1], row[2]) for row in first} != {("artist", artist_id), ("genre", new_genre_id)}:
                raise AssertionError(f"Unexpected first delta: {first}")
            apply_batch(index, first)

            clone.execute("UPDATE contributors SET name=? WHERE id=?", (artist_name, artist_id))
            clone.execute("DELETE FROM genres WHERE id=?", (new_genre_id,))
            clone.execute("INSERT INTO genres(id,name) VALUES (?,?)", (new_genre_id, "POC Genre B"))
            clone.commit()
            second = delta(index, snapshot(clone))
            if {(row[1], row[2]) for row in second} != {("artist", artist_id), ("genre", new_genre_id)}:
                raise AssertionError(f"Unexpected same-ID replacement delta: {second}")
            apply_batch(index, second)

            clone.execute("DELETE FROM genres WHERE id=?", (new_genre_id,))
            clone.commit()
            third = delta(index, snapshot(clone))
            if len(third) != 1 or third[0][1:] != ("genre", new_genre_id, None):
                raise AssertionError(f"Unexpected deletion delta: {third}")
            apply_batch(index, third)
            if delta(index, snapshot(clone)):
                raise AssertionError("Final snapshot was not reconciled")
            integrity = index.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise AssertionError(integrity)
            print(f"version={version} initial={len(initial)} first={len(first)} "
                  f"same_id={len(second)} deleted={len(third)} integrity={integrity}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=("9.1.0", "9.1", "9.2"))
    probe(parser.parse_args().version)
