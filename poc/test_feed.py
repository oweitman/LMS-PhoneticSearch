"""Check that a published LMS catalog and package agree on version and hash."""

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from scripts.prepare_feed import TARGETS, build


class FeedPackageTest(unittest.TestCase):
    def test_catalog_package_and_idempotence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / 'candidate.zip'
            with zipfile.ZipFile(package, 'w') as archive:
                archive.writestr('PhoneticSearch/install.xml',
                                 '<extension><version>0.1.0</version></extension>')
                archive.writestr('PhoneticSearch/HTML/EN/plugins/PhoneticSearch/html/icon.png', b'png')
                archive.writestr('PhoneticSearch/Bin/manifest.json',
                                 json.dumps({'schema': 1, **{target: {} for target in TARGETS}}))
            report = root / 'report.json'
            report.write_text(json.dumps({
                'sha256': hashlib.sha256(package.read_bytes()).hexdigest(),
                'complete': True, 'included': list(TARGETS), 'missing': [],
                'revision': 'fixture',
            }))
            source = root / 'source'
            source.mkdir()
            (source / 'install.xml').write_text(
                '<extension><version>0.1.0</version><targetApplication>'
                '<minVersion>9.2.0</minVersion><maxVersion>*</maxVersion>'
                '</targetApplication></extension>')
            feed = root / 'feed'
            self.assertTrue(build(package, report, feed, 42, source))
            entry = ET.parse(feed / 'public.xml').find('plugins/plugin')
            self.assertEqual(entry.get('version'), '0.1.42')
            self.assertEqual(entry.get('minTarget'), '9.2.0')
            published = feed / 'PhoneticSearch-0.1.42.zip'
            self.assertEqual(entry.findtext('sha'), hashlib.sha1(published.read_bytes()).hexdigest())
            self.assertEqual(entry.findtext('url'),
                             'https://github.com/oweitman/LMS-PhoneticSearch/'
                             'releases/download/v0.1.42/PhoneticSearch-0.1.42.zip')
            self.assertTrue(entry.findtext('icon').endswith('/icon.png'))
            with zipfile.ZipFile(published) as archive:
                self.assertEqual(ET.fromstring(archive.read('install.xml'))
                                 .findtext('version'), '0.1.42')
                self.assertIn('HTML/EN/plugins/PhoneticSearch/html/icon.png', archive.namelist())
            self.assertFalse(build(package, report, feed, 43, source))
            report_data = json.loads(report.read_text())
            report_data['complete'] = False
            report.write_text(json.dumps(report_data))
            with self.assertRaisesRegex(ValueError, 'complete six-target'):
                build(package, report, feed, 44, source)


if __name__ == '__main__':
    unittest.main()
