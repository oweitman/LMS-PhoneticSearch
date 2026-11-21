"""Extension-dependent P1/P2 checks. Set SPELLFIX_BINARY to run them."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

class SpellfixPOCs(unittest.TestCase):
    def test_p1_memory_and_file(self):
        binary = os.environ.get("SPELLFIX_BINARY")
        if not binary:
            self.skipTest("SPELLFIX_BINARY is unset")
        from poc.spellfix_probe import probe
        probe(binary)

    def test_p2_direct_virtual_table_trigger_on_unloaded_connection(self):
        binary = os.environ.get("SPELLFIX_BINARY")
        if not binary:
            self.skipTest("SPELLFIX_BINARY is unset")
        build = Path(__file__).resolve().parents[1] / ".poc-build"
        build.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=build) as directory:
            path = str(Path(directory) / "source.db")
            creator = sqlite3.connect(path)
            creator.enable_load_extension(True)
            try:
                creator.execute("SELECT load_extension(?, 'sqlite3_spellfix_init')", (str(Path(binary).resolve()),))
            finally:
                creator.enable_load_extension(False)
            creator.execute("CREATE TABLE tracks(id INTEGER PRIMARY KEY, title TEXT)")
            creator.execute("CREATE VIRTUAL TABLE words USING spellfix1")
            creator.execute("CREATE TRIGGER direct AFTER INSERT ON tracks BEGIN INSERT INTO words(word) VALUES(NEW.title); END")
            creator.commit()
            unloaded = sqlite3.connect(path)
            try:
                with self.assertRaises(sqlite3.DatabaseError):
                    unloaded.execute("INSERT INTO tracks(title) VALUES('Beatles')")
                unloaded.rollback()
            finally:
                unloaded.close()
                creator.close()

if __name__ == "__main__":
    unittest.main()
