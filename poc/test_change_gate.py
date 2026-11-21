"""Check the cheap change signal against separate SQLite connections."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from poc.change_gate import ChangeGate


@unittest.skipIf(os.name == "nt", "File replacement with an open SQLite handle is Linux POC scope")
class ChangeGatePOC(unittest.TestCase):
    def test_external_writes_race_and_file_replacement(self):
        build = Path(__file__).resolve().parents[1] / ".poc-build"
        build.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=build) as directory:
            path = Path(directory) / "source.db"
            with sqlite3.connect(path) as writer:
                writer.execute("CREATE TABLE item(id INTEGER PRIMARY KEY, name TEXT)")
                writer.execute("INSERT INTO item(name) VALUES('first')")
            gate = ChangeGate(path, force_seconds=900)
            try:
                reason, version, _ = gate.check()
                self.assertEqual(reason, "pending")
                gate.completed(version, full=True)
                self.assertEqual(gate.check()[0], "unchanged")

                periodic = ChangeGate(path, force_seconds=0)
                try:
                    _, periodic_version, _ = periodic.check()
                    periodic.completed(periodic_version, full=True)
                    self.assertEqual(periodic.check()[0], "periodic")
                finally:
                    periodic.close()

                # A fast delta must not postpone the scheduled full pass.
                gate.last_full -= 901
                with sqlite3.connect(path) as writer:
                    writer.execute("UPDATE item SET name='delta' WHERE id=1")
                reason, version, _ = gate.check()
                self.assertEqual(reason, "db_changed")
                gate.completed(version, full=False)
                self.assertEqual(gate.check()[0], "periodic")
                gate.completed(version, full=True)
                self.assertEqual(gate.check()[0], "unchanged")

                with sqlite3.connect(path) as writer:
                    writer.execute("UPDATE item SET name='second' WHERE id=1")
                reason, version, _ = gate.check()
                self.assertEqual(reason, "db_changed")

                # A commit during reconciliation must force another pass.
                with sqlite3.connect(path) as writer:
                    writer.execute("UPDATE item SET name='third' WHERE id=1")
                gate.completed(version)
                reason, version, _ = gate.check()
                self.assertEqual(reason, "pending")
                gate.completed(version)
                self.assertEqual(gate.check()[0], "unchanged")

                replacement = Path(directory) / "replacement.db"
                with sqlite3.connect(replacement) as writer:
                    writer.execute("CREATE TABLE item(id INTEGER PRIMARY KEY, name TEXT)")
                    writer.execute("INSERT INTO item(name) VALUES('replacement')")
                os.replace(replacement, path)
                self.assertEqual(gate.check()[0], "file_replaced")
            finally:
                gate.close()


if __name__ == "__main__":
    unittest.main()
