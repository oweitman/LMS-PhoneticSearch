"""Create a local, Linux x86_64/LMS 9.2 test ZIP (not a release)."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src'
OUTPUT = ROOT / 'dist' / 'PhoneticSearch-linux-x86_64-lms92-POC.zip'
FILES = (
    'install.xml', 'Plugin.pm', 'Settings.pm', 'strings.txt',
    'Bin/manifest.json', 'Bin/indexer-worker.pl',
    'Bin/linux-x86_64/spellfix.so',
    'HTML/EN/plugins/PhoneticSearch/settings/basic.html',
    'HTML/EN/plugins/PhoneticSearch/html/icon.png',
    'lib/Plugins/PhoneticSearch/API.pm',
    'lib/Plugins/PhoneticSearch/Config.pm',
    'lib/Plugins/PhoneticSearch/Indexer.pm',
    'lib/Plugins/PhoneticSearch/Loader.pm',
    'lib/Plugins/PhoneticSearch/Scheduler.pm',
    'lib/Plugins/PhoneticSearch/Search.pm',
)


def build(output: Path = OUTPUT) -> tuple[Path, str]:
    manifest = json.loads((SOURCE / 'Bin/manifest.json').read_text(encoding='utf-8'))
    target = manifest['linux-x86_64']
    binary = SOURCE / target['file']
    assert binary.is_file() and target['file'] in FILES
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == target['sha256']
    install = ElementTree.parse(SOURCE / 'install.xml').getroot()
    assert install.findtext('module') == 'Plugins::PhoneticSearch::Plugin'
    assert install.findtext('targetApplication/minVersion') == '9.1.0'
    assert install.findtext('icon') == ('https://raw.githubusercontent.com/oweitman/'
                                      'LMS-PhoneticSearch/main/src/HTML/EN/plugins/'
                                      'PhoneticSearch/html/icon.png')
    assert (SOURCE / 'HTML/EN/plugins/PhoneticSearch/html/icon.png').read_bytes().startswith(
        b'\x89PNG\r\n\x1a\n')
    for relative in FILES:
        assert (SOURCE / relative).is_file(), relative

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in FILES:
            info = zipfile.ZipInfo(f'PhoneticSearch/{relative}', (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (SOURCE / relative).read_bytes())
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert sorted(archive.namelist()) == sorted(f'PhoneticSearch/{name}' for name in FILES)
        assert hashlib.sha256(archive.read('PhoneticSearch/Bin/linux-x86_64/spellfix.so')).hexdigest() == target['sha256']
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + '.sha256').write_text(
        f'{digest}  {output.name}\n', encoding='ascii')
    return output, digest


if __name__ == '__main__':
    path, checksum = build()
    print(f'{path}\nSHA-256 {checksum}')
