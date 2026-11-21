import sqlite3
import tempfile
import unittest
from pathlib import Path
from poc.fixture import connect, source_schema, install_queue, cleanup_queue, index_schema, consume_one

class IsolatedPOCs(unittest.TestCase):
    def setUp(self):
        build = Path(__file__).resolve().parents[1] / ".poc-build"
        build.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=build)
        self.addCleanup(self.tmp.cleanup)
        self.source_path = Path(self.tmp.name) / "library.db"
        self.index_path = Path(self.tmp.name) / "plugin.db"
        self.source = connect(self.source_path)
        self.addCleanup(self.source.close)
        source_schema(self.source)
        install_queue(self.source)
        self.index = connect(self.index_path)
        self.addCleanup(self.index.close)
        index_schema(self.index)

    def test_p2_second_connection_without_extension_and_rollback(self):
        scanner = connect(self.source_path)
        self.addCleanup(scanner.close)
        scanner.execute("INSERT INTO tracks(url,title,audio,remote) VALUES (?,?,1,0)", ("file:///a", "Beatles"))
        scanner.commit()
        self.assertEqual(self.source.execute("SELECT entity_type,entity_id FROM ps_dirty").fetchall(), [("track", 1)])
        scanner.execute("UPDATE tracks SET title='Beatles 2' WHERE id=1")
        scanner.rollback()
        self.assertEqual(self.source.execute("SELECT title FROM tracks").fetchone()[0], "Beatles")
        scanner.execute("UPDATE tracks SET title='Beatles 3' WHERE id=1")
        scanner.commit()
        self.assertEqual(self.source.execute("SELECT count(*) FROM ps_dirty").fetchone()[0], 1)
        scanner.execute("DELETE FROM tracks WHERE id=1")
        scanner.commit()
        self.assertEqual(self.source.execute("SELECT count(*) FROM ps_dirty").fetchone()[0], 1)

    def test_p2_replace_and_conditional_ack(self):
        self.source.execute("INSERT INTO genres(id,name) VALUES(1,'Rock')")
        self.source.commit()
        old = self.source.execute("SELECT seq FROM ps_dirty").fetchone()[0]
        self.source.execute("INSERT OR REPLACE INTO genres(id,name) VALUES(1,'Pop')")
        self.source.commit()
        new = self.source.execute("SELECT seq FROM ps_dirty").fetchone()[0]
        self.assertGreater(new, old)
        self.source.execute("DELETE FROM ps_dirty WHERE seq=?", (old,))
        self.assertEqual(self.source.execute("SELECT seq FROM ps_dirty").fetchone()[0], new)

    def test_p3_rebuild_disable_enable_replace_cleanup(self):
        self.source.execute("INSERT INTO albums(title) VALUES('Queen')")
        self.source.commit()
        self.assertTrue(consume_one(self.source, self.index))
        self.assertEqual(self.index.execute("SELECT original FROM ps_entity").fetchone()[0], "Queen")
        cleanup_queue(self.source)
        self.assertEqual(self.source.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'ps_%'").fetchone()[0], 0)
        install_queue(self.source)
        self.source.execute("UPDATE albums SET title='Queen II' WHERE id=1")
        self.source.commit()
        self.assertTrue(consume_one(self.source, self.index))
        self.assertEqual(self.index.execute("SELECT original FROM ps_entity").fetchone()[0], "Queen II")
        self.source.close()
        self.source_path.unlink()
        self.source = connect(self.source_path)
        self.addCleanup(self.source.close)
        source_schema(self.source)
        install_queue(self.source)
        self.assertEqual(self.source.execute("SELECT count(*) FROM albums").fetchone()[0], 0)
        cleanup_queue(self.source)
        cleanup_queue(self.source)

    def test_p6_retry_after_index_commit_and_busy(self):
        self.source.execute("INSERT INTO contributors(name) VALUES('Beyoncé')")
        self.source.commit()
        seq = self.source.execute("SELECT seq FROM ps_dirty").fetchone()[0]
        # Simulate death after index commit and before source acknowledgement.
        self.index.execute("INSERT INTO ps_vocab(entity_type,normalized) VALUES('artist','beyoncé')")
        self.index.execute("INSERT INTO ps_entity VALUES('artist',1,'Beyoncé',1)")
        self.index.commit()
        self.assertTrue(consume_one(self.source, self.index))
        self.assertEqual(self.source.execute("SELECT count(*) FROM ps_dirty").fetchone()[0], 0)
        self.assertEqual(self.index.execute("SELECT count(*) FROM ps_entity").fetchone()[0], 1)
        lock = connect(self.source_path)
        self.addCleanup(lock.close)
        lock.execute("BEGIN IMMEDIATE")
        with self.assertRaises(sqlite3.OperationalError):
            self.source.execute("INSERT INTO genres(name) VALUES('Rock')")
        lock.rollback()
        self.source.execute("INSERT INTO genres(name) VALUES('Rock')")
        self.source.commit()
        self.assertGreater(self.source.execute("SELECT seq FROM ps_dirty").fetchone()[0], seq)

    def test_p3_full_wipe_dirties_existing_ids(self):
        self.source.execute("INSERT INTO tracks(url,title) VALUES('file:///a','Old')")
        self.source.execute("INSERT INTO genres(name) VALUES('Jazz')")
        self.source.commit()
        while consume_one(self.source, self.index):
            pass
        self.source.execute("DELETE FROM tracks")
        self.source.execute("DELETE FROM genres")
        self.source.commit()
        self.assertEqual(self.source.execute("SELECT count(*) FROM ps_dirty").fetchone()[0], 2)
        while consume_one(self.source, self.index):
            pass
        self.assertEqual(self.index.execute("SELECT count(*) FROM ps_entity").fetchone()[0], 0)

    def test_p6_corrupt_index_is_rejected_without_source_change(self):
        self.index.close()
        self.index_path.write_bytes(b"not a SQLite database")
        broken = connect(self.index_path)
        self.addCleanup(broken.close)
        with self.assertRaises(sqlite3.DatabaseError):
            broken.execute("PRAGMA integrity_check").fetchone()
        self.source.execute("INSERT INTO albums(title) VALUES('Still writable')")
        self.source.commit()
        self.assertEqual(self.source.execute("SELECT count(*) FROM ps_dirty").fetchone()[0], 1)

if __name__ == "__main__":
    unittest.main()
