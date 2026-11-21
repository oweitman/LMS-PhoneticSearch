"""Validate, stage and inspect one CI-built SQLite extension."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'scripts/platforms.json'
BUNDLE = ROOT / '.bundle'


def targets() -> dict[str, dict]:
    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    assert data['schema'] == 1 and data['sqlite_source'] == '3.45.1'
    entries = data['targets']
    found = {entry['id']: entry for entry in entries}
    assert len(found) == len(entries) == 6
    assert all(entry['id'] in (
        'linux-x86_64', 'linux-aarch64', 'linux-armv7', 'macos-x86_64',
        'macos-arm64', 'windows-x86_64') for entry in entries)
    return found


def matrix() -> None:
    print('matrix=' + json.dumps({'include': list(targets().values())}, separators=(',', ':')))


def preflight(target: str) -> None:
    assert target in targets(), target
    header = (ROOT / 'vendor/sqlite/sqlite3.h').read_text(errors='replace')
    assert '#define SQLITE_VERSION_NUMBER 3045001' in header
    system = platform.system().lower()
    machine = platform.machine().lower()
    expected = {
        'linux-x86_64': ('linux', ('x86_64', 'amd64')),
        'linux-aarch64': ('linux', ('aarch64', 'arm64')),
        'linux-armv7': ('linux', ('armv7l', 'armv7', 'arm')),
        'macos-x86_64': ('darwin', ('x86_64',)),
        'macos-arm64': ('darwin', ('arm64', 'aarch64')),
        'windows-x86_64': ('windows', ('amd64', 'x86_64')),
    }[target]
    assert system == expected[0] and machine in expected[1], (target, system, machine)
    print(f'preflight=ok target={target} host={system}/{machine}')


def staged(target: str) -> tuple[Path, dict]:
    entry = targets()[target]
    directory = BUNDLE / target
    metadata = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
    relative = f'Bin/{target}/{entry["binary"]}'
    assert metadata['id'] == target and metadata['file'] == relative
    assert metadata['sqlite_source'] == '3.45.1'
    assert metadata['smoke'] == entry['smoke']
    binary = directory / relative
    assert binary.is_file() and hashlib.sha256(binary.read_bytes()).hexdigest() == metadata['sha256']
    return binary, metadata


def stage(target: str, source: Path) -> None:
    entry = targets()[target]
    source = source.resolve(strict=True)
    directory = BUNDLE / target
    relative = f'Bin/{target}/{entry["binary"]}'
    binary = directory / relative
    binary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, binary)
    metadata = {
        'id': target,
        'file': relative,
        'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
        'sqlite_source': '3.45.1',
        'smoke': entry['smoke'],
        'build_revision': os.environ.get('GITHUB_SHA', 'local'),
    }
    (directory / 'metadata.json').write_text(
        json.dumps(metadata, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    staged(target)
    print(f'staged={target} sha256={metadata["sha256"]}')


def loader_fixture(target: str) -> None:
    binary, metadata = staged(target)
    fixture = ROOT / '.poc-build/loader-root'
    destination = fixture / metadata['file']
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(binary, destination)
    loader = fixture / 'lib/Plugins/PhoneticSearch/Loader.pm'
    loader.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'src/lib/Plugins/PhoneticSearch/Loader.pm', loader)
    manifest = fixture / 'Bin/manifest.json'
    manifest.write_text(json.dumps({target: metadata}, sort_keys=True), encoding='utf-8')
    print(f'fixture={fixture}')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('matrix', 'preflight', 'stage', 'validate', 'loader-fixture'))
    parser.add_argument('target', nargs='?')
    parser.add_argument('source', nargs='?', type=Path)
    args = parser.parse_args()
    if args.command == 'matrix':
        matrix()
    else:
        assert args.target in targets(), args.target
        if args.command == 'preflight':
            preflight(args.target)
        elif args.command == 'stage':
            assert args.source is not None
            stage(args.target, args.source)
        elif args.command == 'validate':
            staged(args.target)
            print(f'validated={args.target}')
        elif args.command == 'loader-fixture':
            loader_fixture(args.target)


if __name__ == '__main__':
    main()
