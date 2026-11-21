"""P1/P4: load spellfix on a dedicated connection; accepts only local binary path."""
import argparse
from pathlib import Path
import sqlite3
import tempfile

def probe(binary):
    binary = Path(binary).resolve(strict=True)
    build = Path(__file__).resolve().parents[1] / ".poc-build"
    build.mkdir(exist_ok=True)
    for path in (":memory:", None):
        with tempfile.TemporaryDirectory(dir=build) as directory:
            name = path or str(Path(directory) / "index.db")
            db = sqlite3.connect(name)
            try:
                db.enable_load_extension(True)
                try:
                    db.execute("SELECT load_extension(?, 'sqlite3_spellfix_init')", (str(binary),))
                finally:
                    db.enable_load_extension(False)
                try:
                    db.execute("SELECT load_extension(?, 'sqlite3_spellfix_init')", (str(binary),))
                except sqlite3.OperationalError:
                    pass
                else:
                    raise AssertionError("extension loading stayed enabled")
                db.execute("CREATE VIRTUAL TABLE words USING spellfix1")
                db.execute("INSERT INTO words(word) VALUES ('beatles')")
                result = db.execute("SELECT word FROM words WHERE word MATCH 'beatls'").fetchone()
                assert result == ("beatles",), result
                print(f"PASS {name}: {result[0]}")
            finally:
                db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("binary")
    probe(parser.parse_args().binary)
