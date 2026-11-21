"""Remove only PhoneticSearch data after stopping LMS.

This is a manual pre-uninstall step because LMS has no verified pre-uninstall
hook. Without --apply, only the selected paths are printed.
"""
import argparse
import shutil
from pathlib import Path


def selected_paths(config_dir):
    root = config_dir.resolve(strict=True)
    cache = root / 'cache' / 'PhoneticSearch'
    prefs = root / 'prefs' / 'plugin' / 'phoneticsearch.prefs'
    for path in (cache, prefs):
        if path.is_symlink() or path.resolve().parent not in (
                root / 'cache', root / 'prefs' / 'plugin'):
            raise ValueError(f'Unsafe target: {path}')
    return cache, prefs


def cleanup(config_dir, apply=False):
    cache, prefs = selected_paths(config_dir)
    for path in (cache, prefs):
        print(f'{"remove" if apply else "would remove"}: {path}')
        if apply and path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    cleanup(args.config_dir, args.apply)


if __name__ == '__main__':
    main()
