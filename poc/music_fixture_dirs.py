"""Temporarily add/remove the isolated music fixture in LMS 9.2 prefs.

Run only while lms92 is stopped, from the remote POC project directory.
"""
import argparse
from pathlib import Path


PREFS = Path('data/9.2/config/prefs/server.prefs')
ORIGINAL = 'mediadirs:\n- /music\n'
WITH_FIXTURE = 'mediadirs:\n- /music\n- /music-fixture\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('enable', 'disable'))
    args = parser.parse_args()
    text = PREFS.read_text()
    if args.action == 'enable':
        assert ORIGINAL in text and WITH_FIXTURE not in text
        text = text.replace(ORIGINAL, WITH_FIXTURE, 1)
    else:
        assert WITH_FIXTURE in text
        text = text.replace(WITH_FIXTURE, ORIGINAL, 1)
    PREFS.write_text(text)
    print(f'music_fixture={args.action}')


if __name__ == '__main__':
    main()
