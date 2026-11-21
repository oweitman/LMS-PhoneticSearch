"""Test protected LMS 9.2 settings actions on the isolated plugin.

Use --cleanup to exercise the destructive action and restart only lms92.
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from poc.test_live_plugin_api import rpc
from poc.test_live_settings import URL, page
from poc.verify_plugin_index import main as verify_index


ROOT = Path(os.environ.get('LMS_POC_ROOT', Path(__file__).resolve().parents[1]))
CACHE = ROOT / 'data/9.2/config/cache/PhoneticSearch'
PREFS = ROOT / 'data/9.2/config/prefs/plugin/phoneticsearch.prefs'


def submit(action, confirmation='', omit_token=False):
    form, body = page()
    assert len(form.fields.get('phoneticsearch_action_token', '')) == 64
    assert f'value="{action}"' in body
    if omit_token:
        form.fields.pop('phoneticsearch_action_token')
    form.fields.update({'saveSettings': '1',
                        'phoneticsearch_action': action,
                        'phoneticsearch_confirm': confirmation})
    request = Request(form.action, data=urlencode(form.fields).encode())
    with urlopen(request, timeout=15) as response:
        return response.read().decode('utf-8')


def wait_for(operation, previous=None):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        status = rpc('phoneticsearch', 'status', '?')['result']
        if (status.get('state') == 'ready' and status.get('last_mode') == operation
                and (previous is None or status.get('last_success') != previous)):
            return status
        time.sleep(.2)
    raise TimeoutError(f'{operation} did not complete: {status}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cleanup', action='store_true')
    args = parser.parse_args()
    server = rpc('serverstatus', '0', '10')['result']
    assert server['version'] == '9.2.0' and server['httpport'] == '9002'
    prior = rpc('phoneticsearch', 'status', '?')['result'].get('last_success')
    rejected_token = submit('verify', omit_token=True)
    assert 'phoneticsearch_action_notice' in rejected_token
    assert rpc('phoneticsearch', 'status', '?')['result'].get('last_success') == prior
    submit('verify')
    verified = wait_for('verify', prior)
    assert verified['last_verified'] == 1499, verified
    assert '1499' in page()[1]
    prior = verified['last_success']
    submit('rebuild')
    rebuilt = wait_for('full', prior)
    worker = json.loads((CACHE / 'worker-status.json').read_text())
    assert worker['operation'] == 'rebuild' and worker['changes'] == 1499, worker
    verify_index()
    print('admin_actions=ok token_required=1 verify=1499 rebuild=1499')
    if not args.cleanup:
        return
    rejected = submit('cleanup', 'NO')
    assert 'phoneticsearch_action_notice' in rejected
    assert CACHE.is_dir()
    submit('cleanup', 'DELETE')
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        state = rpc('phoneticsearch', 'status', '?')['result']['state']
        if state == 'cleanup_complete':
            break
        time.sleep(.2)
    else:
        raise TimeoutError('cleanup action did not complete')
    assert not CACHE.exists() and not PREFS.exists()
    assert 'phoneticsearch_cleanup_complete' in page()[1]
    subprocess.run(['docker', 'compose', '-f', 'compose.poc.yaml',
                    'stop', 'lms92'], check=True, cwd=ROOT)
    assert not CACHE.exists() and not PREFS.exists(), 'shutdown restored plugin data'
    subprocess.run(['docker', 'compose', '-f', 'compose.poc.yaml',
                    'start', 'lms92'], check=True, cwd=ROOT)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if rpc('phoneticsearch', 'status', '?')['result']['state'] == 'ready':
                verify_index()
                print('admin_cleanup=ok rejected_without_DELETE=1 '
                      'removed_cache_and_prefs_after_stop=1 restart_rebuilt=1')
                return
        except Exception:
            pass
        time.sleep(.5)
    raise TimeoutError('plugin did not rebuild after cleanup and restart')


if __name__ == '__main__':
    main()
