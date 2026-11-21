"""Import one generated WAV through the isolated LMS 9.2 scanner and API."""
import argparse
import sqlite3
import time
import wave
from pathlib import Path

from poc.test_live_plugin_api import rpc


TITLE = 'PhoneticSearch POC Unique Sound 2026'
WAV = Path('poc/music-fixture') / f'{TITLE}.wav'
SOURCE = Path('data/9.2/config/cache/library.db')


def source_count():
    connection = sqlite3.connect(f'file:{SOURCE}?mode=ro', uri=True)
    count = connection.execute(
        'SELECT count(*) FROM tracks WHERE url LIKE ?',
        ('%' + TITLE.replace(' ', '%') + '%',)).fetchone()[0]
    connection.close()
    return count


def hits():
    result = rpc('phoneticsearch', '0', '20',
                 f'query:{TITLE}', 'type:track')['result']
    return [row for row in result.get('results_loop', [])
            if row['name'] == TITLE]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cleanup', action='store_true')
    args = parser.parse_args()
    assert rpc('serverstatus', '0', '10')['result']['version'] == '9.2.0'
    if args.cleanup:
        WAV.unlink(missing_ok=True)
        rpc('rescan')
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            status = rpc('phoneticsearch', 'status', '?')['result']
            if source_count() == 0 and status['state'] == 'ready' and not hits():
                print('import_cleanup=ok source_track=0 search_hit=0')
                return
            time.sleep(.25)
        raise TimeoutError('fixture removal did not reconcile')
    assert not WAV.exists() and source_count() == 0
    WAV.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with wave.open(str(WAV), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b'\0\0' * 44100)
    rpc('rescan')
    saw_updating = False
    source_lag = None
    deadline = started + 90
    while time.monotonic() < deadline:
        if source_lag is None and source_count():
            source_lag = time.monotonic() - started
        status = rpc('phoneticsearch', 'status', '?')['result']
        saw_updating |= status['state'] == 'updating'
        if status['state'] == 'ready' and hits():
            search_lag = time.monotonic() - started
            assert saw_updating and source_lag is not None
            print(f'import=ok source_lag_s={source_lag:.3f} '
                  f'search_lag_s={search_lag:.3f} '
                  f'scan_observed=1 name={TITLE}')
            return
        time.sleep(.25)
    raise TimeoutError(f'import missing: source_lag={source_lag} scan={saw_updating}')


if __name__ == '__main__':
    main()
