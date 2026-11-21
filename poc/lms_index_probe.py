"""Disposable POC worker for the isolated Compose LMS libraries only.

This is a transaction experiment, not the production indexer: it has no
generation marker, staging switch, background scheduling or LMS API.
"""
import argparse
from pathlib import Path
import sqlite3
import sys
from poc.fixture import TYPES, connect, index_schema

ROOT = Path(__file__).resolve().parents[1]

def text_name(raw):
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw

def load_extension(db):
    binary = ROOT / ".poc-build" / "spellfix.so"
    if not binary.is_file():
        raise FileNotFoundError(binary)
    db.enable_load_extension(True)
    try:
        db.execute("SELECT load_extension(?, 'sqlite3_spellfix_init')", (str(binary),))
    finally:
        db.enable_load_extension(False)

def open_index(version):
    path = ROOT / ".poc-build" / f"index-{version}-poc.db"
    db = connect(path)
    load_extension(db)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='ps_meta'").fetchone():
        index_schema(db, extension=True)
        db.execute("INSERT INTO ps_meta VALUES ('poc_schema','1')")
        db.commit()
    return db

def read_batch(source, size):
    source.execute("BEGIN")
    try:
        rows = source.execute("SELECT seq,entity_type,entity_id FROM ps_dirty ORDER BY seq LIMIT ?", (size,)).fetchall()
        batch = []
        for seq, kind, ident in rows:
            table, column = TYPES[kind]
            row = source.execute(f"SELECT {column} FROM {table} WHERE id=?", (ident,)).fetchone()
            batch.append((seq, kind, ident, text_name(row[0]) if row else None))
        source.commit()
        return batch
    except BaseException:
        source.rollback()
        raise

def apply_batch(index, batch):
    with index:
        for _, kind, ident, name in batch:
            old = index.execute("SELECT vocab_id FROM ps_entity WHERE entity_type=? AND entity_id=?",
                                (kind, ident)).fetchone()
            index.execute("DELETE FROM ps_entity WHERE entity_type=? AND entity_id=?", (kind, ident))
            if old and not index.execute("SELECT 1 FROM ps_entity WHERE vocab_id=?", old).fetchone():
                index.execute(f"DELETE FROM ps_spell_{kind} WHERE rowid=?", old)
                index.execute("DELETE FROM ps_vocab WHERE id=?", old)
            if name:
                normalized = " ".join(name.casefold().split())
                cursor = index.execute("INSERT OR IGNORE INTO ps_vocab(entity_type,normalized) VALUES (?,?)",
                                       (kind, normalized))
                vocab_id = index.execute("SELECT id FROM ps_vocab WHERE entity_type=? AND normalized=?",
                                         (kind, normalized)).fetchone()[0]
                if cursor.rowcount:
                    index.execute(f"INSERT INTO ps_spell_{kind}(rowid,word,rank,langid) VALUES (?,?,1,0)",
                                  (vocab_id, normalized))
                index.execute("INSERT INTO ps_entity VALUES (?,?,?,?)", (kind, ident, name, vocab_id))

def sync(version, size):
    source_path = ROOT / "data" / version / "config" / "cache" / "library.db"
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    identity = source_path.stat()
    source = connect(source_path)
    index = open_index(version)
    try:
        batch = read_batch(source, size)
        if not batch:
            print("queue_empty")
            return
        apply_batch(index, batch)
        current = source_path.stat()
        if (identity.st_dev, identity.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("Source DB file changed before ACK; queue retained")
        with source:
            source.executemany("DELETE FROM ps_dirty WHERE seq=?", [(row[0],) for row in batch])
        print(f"processed={len(batch)} remaining={source.execute('SELECT count(*) FROM ps_dirty').fetchone()[0]}")
    finally:
        index.close()
        source.close()

def query(version, kind, term):
    if kind not in TYPES:
        raise ValueError(kind)
    index = open_index(version)
    try:
        rows = index.execute(f"SELECT word,distance,score FROM ps_spell_{kind} WHERE word MATCH ? LIMIT 5",
                             (term.casefold(),)).fetchall()
        for row in rows:
            print(f"word={row[0]!r} distance={row[1]} score={row[2]}")
    finally:
        index.close()

def verify(version):
    index = open_index(version)
    try:
        print(f"integrity={index.execute('PRAGMA integrity_check').fetchone()[0]}")
        for kind in TYPES:
            entities = index.execute("SELECT count(*) FROM ps_entity WHERE entity_type=?", (kind,)).fetchone()[0]
            vocab = index.execute("SELECT count(*) FROM ps_vocab WHERE entity_type=?", (kind,)).fetchone()[0]
            spellfix = index.execute(f"SELECT count(*) FROM ps_spell_{kind}").fetchone()[0]
            print(f"{kind}: entities={entities} vocab={vocab} spellfix={spellfix}")
        orphan = index.execute("SELECT count(*) FROM ps_vocab v WHERE NOT EXISTS "
                               "(SELECT 1 FROM ps_entity e WHERE e.vocab_id=v.id)").fetchone()[0]
        print(f"orphan_vocab={orphan}")
    finally:
        index.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=("9.1.0", "9.1", "9.2"))
    parser.add_argument("action", choices=("sync", "query", "verify"))
    parser.add_argument("args", nargs="*")
    args = parser.parse_args()
    if args.action == "sync":
        sync(args.version, int(args.args[0]) if args.args else 100)
    elif args.action == "verify":
        verify(args.version)
    elif len(args.args) == 2:
        query(args.version, args.args[0], args.args[1])
    else:
        parser.error("query needs KIND TERM")
