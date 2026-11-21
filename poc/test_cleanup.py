"""The manual cleanup removes plugin data and leaves LMS library data intact."""
import tempfile
import unittest
from pathlib import Path

from scripts.cleanup_plugin_data import cleanup


class CleanupTest(unittest.TestCase):
    def test_idempotent_and_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'cache' / 'PhoneticSearch'
            cache.mkdir(parents=True)
            (cache / 'index.db').write_bytes(b'plugin index')
            library = root / 'cache' / 'library.db'
            library.write_bytes(b'LMS library')
            prefs = root / 'prefs' / 'plugin' / 'phoneticsearch.prefs'
            prefs.parent.mkdir(parents=True)
            prefs.write_text('reconcile_interval_seconds: 5')
            cleanup(root)
            self.assertTrue(cache.exists())
            self.assertTrue(prefs.exists())
            cleanup(root, apply=True)
            cleanup(root, apply=True)
            self.assertFalse(cache.exists())
            self.assertFalse(prefs.exists())
            self.assertEqual(library.read_bytes(), b'LMS library')


if __name__ == '__main__':
    unittest.main()
