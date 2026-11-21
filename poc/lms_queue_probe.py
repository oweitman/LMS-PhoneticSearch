"""Operate only on the two disposable Compose LMS databases."""
import argparse
import sqlite3
from pathlib import Path
from poc.fixture import install_queue, cleanup_queue

PROJECT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=("9.1.0", "9.1", "9.2"))
    parser.add_argument("action", choices=("install", "status", "cleanup"))
    args = parser.parse_args()
    path = PROJECT / "data" / args.version / "config" / "cache" / "library.db"
    if not path.is_file():
        raise SystemExit(f"Missing disposable test DB: {path}")
    db = sqlite3.connect(f"file:{path}?mode=rw", uri=True, timeout=5)
    try:
        if args.action == "install":
            with db:
                install_queue(db)
        elif args.action == "cleanup":
            with db:
                cleanup_queue(db)
        print(f"version={args.version} action={args.action} journal={db.execute('PRAGMA journal_mode').fetchone()[0]}")
        for table in ("tracks", "albums", "contributors", "genres"):
            print(f"{table}={db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]}")
        queue = db.execute("SELECT name FROM sqlite_master WHERE name='ps_dirty'").fetchone()
        print(f"queue={db.execute('SELECT count(*) FROM ps_dirty').fetchone()[0] if queue else 'absent'}")
        triggers = db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'ps_%'").fetchone()[0]
        print(f"triggers={triggers}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
