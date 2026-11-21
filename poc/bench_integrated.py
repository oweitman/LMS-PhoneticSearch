"""Benchmark the packaged Perl worker on a disposable copy of LMS 9.2 data.

Run in an isolated LMS test workspace.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path


ROOT = Path(os.environ.get('LMS_POC_ROOT', Path(__file__).resolve().parents[1]))
SOURCE = ROOT / 'data/9.2/config/cache/library.db'
BENCH = ROOT / 'data/9.2/config/cache/PhoneticSearch/bench'
PLUGIN = '/config/cache/InstalledPlugins/Plugins/PhoneticSearch'
PERL = ['perl', '-I/lms/CPAN/arch/5.40', '-I/lms/CPAN',
        '-I/lms/CPAN/arch/5.40/x86_64-linux-thread-multi']


def prepare(count):
    BENCH.mkdir(parents=True, exist_ok=True)
    for name in ('library.db', 'index.db', 'status.json'):
        (BENCH / name).unlink(missing_ok=True)
    source = sqlite3.connect(f'file:{SOURCE}?mode=ro', uri=True)
    target = sqlite3.connect(BENCH / 'library.db')
    source.backup(target)
    source.close()
    before = target.execute('SELECT count(*) FROM tracks').fetchone()[0]
    target.executemany(
        'INSERT INTO tracks(url,title,audio,remote,updated_time) VALUES (?,?,1,0,?)',
        ((f'file:///bench-{i}', f'Benchmark Track {i}', 1795200000 + i)
         for i in range(count)))
    target.commit()
    target.close()
    return before


def worker(full):
    args = ['docker', 'exec', '-u', '1000:1000',
            'lms-phoneticsearch-poc-92', *PERL,
            f'{PLUGIN}/Bin/indexer-worker.pl', PLUGIN,
            '/config/cache/PhoneticSearch/bench/library.db',
            '/config/cache/PhoneticSearch/bench/index.db',
            '/config/cache/PhoneticSearch/bench/status.json', str(int(full))]
    started = time.perf_counter()
    proc = subprocess.run(args, capture_output=True, text=True, timeout=240)
    duration = time.perf_counter() - started
    status = json.loads((BENCH / 'status.json').read_text())
    if proc.returncode or status['state'] != 'ready':
        raise RuntimeError((proc.returncode, proc.stderr, status))
    return duration, status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tracks', type=int, default=100000)
    parser.add_argument('--reuse-source', action='store_true')
    parser.add_argument('--delta-tracks', type=int, default=0)
    parser.add_argument('--delta-names', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.tracks <= 500000:
        parser.error('tracks must be between 1 and 500000')
    if args.reuse_source:
        connection = sqlite3.connect(f'file:{BENCH / "library.db"}?mode=ro', uri=True)
        before = connection.execute('SELECT count(*) FROM tracks').fetchone()[0] - args.tracks
        connection.close()
        (BENCH / 'index.db').unlink(missing_ok=True)
        (BENCH / 'status.json').unlink(missing_ok=True)
    else:
        before = prepare(args.tracks)
    build_wall, build = worker(True)
    idle_wall, idle = worker(False)
    delta_result = {}
    if args.delta_tracks:
        connection = sqlite3.connect(BENCH / 'library.db')
        watermark = connection.execute(
            'SELECT coalesce(max(updated_time),0) FROM tracks').fetchone()[0] + 2
        ids = [row[0] for row in connection.execute(
            'SELECT id FROM tracks ORDER BY id LIMIT ?', (args.delta_tracks,))]
        if args.delta_names:
            connection.executemany(
                'UPDATE tracks SET updated_time=?,title=? WHERE id=?',
                ((watermark, f'Benchmark Updated Name {track_id}', track_id)
                 for track_id in ids))
        else:
            connection.executemany('UPDATE tracks SET updated_time=? WHERE id=?',
                                   ((watermark, track_id) for track_id in ids))
        connection.commit()
        connection.close()
        delta_wall, delta = worker(False)
        delta_result = {'delta_tracks': len(ids),
                        'delta_wall_s': round(delta_wall, 3),
                        'delta_worker_ms': delta['duration_ms'],
                        'delta_mode': delta['mode'],
                        'delta_recent_tracks': delta['recent_tracks'],
                        'delta_changes': delta['changes']}
    index = sqlite3.connect(f'file:{BENCH / "index.db"}?mode=ro', uri=True)
    entities = index.execute('SELECT count(*) FROM ps_entity').fetchone()[0]
    integrity = index.execute('PRAGMA integrity_check').fetchone()[0]
    index.close()
    assert entities >= before + args.tracks and integrity == 'ok'
    print(json.dumps({'base_tracks': before, 'added_tracks': args.tracks,
                      'entities': entities, 'integrity': integrity,
                      'build_wall_s': round(build_wall, 3),
                      'build_worker_ms': build['duration_ms'],
                      'idle_wall_s': round(idle_wall, 3),
                      'idle_worker_ms': idle['duration_ms'],
                      'idle_changes': idle['changes'],
                      'source_bytes': (BENCH / 'library.db').stat().st_size,
                      'index_bytes': (BENCH / 'index.db').stat().st_size,
                      **delta_result},
                     sort_keys=True))


if __name__ == '__main__':
    main()
