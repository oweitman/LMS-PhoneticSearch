"""Turn a complete CI package into an LMS repository catalog and stable ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPO = 'https://github.com/oweitman/LMS-PhoneticSearch'
RAW = 'https://raw.githubusercontent.com/oweitman/LMS-PhoneticSearch'
ICON = f'{RAW}/main/src/HTML/EN/plugins/PhoneticSearch/html/icon.png'
TARGETS = ('linux-x86_64', 'linux-aarch64', 'linux-armv7',
           'macos-x86_64', 'macos-arm64', 'windows-x86_64')


def digest(data: bytes, algorithm: str = 'sha256') -> str:
    return hashlib.new(algorithm, data).hexdigest()


def build(package: Path, report_path: Path, feed: Path, run_number: int,
          source_root: Path = ROOT / 'src') -> bool:
    report = json.loads(report_path.read_text(encoding='utf-8'))
    original = package.read_bytes()
    if digest(original) != report['sha256']:
        raise ValueError('CI package hash differs from build report')
    if not report['complete'] or set(report['included']) != set(TARGETS) or report['missing']:
        raise ValueError('Only a complete six-target package may enter the LMS feed')
    with zipfile.ZipFile(package) as archive:
        if archive.testzip() is not None:
            raise ValueError('Corrupt CI package')
        names = archive.namelist()
        if 'PhoneticSearch/install.xml' not in names or \
                'PhoneticSearch/HTML/EN/plugins/PhoneticSearch/html/icon.png' not in names:
            raise ValueError('Required plugin metadata or icon missing')
        manifest = json.loads(archive.read('PhoneticSearch/Bin/manifest.json'))
        if set(manifest) != set(TARGETS) | {'schema'}:
            raise ValueError('Binary manifest does not match the platform matrix')
    state_path = feed / 'feed-state.json'
    if state_path.is_file():
        previous = json.loads(state_path.read_text(encoding='utf-8'))
        if previous['input_sha256'] == report['sha256']:
            print('feed=unchanged')
            return False
    else:
        previous = None
    source_install = ET.parse(source_root / 'install.xml').getroot()
    base_version = source_install.findtext('version')
    if not base_version or not re.fullmatch(r'\d+\.\d+\.\d+', base_version):
        raise ValueError('Expected numeric source plugin version')
    major, minor, patch = (int(value) for value in base_version.split('.'))
    new_patch = max(patch, run_number)
    if previous:
        old = tuple(int(value) for value in previous['version'].split('.'))
        if (major, minor) == old[:2]:
            new_patch = max(new_patch, old[2] + 1)
        elif (major, minor) < old[:2]:
            raise ValueError('Source plugin version would decrease published version')
    version = f'{major}.{minor}.{new_patch}'
    output_name = f'PhoneticSearch-{version}.zip'
    feed.mkdir(parents=True, exist_ok=True)
    output = feed / output_name
    with zipfile.ZipFile(package) as original_zip, \
            zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as published:
        for original_name in sorted(original_zip.namelist()):
            if not original_name.startswith('PhoneticSearch/'):
                raise ValueError('Unexpected path outside plugin root')
            name = original_name.removeprefix('PhoneticSearch/')
            if not name or '..' in Path(name).parts:
                raise ValueError('Unsafe plugin archive path')
            data = original_zip.read(original_name)
            if name == 'install.xml':
                xml = data.decode('utf-8')
                xml, count = re.subn(r'<version>[^<]+</version>',
                                     f'<version>{version}</version>', xml, count=1)
                if count != 1:
                    raise ValueError('Plugin version element not found')
                data = xml.encode('utf-8')
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            published.writestr(info, data)
    payload = output.read_bytes()
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert ET.fromstring(archive.read('install.xml')).findtext('version') == version
    catalog = ET.Element('extensions')
    ET.SubElement(ET.SubElement(catalog, 'details'), 'title', {'lang': 'EN'}).text = \
        'PhoneticSearch for Lyrion Music Server'
    entry = ET.SubElement(ET.SubElement(catalog, 'plugins'), 'plugin', {
        'name': 'PhoneticSearch', 'version': version,
        'minTarget': source_install.findtext('targetApplication/minVersion') or '',
        'maxTarget': source_install.findtext('targetApplication/maxVersion') or '*',
    })
    ET.SubElement(entry, 'title', {'lang': 'EN'}).text = 'PhoneticSearch'
    ET.SubElement(entry, 'desc', {'lang': 'EN'}).text = \
        'Phonetic search for artists, albums, tracks and genres.'
    ET.SubElement(entry, 'desc', {'lang': 'DE'}).text = \
        'Phonetische Suche nach Interpreten, Alben, Titeln und Genres.'
    ET.SubElement(entry, 'url').text = f'{REPO}/releases/download/v{version}/{output_name}'
    ET.SubElement(entry, 'link').text = REPO
    ET.SubElement(entry, 'icon').text = ICON
    ET.SubElement(entry, 'sha').text = digest(payload, 'sha1')
    ET.SubElement(entry, 'creator').text = 'oweitman'
    ET.indent(catalog, space='  ')
    (feed / 'public.xml').write_bytes(
        b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(catalog, encoding='utf-8') + b'\n')
    state = {
        'input_sha256': report['sha256'],
        'package_sha256': digest(payload),
        'package_sha1': digest(payload, 'sha1'),
        'revision': report['revision'],
        'version': version,
    }
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'feed=updated version={version} sha1={state["package_sha1"]}')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', type=Path, default=ROOT / 'dist/PhoneticSearch-ci.zip')
    parser.add_argument('--report', type=Path, default=ROOT / 'dist/build-report.json')
    parser.add_argument('--feed', type=Path, default=ROOT / 'feed')
    parser.add_argument('--run-number', type=int, default=int(os.environ.get('GITHUB_RUN_NUMBER', '1')))
    args = parser.parse_args()
    build(args.package, args.report, args.feed, args.run_number)
