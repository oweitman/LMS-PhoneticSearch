"""Kill a packaged Perl staging worker on a disposable LMS 9.2 DB copy.

Prerequisite: python3 -m poc.bench_integrated --tracks 100000
Run only in an isolated LMS test workspace.
"""
import hashlib
import json
import shutil
import subprocess
import time

from poc.bench_integrated import BENCH, PLUGIN, PERL


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command():
    return ['docker', 'exec', '-u', '1000:1000',
            'lms-phoneticsearch-poc-92', *PERL,
            f'{PLUGIN}/Bin/indexer-worker.pl', PLUGIN,
            '/config/cache/PhoneticSearch/bench/library-replaced.db',
            '/config/cache/PhoneticSearch/bench/index.db',
            '/config/cache/PhoneticSearch/bench/kill-status.json', '1']


def worker_pid():
    result = subprocess.run(
        ['docker', 'exec', 'lms-phoneticsearch-poc-92', 'ps', '-eo', 'pid,args'],
        capture_output=True, text=True, check=True)
    for line in result.stdout.splitlines():
        if 'indexer-worker.pl' in line and 'library-replaced.db' in line:
            return int(line.strip().split(None, 1)[0])
    return None


def main():
    source = BENCH / 'library.db'
    replacement = BENCH / 'library-replaced.db'
    index = BENCH / 'index.db'
    assert source.is_file() and index.is_file(), 'Create 100k benchmark fixture first'
    shutil.copy2(source, replacement)
    old_digest = digest(index)
    stages_before = set(BENCH.glob('phonetic-stage-*'))
    process = subprocess.Popen(command(), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 20
    pid = None
    while time.monotonic() < deadline:
        pid = worker_pid()
        stages = set(BENCH.glob('phonetic-stage-*')) - stages_before
        if pid and stages:
            break
        if process.poll() is not None:
            raise RuntimeError(f'worker ended before kill: {process.communicate()}')
        time.sleep(.1)
    else:
        raise TimeoutError('staging worker did not start')
    subprocess.run(['docker', 'exec', 'lms-phoneticsearch-poc-92',
                    'kill', '-9', str(pid)], check=True)
    process.communicate(timeout=10)
    assert process.returncode != 0
    assert digest(index) == old_digest, 'active index changed before stage swap'
    recovered = subprocess.run(command(), capture_output=True, text=True,
                               timeout=240)
    status = json.loads((BENCH / 'kill-status.json').read_text())
    assert recovered.returncode == 0 and status['state'] == 'ready', (recovered, status)
    print(f'worker_kill=ok old_index_preserved=1 recovery={status["mode"]} '
          f'changes={status["changes"]} orphan_stages={len(stages)}')


if __name__ == '__main__':
    main()
