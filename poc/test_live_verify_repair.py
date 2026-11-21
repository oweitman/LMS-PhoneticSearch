"""Corrupt only the isolated plugin index and verify UI-triggered repair."""
import json
import sqlite3
import time

from poc.lms_index_probe import load_extension
from poc.test_live_admin_actions import CACHE, submit, wait_for
from poc.test_live_plugin_api import rpc
from poc.verify_plugin_index import main as verify_index


def main():
    server = rpc('serverstatus', '0', '10')['result']
    assert server['version'] == '9.2.0' and server['httpport'] == '9002'
    index = sqlite3.connect(CACHE / 'index.db')
    load_extension(index)
    row = index.execute(
        "SELECT entity_id FROM ps_entity WHERE entity_type='artist' "
        "AND original='Alphaville' LIMIT 1").fetchone()
    assert row, 'Alphaville artist missing'
    index.execute(
        "UPDATE ps_entity SET original='Alphaville POC Corrupted' "
        "WHERE entity_type='artist' AND entity_id=?", row)
    index.commit()
    index.close()
    try:
        submit('verify')
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            status = rpc('phoneticsearch', 'status', '?')['result']
            try:
                worker = json.loads((CACHE / 'worker-status.json').read_text())
            except FileNotFoundError:
                time.sleep(.2)
                continue
            if (status['state'] == 'ready' and worker['operation'] == 'rebuild'):
                verify_index()
                print('verify_repair=ok stale_detected=1 rebuild=full')
                return
            time.sleep(.2)
        raise TimeoutError(f'verification did not repair index: {status}, {worker}')
    except Exception:
        # Leave the isolated test service with a valid index even if the
        # verification path fails. The failure still propagates to the caller.
        submit('rebuild')
        wait_for('full')
        raise


if __name__ == '__main__':
    main()
