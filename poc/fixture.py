"""Disposable SQLite fixture using the LMS 9.2 column names relevant to the POCs."""
import sqlite3

TYPES = {"track": ("tracks", "title"), "album": ("albums", "title"),
         "artist": ("contributors", "name"), "genre": ("genres", "name")}

def connect(path):
    db = sqlite3.connect(path, timeout=0.2)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=200")
    return db

def source_schema(db):
    db.executescript("""
      CREATE TABLE tracks(id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL,
        title BLOB, audio BOOL, remote BOOL, content_type TEXT);
      CREATE TABLE albums(id INTEGER PRIMARY KEY AUTOINCREMENT, title BLOB);
      CREATE TABLE contributors(id INTEGER PRIMARY KEY AUTOINCREMENT, name BLOB);
      CREATE TABLE genres(id INTEGER PRIMARY KEY AUTOINCREMENT, name BLOB);
      CREATE TABLE metainformation(name TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)

def install_queue(db):
    db.execute("""CREATE TABLE IF NOT EXISTS ps_dirty(
      seq INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL,
      entity_id INTEGER NOT NULL, UNIQUE(entity_type,entity_id))""")
    for kind, (table, column) in TYPES.items():
        for suffix, event, ref in (("ai", "INSERT", "NEW"),
                                   ("au", f"UPDATE OF id,{column}", "NEW"),
                                   ("ad", "DELETE", "OLD")):
            values = [f"('{kind}',{ref}.id)"]
            if suffix == "au":
                values.insert(0, f"('{kind}',OLD.id)")
            body = ";".join("INSERT OR REPLACE INTO ps_dirty(entity_type,entity_id) "
                            f"VALUES {value}" for value in values)
            db.execute(f"CREATE TRIGGER ps_{table}_{suffix} AFTER {event} ON {table} "
                       f"BEGIN {body}; END")

def cleanup_queue(db):
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'ps_%'"):
        db.execute(f'DROP TRIGGER "{name}"')
    db.execute("DROP TABLE IF EXISTS ps_dirty")

def index_schema(db, extension=False):
    db.executescript("""
      CREATE TABLE ps_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE ps_vocab(id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL,
        normalized TEXT NOT NULL, UNIQUE(entity_type,normalized));
      CREATE TABLE ps_entity(entity_type TEXT NOT NULL,entity_id INTEGER NOT NULL,
        original TEXT NOT NULL,vocab_id INTEGER NOT NULL REFERENCES ps_vocab(id),
        PRIMARY KEY(entity_type,entity_id));
      CREATE INDEX ps_entity_vocab ON ps_entity(vocab_id);
    """)
    if extension:
        for kind in TYPES:
            db.execute(f"CREATE VIRTUAL TABLE ps_spell_{kind} USING spellfix1")

def consume_one(source, index):
    """POC-only two-commit worker; caller serializes it and checks generation."""
    item = source.execute("SELECT seq,entity_type,entity_id FROM ps_dirty ORDER BY seq LIMIT 1").fetchone()
    if item is None:
        return False
    seq, kind, ident = item
    table, col = TYPES[kind]
    row = source.execute(f"SELECT {col} FROM {table} WHERE id=?", (ident,)).fetchone()
    name = row[0] if row else None
    with index:
        index.execute("DELETE FROM ps_entity WHERE entity_type=? AND entity_id=?", (kind, ident))
        if name:
            normalized = str(name).casefold().strip()
            index.execute("INSERT OR IGNORE INTO ps_vocab(entity_type,normalized) VALUES (?,?)", (kind, normalized))
            vocab_id = index.execute("SELECT id FROM ps_vocab WHERE entity_type=? AND normalized=?", (kind, normalized)).fetchone()[0]
            index.execute("INSERT INTO ps_entity VALUES (?,?,?,?)", (kind, ident, name, vocab_id))
    with source:
        source.execute("DELETE FROM ps_dirty WHERE seq=?", (seq,))
    return True
