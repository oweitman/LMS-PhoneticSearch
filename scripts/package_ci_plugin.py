"""Package every validated binary available in this workflow run."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

from ci_binary import BUNDLE, ROOT, staged, targets
from package_test_plugin import FILES as TEST_FILES

OUTPUT = ROOT / 'dist/PhoneticSearch-ci.zip'
BASE_FILES = tuple(name for name in TEST_FILES if name not in (
    'Bin/manifest.json', 'Bin/linux-x86_64/spellfix.so'))


def build() -> tuple[Path, dict]:
    supported = targets()
    manifest = {'schema': 1}
    entries = [(f'PhoneticSearch/{name}', (ROOT / 'src' / name).read_bytes())
               for name in BASE_FILES]
    included = []
    for target in supported:
        if not (BUNDLE / target / 'metadata.json').is_file():
            continue
        binary, metadata = staged(target)
        manifest[target] = {key: metadata[key] for key in (
            'file', 'sha256', 'sqlite_source', 'smoke', 'build_revision')}
        entries.append((f'PhoneticSearch/{metadata["file"]}', binary.read_bytes()))
        included.append(target)
    if not included:
        raise SystemExit('No validated binaries were produced; refusing to package')
    entries.append(('PhoneticSearch/Bin/manifest.json',
                    (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(entries):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    with zipfile.ZipFile(OUTPUT) as archive:
        assert archive.testzip() is None
        assert sorted(archive.namelist()) == sorted(name for name, _ in entries)
    report = {
        'revision': os.environ.get('GITHUB_SHA', 'local'),
        'included': included,
        'missing': [target for target in supported if target not in included],
        'sha256': hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
        'complete': len(included) == len(supported),
    }
    (OUTPUT.parent / 'build-report.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (OUTPUT.parent / 'PhoneticSearch-ci.zip.sha256').write_text(
        f'{report["sha256"]}  {OUTPUT.name}\n', encoding='ascii')
    return OUTPUT, report


if __name__ == '__main__':
    output, result = build()
    print(json.dumps({'file': str(output), **result}, indent=2))
